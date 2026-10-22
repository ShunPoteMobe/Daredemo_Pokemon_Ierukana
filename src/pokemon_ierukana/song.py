"""曲・フレーズ・グループのモデルと、それらへの操作（変換、選択、合体、分割など）。

フレーズとグループは固定の ID で扱う。表示上の番号との変換は UI 側の責務。
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from .kana import is_valid_reading, to_morae
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
    selected: int = 0

    @property
    def selected_combination(self) -> Combination | None:
        return self.combinations[self.selected] if self.combinations else None

    def selected_names(self) -> list[str]:
        combination = self.selected_combination
        if combination is None:
            return []
        return [slot.result.name for slot in combination.slots]

    def clear_conversion(self) -> None:
        self.combinations = []
        self.selected = 0


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

    def remove_phrase(self, phrase_id: int) -> None:
        del self.phrases[self.index_of(phrase_id)]
        self._remove_empty_groups()

    def merge(self, phrase_ids: list[int]) -> Phrase:
        """連続したフレーズを1つにする。各フレーズの選択中の組合わせ候補を連結して引き継ぐ。"""
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
        )
        combination = _concat_selected_combinations(targets)
        if combination is not None:
            merged.combinations = [combination]

        self.phrases[indexes[0] : indexes[-1] + 1] = [merged]
        self._remove_empty_groups()
        return merged

    def split(self, phrase_id: int, position: int) -> tuple[Phrase, Phrase]:
        """先頭から position 文字目の後ろで2つに分ける。どちらも変換結果は消える。"""
        index = self.index_of(phrase_id)
        phrase = self.phrases[index]
        _require_unlocked(phrase)
        if not 1 <= position < len(phrase.text):
            raise ValueError(f"分割位置は 1〜{len(phrase.text) - 1} で指定してください")
        head, tail = phrase.text[:position], phrase.text[position:]
        if not is_valid_reading(tail):
            raise ValueError("拗音の途中（「し|ょ」など）では分割できません")

        first = Phrase(phrase.id, head, channel=phrase.channel, group_id=phrase.group_id)
        second = Phrase(self._new_phrase_id(), tail, channel=phrase.channel, group_id=phrase.group_id)
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
                phrase.combinations = converter.convert(phrase.text)
                phrase.selected = 0
            return

        # 対象外のフレーズ（ロック中を含む）の候補を先に押さえてから、対象を順に変換して積み上げる
        target_ids = {p.id for p in targets}
        used_by_channel: dict[int, UsedByRank] = {}
        for phrase in self.phrases:
            if phrase.id not in target_ids:
                _collect_used(phrase, used_by_channel.setdefault(phrase.channel, empty_used()))
        for phrase in targets:
            used = used_by_channel.setdefault(phrase.channel, empty_used())
            phrase.combinations = converter.convert(phrase.text, used)
            phrase.selected = 0

    # ---- 候補の選択・手入力 ----

    def select_combination(self, phrase_id: int, combination_index: int) -> None:
        phrase = self.phrase(phrase_id)
        _require_unlocked(phrase)
        _check_index(combination_index, phrase.combinations, "組合わせ候補")
        phrase.selected = combination_index

    def select_candidate(self, phrase_id: int, slot_index: int, candidate_index: int) -> None:
        """選択中の組合わせ候補の、指定した枠の個別ポケモン候補を選ぶ。手入力は取り消される。"""
        slot = self._selected_slot(phrase_id, slot_index)
        _check_index(candidate_index, slot.candidates, "候補")
        slot.selected = candidate_index
        slot.manual = None

    def set_manual(self, phrase_id: int, slot_index: int, pokemon: Pokemon) -> None:
        """選択中の組合わせ候補の、指定した枠にポケモンを手入力する。音数や一致度は問わない。"""
        self._selected_slot(phrase_id, slot_index).manual = pokemon

    def _selected_slot(self, phrase_id: int, slot_index: int):
        phrase = self.phrase(phrase_id)
        _require_unlocked(phrase)
        combination = phrase.selected_combination
        if combination is None:
            raise ValueError("このフレーズはまだ変換されていません")
        _check_index(slot_index, combination.slots, "枠")
        return combination.slots[slot_index]

    # ---- チャンネル・ロック ----

    def set_channel(self, phrase_ids: list[int], channel: int) -> None:
        if channel < 1:
            raise ValueError("チャンネルは 1 以上の整数で指定してください")
        for pid in phrase_ids:
            self.phrase(pid).channel = channel

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
            # 手入力は選択中の結果なので、第1序列として扱う
            if slot.manual is not None:
                used[0].add(slot.manual.id)


def _concat_selected_combinations(phrases: list[Phrase]) -> Combination | None:
    """各フレーズの選択中の組合わせ候補を、音の位置をずらしながら連結する。未変換が混ざれば None。"""
    if any(p.selected_combination is None for p in phrases):
        return None
    slots = []
    score = 0
    offset = 0
    for phrase in phrases:
        combination = phrase.selected_combination
        slots.extend(replace(s, start=s.start + offset, end=s.end + offset) for s in combination.slots)
        score += combination.score
        offset += len(to_morae(phrase.text))
    return Combination(slots, score)


def _check_index(index: int, items: list, label: str) -> None:
    if not 0 <= index < len(items):
        raise ValueError(f"{label}の番号は 1〜{len(items)} で指定してください")
