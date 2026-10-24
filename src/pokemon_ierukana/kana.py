"""かなの正規化とモーラ（音）単位の情報を扱う。"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace

LONG_VOWEL = "ー"
SOKUON = "っ"
HATSUON = "ん"

# 直前の文字と合わせて1音になる小書き文字
_SMALL_KANA = set("ゃゅょぁぃぅぇぉゎ")
_SMALL_VOWEL_TO_LARGE = dict(zip("ぁぃぅぇぉ", "あいうえお"))

# 表記上の区切り記号（カプ・コケコ、タイプ：ヌル）。音を持たないので取り除く
_IGNORED_SYMBOLS = set("・：:")

_VOWEL_GROUPS = {
    "a": "あかさたなはまやらわがざだばぱぁゃゎ",
    "i": "いきしちにひみりぎじぢびぴぃゐ",
    "u": "うくすつぬふむゆるぐずづぶぷぅゅゔ",
    "e": "えけせてねへめれげぜでべぺぇゑ",
    "o": "おこそとのほもよろをごぞどぼぽぉょ",
}
_VOWEL_OF_KANA = {kana: vowel for vowel, chars in _VOWEL_GROUPS.items() for kana in chars}

# 子音（清濁を区別する）。"" は母音だけの音。ゔ は音が近い ば と同じに扱う
CONSONANT_SOKUON = "Q"
CONSONANT_HATSUON = "N"
_CONSONANT_GROUPS = {
    "": "あいうえおぁぃぅぇぉ",
    "k": "かきくけこ",
    "g": "がぎぐげご",
    "s": "さしすせそ",
    "z": "ざじずぜぞ",
    "t": "たちつてと",
    "d": "だぢづでど",
    "n": "なにぬねの",
    "h": "はひふへほ",
    "b": "ばびぶべぼゔ",
    "p": "ぱぴぷぺぽ",
    "m": "まみむめも",
    "y": "やゆよゃゅょ",
    "r": "らりるれろ",
    "w": "わをゐゑゎ",
}
_CONSONANT_OF_KANA = {kana: consonant for consonant, chars in _CONSONANT_GROUPS.items() for kana in chars}

_HIRAGANA_CHARS = set(_VOWEL_OF_KANA) | set(_CONSONANT_OF_KANA) | {LONG_VOWEL, SOKUON, HATSUON}


def katakana_to_hiragana(text: str) -> str:
    """カタカナをひらがなに変換する。長音符などカタカナ以外の文字はそのまま残す。"""
    result = []
    for ch in text:
        code = ord(ch)
        # ァ(U+30A1)〜ヶ(U+30F6) はひらがなと 0x60 ずれて対応する（ヴ→ゔ も含む）
        if 0x30A1 <= code <= 0x30F6:
            result.append(chr(code - 0x60))
        else:
            result.append(ch)
    return "".join(result)


def to_reading(text: str) -> str:
    """表記を、記号を除いたひらがなの読みに正規化する。"""
    return katakana_to_hiragana("".join(ch for ch in text if ch not in _IGNORED_SYMBOLS))


def is_valid_reading(text: str) -> bool:
    """ひらがなと長音符だけで構成されているかを返す。"""
    return bool(text) and all(ch in _HIRAGANA_CHARS for ch in text) and text[0] not in _SMALL_KANA


def split_morae(reading: str) -> list[str]:
    """読みをモーラ（1音）単位に分割する。拗音は1音、っ・ん・ー もそれぞれ1音。"""
    morae: list[str] = []
    for ch in reading:
        if ch in _SMALL_VOWEL_TO_LARGE and morae and _VOWEL_OF_KANA.get(morae[-1][-1]) == _VOWEL_OF_KANA[ch]:
            # ピィ・ケーシィ のように直前と同じ母音の小書き文字は、伸ばす音として独立した1音にする
            morae.append(_SMALL_VOWEL_TO_LARGE[ch])
        elif ch in _SMALL_KANA and morae:
            morae[-1] += ch
        else:
            morae.append(ch)
    return morae


@dataclass(frozen=True)
class Mora:
    """1音分の情報。

    vowel は っ・ん では None。consonant は清濁を区別した子音で、母音だけの音（ー を含む）は ""、
    っ は CONSONANT_SOKUON、ん は CONSONANT_HATSUON。
    """

    text: str
    vowel: str | None
    consonant: str
    # フレーズ側でユーザーが「省略しない」に設定した ー・っ
    fixed: bool = False

    @property
    def attaches_to_previous(self) -> bool:
        """直前の音に付く音（ー・っ）か。区切りの先頭には置かない。"""
        return self.text in (LONG_VOWEL, SOKUON)

    @property
    def is_optional_in_phrase(self) -> bool:
        """フレーズ側で「あってもなくてもよい」音か。ん は1音として必ず数える（仕様で合意済み）。"""
        return self.attaches_to_previous and not self.fixed

    @property
    def is_extendable_tail(self) -> bool:
        """フレーズ末尾で余分な1音として許される音か。"""
        return self.text in (LONG_VOWEL, SOKUON, HATSUON)


def to_morae(reading: str) -> list[Mora]:
    """読みを Mora のリストに変換する。

    ー は直前の音の母音だけの音とする（くー の ー は「う」と同じ音）。
    """
    result: list[Mora] = []
    for text in split_morae(reading):
        if text == LONG_VOWEL:
            vowel = result[-1].vowel if result else None
            consonant = ""
        elif text == SOKUON:
            vowel, consonant = None, CONSONANT_SOKUON
        elif text == HATSUON:
            vowel, consonant = None, CONSONANT_HATSUON
        else:
            # 拗音は最後の小書き文字で母音、最初の文字で子音が決まる（しょ → o, s）
            vowel = _VOWEL_OF_KANA.get(text[-1])
            consonant = _CONSONANT_OF_KANA[text[0]]
        result.append(Mora(text, vowel, consonant))
    return result


def is_fixable(ch: str) -> bool:
    """「省略しない」に設定できる文字（ー・っ）か。"""
    return ch in (LONG_VOWEL, SOKUON)


def to_phrase_morae(text: str, fixed_positions: Iterable[int] = ()) -> list[Mora]:
    """フレーズを Mora のリストに変換し、fixed_positions（0始まりの文字の位置）の ー・っ を「省略しない」にする。"""
    fixed = set(fixed_positions)
    morae = to_morae(text)
    if not fixed:
        return morae
    result = []
    position = 0
    for mora in morae:
        if mora.attaches_to_previous and position in fixed:
            mora = replace(mora, fixed=True)
        result.append(mora)
        position += len(mora.text)
    return result