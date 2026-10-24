"""曲・フレーズ・グループのモデルと、それらへの操作（変換、選択、合体、分割など）。

フレーズとグループは固定の ID で扱う。表示上の番号との変換は UI 側の責務。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .kana import is_fixable, is_valid_reading
from .repository import Pokemon
from .segmenter import Combination, Converter, UsedByRank, empty_used

DEFAULT_CHANNEL = 1


@dataclass
class Phrase:
    id: int
    text: str
    channel: int = DEFAULT_CHANNEL
    locked: bool = False
    group_id: int | None = None
    combinations: list[Combination] = field(default_factory=list)
    # 選択情報: ユーザーが決めたポケモンの並び。候補とは別に持ち、変換し直しても残る
    selection: list[Pokemon] = field(default_factory=list)
    # 「省略しない」に設定した ー・っ の文字の位置（0始まり）
    fixed_positions: set[int] = field(default_factory=set)

    def selected_names(self) -> list[str]:
        return [p.name for p in self.selection]


@dataclass
class Group:
    id: int
    name: str


@dataclass
class Song:
    title: str = ""
    allow_duplicates: bool = True
    phrases: list[Phrase] = field(default_factory=list)
    groups: list[Group] = field(default_factory=list)
    next_phrase_id: int = 1
    next_group_id: int = 1

    # ---- 参照 ----

    def phrase(self, phrase_id: int) -> Phrase:
        return self.phrases[self.index_of(phrase_id)]

    def index_of(self, phrase_id: int) -> int:
        for i, phrase in enumerate(self.phrases):
            if phrase.id == phrase_id:
                return i
        raise ValueError(f"フレーズ(id={phrase_id})が見つかりません")

    def group(self, group_id: int) -> Group:
        for group in self.groups:
            if group.id == group_id:
                return group
        raise ValueError(f"グループ g{group_id} が見つかりません")

    def group_members(self, group_id: int) -> list[Phrase]:
        """グループのメンバーを歌詞の順に返す。"""
        self.group(group_id)
        return [p for p in self.phrases if p.group_id == group_id]

    # ---- フレーズの追加・削除・合体・分割 ----

    def add_phrase(self, text: str) -> Phrase:
        phrase = Phrase(self._new_phrase_id(), _validated_text(text))
        self.phrases.append(phrase)
        return phrase

    def edit_phrase(self, phrase_id: int, text: str) -> Phrase:
        """フレーズの文字列を変更する。候補・選択情報・省略しない設定はリセットし、ID・チャンネル・グループは引き継ぐ。"""
        phrase = self._unlocked(phrase_id)
        phrase.text = _validated_text(text)
        phrase.combinations = []
        phrase.selection = []
        phrase.fixed_positions = set()
        return phrase

    def remove_phrase(self, phrase_id: int) -> None:
        del self.phrases[self.index_of(phrase_id)]
        self._remove_empty_groups()

    def merge(self, phrase_ids: list[int]) -> Phrase:
        """連続したフレーズを1つにする。選択情報は順につなげて引き継ぎ、候補は消える。"""
        if len(phrase_ids) < 2:
            raise ValueError("合体するフレーズを2つ以上指定してください")
        indexes = sorted(self.index_of(pid) for pid in phrase_ids)
        if len(set(indexes)) != len(indexes) or indexes != list(range(indexes[0], indexes[-1] + 1)):
            raise ValueError("合体できるのは連続したフレーズだけです")
        targets = [self.phrases[i] for i in indexes]
        for phrase in targets:
            _require_unlocked(phrase)

        first = targets[0]
        merged = Phrase(
            id=first.id,
            text="".join(p.text for p in targets),
            channel=first.channel,
            group_id=first.group_id,
            selection=[p for phrase in targets for p in phrase.selection],
            fixed_positions=_shifted_fixed_positions(targets),
        )
        self.phrases[indexes[0] : indexes[-1] + 1] = [merged]
        self._remove_empty_groups()
        return merged

    def split(self, phrase_id: int, position: int) -> tuple[Phrase, Phrase]:
        """先頭から position 文字目の後ろで2つに分ける。どちらも候補と選択情報は消える。"""
        index = self.index_of(phrase_id)
        phrase = self.phrases[index]
        _require_unlocked(phrase)
        if not 1 <= position < len(phrase.text):
            raise ValueError(f"分割位置は 1〜{len(phrase.text) - 1} で指定してください")
        head, tail = phrase.text[:position], phrase.text[position:]
        if not is_valid_reading(tail):
            raise ValueError("拗音の途中（「し|ょ」など）では分割できません")

        fixed_head = {i for i in phrase.fixed_positions if i < position}
        fixed_tail = {i - position for i in phrase.fixed_positions if i >= position}
        first = Phrase(phrase.id, head, channel=phrase.channel, group_id=phrase.group_id, fixed_positions=fixed_head)
        second = Phrase(
            self._new_phrase_id(), tail, channel=phrase.channel, group_id=phrase.group_id, fixed_positions=fixed_tail
        )
        self.phrases[index : index + 1] = [first, second]
        return first, second

    # ---- 変換 ----

    def convert_phrase(self, phrase_id: int, converter: Converter) -> Phrase:
        """1フレーズだけ変換する。重複禁止モードでは、同じチャンネルの他のフレーズと同じ序列の重複を避ける。"""
        phrase = self.phrase(phrase_id)
        _require_unlocked(phrase)
        self._convert_targets([phrase], converter)
        return phrase

    def convert_all(self, converter: Converter) -> None:
        """ロック中を除くすべてのフレーズを、歌詞の順に変換し直す。"""
        self._convert_targets([p for p in self.phrases if not p.locked], converter)

    def convert_group(self, group_id: int, converter: Converter) -> None:
        """グループ内のロック中でないフレーズを、歌詞の順に変換し直す。"""
        targets = [p for p in self.group_members(group_id) if not p.locked]
        if not targets:
            raise ValueError("変換できるフレーズがありません（すべてロック中です）")
        self._convert_targets(targets, converter)

    def _convert_targets(self, targets: list[Phrase], converter: Converter) -> None:
        if self.allow_duplicates:
            for phrase in targets:
                phrase.combinations = converter.convert(phrase.text, fixed_positions=phrase.fixed_positions)
            return

        # 対象外のフレーズ（ロック中を含む）の候補を先に押さえてから、対象を順に変換して積み上げる
        target_ids = {p.id for p in targets}
        used_by_channel: dict[int, UsedByRank] = {}
        for phrase in self.phrases:
            if phrase.id not in target_ids:
                _collect_used(phrase, used_by_channel.setdefault(phrase.channel, empty_used()))
        for phrase in targets:
            used = used_by_channel.setdefault(phrase.channel, empty_used())
            phrase.combinations = converter.convert(phrase.text, used, phrase.fixed_positions)

    # ---- 選択情報 ----

    def candidate(self, phrase_id: int, combination_index: int, slot_index: int, candidate_index: int) -> Pokemon:
        """組合わせ候補・枠・個別候補の番号（0始まり）から候補のポケモンを返す。"""
        phrase = self.phrase(phrase_id)
        if not phrase.combinations:
            raise ValueError("このフレーズはまだ変換されていません")
        _check_index(combination_index, phrase.combinations, "組合わせ候補")
        slots = phrase.combinations[combination_index].slots
        _check_index(slot_index, slots, "枠")
        candidates = slots[slot_index].candidates
        _check_index(candidate_index, candidates, "候補")
        return candidates[candidate_index].pokemon

    def add_selection(self, phrase_id: int, pokemon: Pokemon) -> None:
        """選択情報の末尾にポケモンを追加する。候補でも手入力でもよく、同じポケモンを2回入れてもよい。"""
        phrase = self._unlocked(phrase_id)
        phrase.selection.append(pokemon)

    def replace_selection(self, phrase_id: int, position: int, pokemon: Pokemon) -> None:
        """選択情報の指定した位置（0始まり）のポケモンを入れ替える。"""
        phrase = self._unlocked(phrase_id)
        _check_index(position, phrase.selection, "選択情報の位置")
        phrase.selection[position] = pokemon

    def remove_selection(self, phrase_id: int, position: int) -> None:
        phrase = self._unlocked(phrase_id)
        _check_index(position, phrase.selection, "選択情報の位置")
        del phrase.selection[position]

    def clear_selection(self, phrase_id: int) -> None:
        self._unlocked(phrase_id).selection.clear()

    def _unlocked(self, phrase_id: int) -> Phrase:
        phrase = self.phrase(phrase_id)
        _require_unlocked(phrase)
        return phrase

    # ---- チャンネル・ロック ----

    def set_channel(self, phrase_ids: list[int], channel: int) -> None:
        if channel < 1:
            raise ValueError("チャンネルは 1 以上の整数で指定してください")
        for pid in phrase_ids:
            self.phrase(pid).channel = channel

    def set_fixed(self, phrase_id: int, positions: list[int], fixed: bool) -> None:
        """ー・っ の文字の位置（0始まり）を「省略しない」にする／解除する。反映は変換し直したとき。"""
        phrase = self.phrase(phrase_id)
        for position in positions:
            if not 0 <= position < len(phrase.text):
                raise ValueError(f"位置は 1〜{len(phrase.text)} で指定してください")
            if not is_fixable(phrase.text[position]):
                raise ValueError(f"{position + 1}文字目「{phrase.text[position]}」は ー・っ ではありません")
        if fixed:
            phrase.fixed_positions |= set(positions)
        else:
            phrase.fixed_positions -= set(positions)

    def set_locked(self, phrase_ids: list[int], locked: bool) -> None:
        for pid in phrase_ids:
            self.phrase(pid).locked = locked

    # ---- グループ ----

    def create_group(self, phrase_ids: list[int], name: str = "") -> Group:
        if not phrase_ids:
            raise ValueError("グループにするフレーズを指定してください")
        targets = [self.phrase(pid) for pid in phrase_ids]
        for phrase in targets:
            if phrase.group_id is not None:
                raise ValueError(f"「{phrase.text}」は既にグループ g{phrase.group_id} に入っています")
        group = Group(self.next_group_id, name or f"グループ{self.next_group_id}")
        self.next_group_id += 1
        self.groups.append(group)
        for phrase in targets:
            phrase.group_id = group.id
        return group

    def remove_group(self, group_id: int) -> None:
        """グループを解除する。フレーズは残る。"""
        for phrase in self.group_members(group_id):
            phrase.group_id = None
        self.groups = [g for g in self.groups if g.id != group_id]

    def _remove_empty_groups(self) -> None:
        used_ids = {p.group_id for p in self.phrases}
        self.groups = [g for g in self.groups if g.id in used_ids]

    def _new_phrase_id(self) -> int:
        phrase_id = self.next_phrase_id
        self.next_phrase_id += 1
        return phrase_id


def normalize_phrase(text: str) -> str:
    """入力のゆれを吸収する（空白の除去、波ダッシュ等を長音符に統一）。"""
    text = "".join(text.split())
    for ch in "～〜−-":
        text = text.replace(ch, "ー")
    return text


def _validated_text(text: str) -> str:
    text = normalize_phrase(text)
    if not is_valid_reading(text):
        raise ValueError(f"「{text}」はひらがなと「ー」だけで入力してください")
    return text


def _require_unlocked(phrase: Phrase) -> None:
    if phrase.locked:
        raise ValueError(f"「{phrase.text}」はロック中です（unlock で解除できます）")


def _collect_used(phrase: Phrase, used: UsedByRank) -> None:
    for combination in phrase.combinations:
        for slot in combination.slots:
            for rank, candidate in enumerate(slot.candidates):
                used[rank].add(candidate.pokemon.id)
    # 選択情報はユーザーが決めた結果なので、第1序列として扱う
    for pokemon in phrase.selection:
        used[0].add(pokemon.id)


def _shifted_fixed_positions(phrases: list[Phrase]) -> set[int]:
    """合体するフレーズの「省略しない」設定を、合体後の文字の位置にずらして集める。"""
    result = set()
    offset = 0
    for phrase in phrases:
        result |= {offset + i for i in phrase.fixed_positions}
        offset += len(phrase.text)
    return result


def _check_index(index: int, items: list, label: str) -> None:
    if not 0 <= index < len(items):
        raise ValueError(f"{label}の番号は 1〜{len(items)} で指定してください")
