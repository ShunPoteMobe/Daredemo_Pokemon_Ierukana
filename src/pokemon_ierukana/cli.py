"""対話型のコンソールUI。入出力だけを担当し、変換や曲の操作は song / segmenter に任せる。

フレーズは表示順の番号（1から）、グループは g<ID>（例: g1）で指定する。内部の操作は ID で行う。
"""

from __future__ import annotations

from pathlib import Path

from .kana import is_fixable
from .repository import PokemonIndex, load_pokemon
from .segmenter import Combination, Converter
from .song import Phrase, Song
from .song_json import load_song, save_song

DEFAULT_SONG_DIR = Path(__file__).resolve().parents[2] / "data" / "songs"

HELP = """\
コマンド一覧（N はフレーズの番号、gK はグループ。<対象> には N と gK のどちらも使えます）
  add [フレーズ ...]           フレーズを追加（省略すると空行まで1行ずつ入力）
  edit <N> <フレーズ>                     フレーズを変更（候補・選択情報・省略しない設定はリセット）
  del <N>                      フレーズを削除
  list                         フレーズと選択中のポケモンを一覧表示
  show <N>                     フレーズの候補を詳しく表示
  conv <対象> | conv all       変換（グループはメンバーを歌詞の順に。ロック中は飛ばす）
  sel <N> <組合わせ> <枠> <候補>          候補を選択情報の末尾に追加
  swap <N> <位置> <組合わせ> <枠> <候補>  選択情報の<位置>を候補と入れ替え
  manual <N> <ポケモン> [位置]            手入力（名前または読み。位置を省略すると末尾に追加）
  unsel <N> <位置> | unsel <N> all        選択情報から削除／全消去
  merge <N> <M> ...            連続したフレーズを合体
  split <N> <位置>             先頭から<位置>文字目の後ろで2つに分割
  fix <N> <位置> [<位置> ...]             ー・っ を「省略しない」にする（位置は先頭から何文字目か）
  unfix <N> <位置> [...] | unfix <N> all  「省略しない」を解除
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

    def cmd_edit(self, args: list[str]) -> None:
        if len(args) != 2:
            raise ValueError("edit <N> <フレーズ> の形で指定してください")
        phrase = self._phrase(args[0])
        before = phrase.text
        self.song.edit_phrase(phrase.id, args[1])
        print(f"「{before}」を「{phrase.text}」に変更しました（候補・選択情報・省略しない設定はリセット）")

    def cmd_fix(self, args: list[str]) -> None:
        phrase, positions = self._phrase_and_positions(args, "fix")
        self.song.set_fixed(phrase.id, positions, True)
        print(f"  {_fixable_line(phrase)}")
        print("  反映するには変換し直してください")

    def cmd_unfix(self, args: list[str]) -> None:
        if len(args) == 2 and args[1] == "all":
            phrase = self._phrase(args[0])
            positions = sorted(phrase.fixed_positions)
        else:
            phrase, positions = self._phrase_and_positions(args, "unfix")
        self.song.set_fixed(phrase.id, positions, False)
        print(f"  {_fixable_line(phrase)}")
        print("  反映するには変換し直してください")

    def _phrase_and_positions(self, args: list[str], command: str) -> tuple[Phrase, list[int]]:
        if len(args) < 2 or not all(a.isdigit() for a in args[1:]):
            raise ValueError(f"{command} <N> <位置> [<位置> ...] の形で指定してください")
        return self._phrase(args[0]), [int(a) - 1 for a in args[1:]]

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

    # ---- 選択情報 ----

    def cmd_sel(self, args: list[str]) -> None:
        phrase, numbers = self._phrase_and_numbers(args, 3)
        self.song.add_selection(phrase.id, self.song.candidate(phrase.id, *numbers))
        self._print_selection(phrase)

    def cmd_swap(self, args: list[str]) -> None:
        phrase, (position, *numbers) = self._phrase_and_numbers(args, 4)
        self.song.replace_selection(phrase.id, position, self.song.candidate(phrase.id, *numbers))
        self._print_selection(phrase)

    def cmd_manual(self, args: list[str]) -> None:
        if len(args) not in (2, 3) or (len(args) == 3 and not args[2].isdigit()):
            raise ValueError("manual <N> <ポケモン> [位置] の形で指定してください")
        phrase = self._phrase(args[0])
        pokemon = self.index.find(args[1])
        if len(args) == 3:
            self.song.replace_selection(phrase.id, int(args[2]) - 1, pokemon)
        else:
            self.song.add_selection(phrase.id, pokemon)
        self._print_selection(phrase)

    def cmd_unsel(self, args: list[str]) -> None:
        if len(args) != 2 or not (args[1] == "all" or args[1].isdigit()):
            raise ValueError("unsel <N> <位置> または unsel <N> all の形で指定してください")
        phrase = self._phrase(args[0])
        if args[1] == "all":
            self.song.clear_selection(phrase.id)
        else:
            self.song.remove_selection(phrase.id, int(args[1]) - 1)
        self._print_selection(phrase)

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
        return f"[{self._number(phrase)}] ({' '.join(tags)}) {_marked_text(phrase)} → {_summary(phrase)}"

    def _print_detail(self, phrase: Phrase) -> None:
        print(self._headline(phrase))
        print(f"  {_selection_line(phrase)}")
        fixable = _fixable_line(phrase)
        if fixable:
            print(f"  {fixable}")
        if not phrase.combinations:
            print("  （候補なし。conv で変換してください）")
        for ci, combination in enumerate(phrase.combinations):
            _print_combination(ci, combination)

    def _print_selection(self, phrase: Phrase) -> None:
        print(self._headline(phrase))
        print(f"  {_selection_line(phrase)}")


def _single(args: list[str]) -> str:
    if len(args) != 1:
        raise ValueError("対象を1つ指定してください")
    return args[0]


def _group_id(target: str) -> int:
    if not (target.startswith("g") and target[1:].isdigit()):
        raise ValueError("グループは g1 のように指定してください")
    return int(target[1:])


def _summary(phrase: Phrase) -> str:
    if phrase.selection:
        return " / ".join(phrase.selected_names())
    return "（未選択・候補あり）" if phrase.combinations else "（未変換）"


def _marked_text(phrase: Phrase) -> str:
    """「省略しない」にした ー・っ を [ ] で囲んだフレーズ。"""
    return "".join(f"[{ch}]" if i in phrase.fixed_positions else ch for i, ch in enumerate(phrase.text))


def _fixable_line(phrase: Phrase) -> str:
    """ー・っ の位置と「省略しない」設定の一覧。ー・っ が無ければ空文字。"""
    positions = [i for i, ch in enumerate(phrase.text) if is_fixable(ch)]
    if not positions:
        return ""
    line = "省略できる文字: " + " ".join(f"{i + 1}:{phrase.text[i]}" for i in positions)
    if phrase.fixed_positions:
        line += "（省略しない: " + " ".join(str(i + 1) for i in sorted(phrase.fixed_positions)) + "）"
    return line


def _selection_line(phrase: Phrase) -> str:
    if not phrase.selection:
        return "選択: （なし）"
    return "選択: " + "  ".join(f"{i}.{name}" for i, name in enumerate(phrase.selected_names(), 1))


def _print_combination(ci: int, combination: Combination) -> None:
    print(f"  組合わせ{ci + 1}: {combination.pattern}  一致度 {combination.similarity:.0%}")
    for si, slot in enumerate(combination.slots):
        options = [f"{ki + 1}.{c.pokemon.name}({c.similarity:.0%})" for ki, c in enumerate(slot.candidates)]
        print(f"     枠{si + 1} {slot.text}: {'  '.join(options)}")
