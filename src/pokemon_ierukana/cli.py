"""対話型のコンソールUI。入出力だけを担当し、変換や曲の操作は song / segmenter に任せる。

フレーズは表示順の番号（1から）、グループは g<ID>（例: g1）で指定する。内部の操作は ID で行う。
"""

from __future__ import annotations

from pathlib import Path

from .repository import PokemonIndex, load_pokemon
from .scoring import SCORE_LABELS, decode_score
from .segmenter import Combination, Converter
from .song import Phrase, Song
from .song_json import load_song, save_song

DEFAULT_SONG_DIR = Path(__file__).resolve().parents[2] / "data" / "songs"

HELP = """\
コマンド一覧（N はフレーズの番号、gK はグループ。<対象> には N と gK のどちらも使えます）
  add [フレーズ ...]           フレーズを追加（省略すると空行まで1行ずつ入力）
  del <N>                      フレーズを削除
  list                         フレーズと選択中のポケモンを一覧表示
  show <N>                     フレーズの候補を詳しく表示
  conv <対象> | conv all       変換（グループはメンバーを歌詞の順に。ロック中は飛ばす）
  combo <N> <C>                組合わせ候補 C を選択
  pick <N> <枠> <候補>         選択中の組合わせで、枠の個別候補を選択（手入力は取り消し）
  manual <N> <枠> <ポケモン>   枠にポケモンを手入力（名前または読み）
  merge <N> <M> ...            連続したフレーズを合体
  split <N> <位置>             先頭から<位置>文字目の後ろで2つに分割
  channel <対象> <C>           重複チャンネルを設定（同じチャンネルどうしで重複を避ける）
  lock <対象> / unlock <対象>  ロック／解除
  group <N> <M> ... [名前]     グループを作成
  ungroup <gK>                 グループを解除
  mode                         重複を許すモード / 許さないモードを切り替え
  title <名前>                 曲名を設定
  save [ファイル]              曲を JSON で保存（既定: data/songs/<曲名>.json）
  load <ファイル>              JSON から曲を読み込み
  help                         このヘルプを表示
  quit                         終了"""


def main() -> None:
    print("ポケモン言えるかな変換（help でコマンド一覧）")
    print("ポケモン一覧を読み込み中...")
    pokemon = load_pokemon()
    app = _App(Converter(pokemon), PokemonIndex(pokemon))
    while True:
        try:
            line = input(f"\n[{app.mode_label()}] > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        try:
            if not app.run(line):
                break
        except ValueError as e:
            print(f"エラー: {e}")
        except OSError as e:
            print(f"ファイルエラー: {e}")


class _App:
    def __init__(self, converter: Converter, index: PokemonIndex):
        self.converter = converter
        self.index = index
        self.song = Song()

    def mode_label(self) -> str:
        return "重複OK" if self.song.allow_duplicates else "重複NG"

    def run(self, line: str) -> bool:
        """1行のコマンドを実行する。終了するときは False を返す。"""
        # フレーズに空白は含まれず、Windows のパスの \ を壊さないよう単純な空白区切りにする
        command, *args = line.split()
        handler = getattr(self, f"cmd_{command}", None)
        if handler is None:
            raise ValueError(f"不明なコマンドです: {command}（help で一覧表示）")
        return handler(args) is not False

    def cmd_help(self, args: list[str]) -> None:
        print(HELP)

    def cmd_quit(self, args: list[str]) -> bool:
        return False

    # ---- フレーズの編集 ----

    def cmd_add(self, args: list[str]) -> None:
        texts = args
        if not texts:
            print("フレーズを1行ずつ入力してください（空行で終了）")
            texts = []
            while text := input("  フレーズ> ").strip():
                texts.append(text)
        for text in texts:
            try:
                phrase = self.song.add_phrase(text)
                print(f"  [{len(self.song.phrases)}] {phrase.text} を追加しました")
            except ValueError as e:
                print(f"  エラー: {e}")

    def cmd_del(self, args: list[str]) -> None:
        phrase = self._phrase(_single(args))
        self.song.remove_phrase(phrase.id)
        print(f"{phrase.text} を削除しました")

    def cmd_merge(self, args: list[str]) -> None:
        merged = self.song.merge([self._phrase(a).id for a in args])
        self._print_detail(merged)

    def cmd_split(self, args: list[str]) -> None:
        if len(args) != 2 or not args[1].isdigit():
            raise ValueError("split <N> <位置> の形で指定してください")
        first, second = self.song.split(self._phrase(args[0]).id, int(args[1]))
        print(f"「{first.text}」と「{second.text}」に分割しました")
        self.cmd_list([])

    # ---- 表示 ----

    def cmd_list(self, args: list[str]) -> None:
        if self.song.title:
            print(f"曲名: {self.song.title}")
        if not self.song.phrases:
            print("フレーズがありません（add で追加）")
        for phrase in self.song.phrases:
            print(self._headline(phrase))
        for group in self.song.groups:
            numbers = ", ".join(str(self._number(p)) for p in self.song.group_members(group.id))
            print(f"g{group.id} {group.name}: [{numbers}]")

    def cmd_show(self, args: list[str]) -> None:
        self._print_detail(self._phrase(_single(args)))

    # ---- 変換・選択 ----

    def cmd_conv(self, args: list[str]) -> None:
        target = _single(args)
        if target == "all":
            self.song.convert_all(self.converter)
            self.cmd_list([])
        elif target.startswith("g"):
            group_id = _group_id(target)
            self.song.convert_group(group_id, self.converter)
            for phrase in self.song.group_members(group_id):
                self._print_detail(phrase)
        else:
            self._print_detail(self.song.convert_phrase(self._phrase(target).id, self.converter))

    def cmd_combo(self, args: list[str]) -> None:
        phrase, (combination_index,) = self._phrase_and_numbers(args, 1)
        self.song.select_combination(phrase.id, combination_index)
        self._print_detail(phrase)

    def cmd_pick(self, args: list[str]) -> None:
        phrase, (slot_index, candidate_index) = self._phrase_and_numbers(args, 2)
        self.song.select_candidate(phrase.id, slot_index, candidate_index)
        self._print_detail(phrase)

    def cmd_manual(self, args: list[str]) -> None:
        if len(args) != 3 or not args[1].isdigit():
            raise ValueError("manual <N> <枠> <ポケモン> の形で指定してください")
        phrase = self._phrase(args[0])
        self.song.set_manual(phrase.id, int(args[1]) - 1, self.index.find(args[2]))
        self._print_detail(phrase)

    # ---- チャンネル・ロック・グループ ----

    def cmd_channel(self, args: list[str]) -> None:
        if len(args) != 2 or not args[1].isdigit():
            raise ValueError("channel <対象> <C> の形で指定してください")
        self.song.set_channel(self._target_ids(args[0]), int(args[1]))
        print(f"チャンネルを {args[1]} にしました。候補に反映するには変換し直してください")

    def cmd_lock(self, args: list[str]) -> None:
        self.song.set_locked(self._target_ids(_single(args)), True)
        print("ロックしました")

    def cmd_unlock(self, args: list[str]) -> None:
        self.song.set_locked(self._target_ids(_single(args)), False)
        print("ロックを解除しました")

    def cmd_group(self, args: list[str]) -> None:
        numbers = [a for a in args if a.isdigit()]
        name = " ".join(a for a in args if not a.isdigit())
        group = self.song.create_group([self._phrase(n).id for n in numbers], name)
        print(f"g{group.id}「{group.name}」を作成しました")

    def cmd_ungroup(self, args: list[str]) -> None:
        group_id = _group_id(_single(args))
        self.song.remove_group(group_id)
        print(f"g{group_id} を解除しました")

    # ---- 曲全体 ----

    def cmd_mode(self, args: list[str]) -> None:
        self.song.allow_duplicates = not self.song.allow_duplicates
        print(f"{self.mode_label()} モードにしました。候補に反映するには conv all で変換し直してください")

    def cmd_title(self, args: list[str]) -> None:
        self.song.title = " ".join(args)
        print(f"曲名を「{self.song.title}」にしました")

    def cmd_save(self, args: list[str]) -> None:
        path = Path(args[0]) if args else DEFAULT_SONG_DIR / f"{self.song.title or 'song'}.json"
        save_song(self.song, path)
        print(f"{path} に保存しました")

    def cmd_load(self, args: list[str]) -> None:
        path = Path(_single(args))
        self.song = load_song(path)
        print(f"{path} を読み込みました（{self.mode_label()} モード）")
        self.cmd_list([])

    # ---- 番号・対象の解釈 ----

    def _phrase(self, number: str) -> Phrase:
        if not number.isdigit() or not 1 <= int(number) <= len(self.song.phrases):
            raise ValueError(f"フレーズの番号は 1〜{len(self.song.phrases)} で指定してください")
        return self.song.phrases[int(number) - 1]

    def _phrase_and_numbers(self, args: list[str], count: int) -> tuple[Phrase, list[int]]:
        if len(args) != count + 1 or not all(a.isdigit() for a in args[1:]):
            raise ValueError(f"フレーズの番号に続けて、番号を {count} つ指定してください")
        return self._phrase(args[0]), [int(a) - 1 for a in args[1:]]

    def _target_ids(self, target: str) -> list[int]:
        """N ならそのフレーズ、gK ならグループのメンバーの ID を返す。"""
        if target.startswith("g"):
            return [p.id for p in self.song.group_members(_group_id(target))]
        return [self._phrase(target).id]

    def _number(self, phrase: Phrase) -> int:
        return self.song.index_of(phrase.id) + 1

    # ---- 表示の整形 ----

    def _headline(self, phrase: Phrase) -> str:
        tags = [f"ch{phrase.channel}"]
        if phrase.group_id is not None:
            tags.append(f"g{phrase.group_id}")
        if phrase.locked:
            tags.append("ロック")
        return f"[{self._number(phrase)}] ({' '.join(tags)}) {phrase.text} → {_summary(phrase)}"

    def _print_detail(self, phrase: Phrase) -> None:
        print(self._headline(phrase))
        for ci, combination in enumerate(phrase.combinations):
            _print_combination(ci, combination, ci == phrase.selected)


def _single(args: list[str]) -> str:
    if len(args) != 1:
        raise ValueError("対象を1つ指定してください")
    return args[0]


def _group_id(target: str) -> int:
    if not (target.startswith("g") and target[1:].isdigit()):
        raise ValueError("グループは g1 のように指定してください")
    return int(target[1:])


def _summary(phrase: Phrase) -> str:
    if not phrase.combinations:
        return "（未変換または変換できません）"
    return " / ".join(phrase.selected_names())


def _format_score(score: int) -> str:
    return " ".join(f"{label}={count}" for label, count in zip(SCORE_LABELS, decode_score(score)) if count)


def _print_combination(ci: int, combination: Combination, is_selected: bool) -> None:
    mark = "*" if is_selected else " "
    print(f" {mark}組合わせ{ci + 1}: {combination.pattern}  ({_format_score(combination.score)})")
    for si, slot in enumerate(combination.slots):
        options = []
        if slot.manual is not None:
            options.append(f"*手入力.{slot.manual.name}")
        for ki, candidate in enumerate(slot.candidates):
            selected = "*" if slot.manual is None and ki == slot.selected else " "
            options.append(f"{selected}{ki + 1}.{candidate.pokemon.name}")
        print(f"     枠{si + 1} {slot.text}: {'  '.join(options)}")
