"""フレーズの区間とポケモン1匹の一致度を計算する。

1音の点数 = 母音の重み × 母音の近さ ＋ 子音の重み × 子音の近さ。区間の点数は1音ごとの点数の合計。
母音が合うことを最も重視する（母音が合えば歌ったときに近く聞こえるため）。
DP で扱いやすいよう、点数は SCALE 倍した整数で表す。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from .kana import LONG_VOWEL, Mora

SCALE = 100

# フレーズ側の母音 → ポケモン側の異なる母音の優先順（先頭ほど近い）
VOWEL_PREFERENCE = {
    "a": ("e", "i", "u", "o"),
    "i": ("e", "a", "u", "o"),
    "u": ("e", "o", "a", "i"),
    "e": ("a", "i", "o", "u"),
    "o": ("a", "u", "e", "i"),
}

_VOICING_PAIRS = (("k", "g"), ("s", "z"), ("t", "d"), ("h", "b"), ("h", "p"), ("b", "p"))
# 調音の仕方が似ている子音（唇を使う音、舌先を使う音、半母音と母音だけの音）
_SIMILAR_CONSONANTS = (
    (("m", "b"), 0.4),
    (("m", "p"), 0.4),
    (("n", "r"), 0.4),
    (("n", "d"), 0.4),
    (("r", "d"), 0.4),
    (("y", ""), 0.4),
    (("w", ""), 0.4),
    (("n", "m"), 0.3),
)

_IMPOSSIBLE = -1


@dataclass(frozen=True)
class ScoringParams:
    """一致度の調整できる値。"""

    vowel_weight: float = 3.0
    consonant_weight: float = 1.0
    # 組合わせ候補を比べるとき、ポケモン1匹ごとに引く点数（弱い短いポケモンで細かく区切るのを防ぐ）
    per_pokemon_penalty: float = 1.0
    # 枠の一致度がこの値未満なら、足りない分に比例して追加で引く（弱い枠が1つあると全体が台無しに感じるため）
    weak_slot_threshold: float = 0.65
    weak_slot_penalty: float = 1.0
    # 片方が「ー」、もう片方が子音のある音のときに引く点数。
    # 「ー」は前の音を伸ばす1つの音で、子音のある音は別々に発音する音なので、母音が同じでもリズムが少し違う
    long_vowel_mismatch_penalty: float = 0.5
    # フレーズ側で省略した ー・っ 1音分の点数（省略は自然なので、0点にして不利にしない）
    dropped_mora_points: float = 2.0
    # 母音が違うときの近さ（優先表の1〜3番目）。4番目は 0
    vowel_preference_similarity: tuple[float, ...] = (0.4, 0.3, 0.15)
    # 清濁だけが違う子音の近さ
    voicing_similarity: float = 0.6
    similar_consonants: tuple[tuple[tuple[str, str], float], ...] = _SIMILAR_CONSONANTS

    @property
    def max_mora_points(self) -> float:
        return self.vowel_weight + self.consonant_weight


@dataclass
class Scorer:
    params: ScoringParams = field(default_factory=ScoringParams)

    def __post_init__(self) -> None:
        self._consonant_similarity: dict[frozenset[str], float] = {
            frozenset(pair): self.params.voicing_similarity for pair in _VOICING_PAIRS
        }
        for pair, similarity in self.params.similar_consonants:
            self._consonant_similarity[frozenset(pair)] = similarity
        self._cache: dict[tuple[Mora, Mora], int] = {}

    def slot_penalty(self, score: int, length: int) -> int:
        """組合わせ候補の順位付けで、1つの枠（第1候補の点数 score、音数 length）から引く点数。表示する一致度には含めない。"""
        params = self.params
        penalty = params.per_pokemon_penalty
        shortfall = params.weak_slot_threshold - self.similarity(score, length)
        if shortfall > 0:
            penalty += params.weak_slot_penalty * shortfall * length * params.max_mora_points
        return round(penalty * SCALE)

    def similarity(self, score: int, length: int) -> float:
        """点数を、満点に対する割合（0〜1）に直す。"""
        return score / (length * self.params.max_mora_points * SCALE) if length else 0.0

    def mora_score(self, phrase_mora: Mora, pokemon_mora: Mora) -> int:
        """1音同士の点数。"""
        key = (phrase_mora, pokemon_mora)
        if key not in self._cache:
            self._cache[key] = round(self._mora_points(phrase_mora, pokemon_mora) * SCALE)
        return self._cache[key]

    def _mora_points(self, p: Mora, q: Mora) -> float:
        params = self.params
        if p.vowel is None or q.vowel is None:
            # っ・ん は同じものどうしのときだけ満点
            return params.max_mora_points if p.consonant == q.consonant and p.vowel == q.vowel else 0.0
        if p.vowel == q.vowel:
            vowel = 1.0
        else:
            rank = VOWEL_PREFERENCE[p.vowel].index(q.vowel)
            preference = params.vowel_preference_similarity
            vowel = preference[rank] if rank < len(preference) else 0.0
        if p.consonant == q.consonant:
            consonant = 1.0
        else:
            consonant = self._consonant_similarity.get(frozenset((p.consonant, q.consonant)), 0.0)
        points = params.vowel_weight * vowel + params.consonant_weight * consonant
        if (p.text == LONG_VOWEL) != (q.text == LONG_VOWEL):
            other = q if p.text == LONG_VOWEL else p
            if other.consonant != "":
                points = max(0.0, points - params.long_vowel_mismatch_penalty)
        return points

    def align_score(self, segment: Sequence[Mora], pokemon_morae: Sequence[Mora], allow_extra_tail: bool = False) -> int | None:
        """区間とポケモンの読みを対応付けたときの最大の点数。対応付けられなければ None。

        - フレーズ側の ー・っ は省略できる（ポケモン側の音とは対応させない）。
        - ポケモン側の音は省略しない。
        - allow_extra_tail が True の場合のみ、ポケモンの最後の ー・ッ・ン を余分な1音として許す。
        """
        best = self._align_exact(segment, pokemon_morae)
        if allow_extra_tail and len(pokemon_morae) >= 2 and pokemon_morae[-1].is_extendable_tail:
            trimmed = self._align_exact(segment, pokemon_morae[:-1])
            if trimmed is not None and (best is None or trimmed > best):
                best = trimmed
        return best

    def _align_exact(self, segment: Sequence[Mora], pokemon_morae: Sequence[Mora]) -> int | None:
        m, n = len(segment), len(pokemon_morae)
        optional_count = sum(1 for mora in segment if mora.is_optional_in_phrase)
        if not (m - optional_count <= n <= m):
            return None
        if m == n:
            return sum(self.mora_score(p, q) for p, q in zip(segment, pokemon_morae))

        dropped = round(self.params.dropped_mora_points * SCALE)
        # dp[j]: フレーズ側をここまで見て、ポケモン側の j 音目まで対応させたときの最大の点数
        dp = [0] + [_IMPOSSIBLE] * n
        for phrase_mora in segment:
            if phrase_mora.is_optional_in_phrase:
                next_dp = [v + dropped if v != _IMPOSSIBLE else _IMPOSSIBLE for v in dp]
            else:
                next_dp = [_IMPOSSIBLE] * (n + 1)
            for j in range(n):
                if dp[j] != _IMPOSSIBLE:
                    next_dp[j + 1] = max(next_dp[j + 1], dp[j] + self.mora_score(phrase_mora, pokemon_morae[j]))
            dp = next_dp
        return None if dp[n] == _IMPOSSIBLE else dp[n]
