"""かなの正規化とモーラ（音）単位の情報を扱う。"""

from __future__ import annotations

from dataclasses import dataclass

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

# 濁音・半濁音は清音と同じ行として扱う（仕様で合意済み）。ゔ は音が近い は行 に含める
_ROW_GROUPS = {
    "a": "あいうえおぁぃぅぇぉ",
    "k": "かきくけこがぎぐげご",
    "s": "さしすせそざじずぜぞ",
    "t": "たちつてとだぢづでど",
    "n": "なにぬねの",
    "h": "はひふへほばびぶべぼぱぴぷぺぽゔ",
    "m": "まみむめも",
    "y": "やゆよゃゅょ",
    "r": "らりるれろ",
    "w": "わをゐゑゎ",
}
_ROW_OF_KANA = {kana: row for row, chars in _ROW_GROUPS.items() for kana in chars}

_HIRAGANA_CHARS = set(_VOWEL_OF_KANA) | set(_ROW_OF_KANA) | {LONG_VOWEL, SOKUON, HATSUON}


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
    """1音分の情報。vowel/row は該当しない音（っ・ん 等）では None。"""

    text: str
    vowel: str | None
    row: str | None

    @property
    def is_optional_in_phrase(self) -> bool:
        """フレーズ側で「あってもなくてもよい」音か。ん は1音として必ず数える（仕様で合意済み）。"""
        return self.text in (LONG_VOWEL, SOKUON)

    @property
    def is_extendable_tail(self) -> bool:
        """フレーズ末尾で余分な1音として許される音か。"""
        return self.text in (LONG_VOWEL, SOKUON, HATSUON)


def to_morae(reading: str) -> list[Mora]:
    """読みを Mora のリストに変換する。ー の母音は直前の音の母音とする。"""
    result: list[Mora] = []
    for text in split_morae(reading):
        if text == LONG_VOWEL:
            vowel = result[-1].vowel if result else None
            row = None
        elif text in (SOKUON, HATSUON):
            vowel = None
            row = None
        else:
            # 拗音は最後の小書き文字で母音、最初の文字で行が決まる（しょ → o, さ行）
            vowel = _VOWEL_OF_KANA.get(text[-1])
            row = _ROW_OF_KANA.get(text[0])
        result.append(Mora(text, vowel, row))
    return result
