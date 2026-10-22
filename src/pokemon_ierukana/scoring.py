"""フレーズの区間とポケモン1匹の一致度を計算する。

一致度は「完全一致 > 母音一致 > 同じ行 > 異なる母音の優先度1〜3」の件数を辞書式に比較する。
DP で足し合わせやすいよう、各件数を桁に詰めた1つの整数で表す（大きいほど近い）。
"""

from __future__ import annotations

from collections.abc import Sequence

from .kana import Mora

SCORE_LABELS = ("完全一致", "母音一致", "同じ行", "母音優先1", "母音優先2", "母音優先3")

# 各件数は1フレーズの音数を超えないので、この基数なら桁あふれしない
_BASE = 1000
_WEIGHTS = tuple(_BASE ** (len(SCORE_LABELS) - 1 - i) for i in range(len(SCORE_LABELS)))

# フレーズ側の母音 → ポケモン側の異なる母音の優先順（先頭ほど近い）。4番目は加点なし
VOWEL_PREFERENCE = {
    "a": ("e", "i", "u", "o"),
    "i": ("e", "a", "u", "o"),
    "u": ("e", "o", "a", "i"),
    "e": ("a", "i", "o", "u"),
    "o": ("a", "u", "e", "i"),
}

_IMPOSSIBLE = -1


def mora_score(phrase_mora: Mora, pokemon_mora: Mora) -> int:
    """1音同士の一致度。"""
    score = 0
    if phrase_mora.text == pokemon_mora.text:
        score += _WEIGHTS[0]
    if phrase_mora.vowel is not None and pokemon_mora.vowel is not None:
        if phrase_mora.vowel == pokemon_mora.vowel:
            score += _WEIGHTS[1]
        else:
            rank = VOWEL_PREFERENCE[phrase_mora.vowel].index(pokemon_mora.vowel)
            if rank < 3:
                score += _WEIGHTS[3 + rank]
    if phrase_mora.row is not None and phrase_mora.row == pokemon_mora.row:
        score += _WEIGHTS[2]
    return score


def decode_score(score: int) -> tuple[int, ...]:
    """整数の一致度を SCORE_LABELS 順の件数に戻す。"""
    return tuple((score // w) % _BASE for w in _WEIGHTS)


def align_score(segment: Sequence[Mora], pokemon_morae: Sequence[Mora], allow_extra_tail: bool = False) -> int | None:
    """区間とポケモンの読みを対応付けたときの最大の一致度。対応付けられなければ None。

    - フレーズ側の ー・っ は省略できる（ポケモン側の音とは対応させない）。
    - ポケモン側の音は省略しない。
    - allow_extra_tail が True の場合のみ、ポケモンの最後の ー・ッ・ン を余分な1音として許す。
    """
    best = _align_exact(segment, pokemon_morae)
    if allow_extra_tail and len(pokemon_morae) >= 2 and pokemon_morae[-1].is_extendable_tail:
        trimmed = _align_exact(segment, pokemon_morae[:-1])
        if trimmed is not None and (best is None or trimmed > best):
            best = trimmed
    return best


def _align_exact(segment: Sequence[Mora], pokemon_morae: Sequence[Mora]) -> int | None:
    m, n = len(segment), len(pokemon_morae)
    optional_count = sum(1 for mora in segment if mora.is_optional_in_phrase)
    if not (m - optional_count <= n <= m):
        return None
    if m == n:
        return sum(mora_score(p, q) for p, q in zip(segment, pokemon_morae))

    # dp[j]: フレーズ側を i 音目まで見て、ポケモン側の j 音目まで対応させたときの最大一致度
    dp = [0] + [_IMPOSSIBLE] * n
    for phrase_mora in segment:
        next_dp = dp[:] if phrase_mora.is_optional_in_phrase else [_IMPOSSIBLE] * (n + 1)
        for j in range(n):
            if dp[j] != _IMPOSSIBLE:
                next_dp[j + 1] = max(next_dp[j + 1], dp[j] + mora_score(phrase_mora, pokemon_morae[j]))
        dp = next_dp
    return None if dp[n] == _IMPOSSIBLE else dp[n]
