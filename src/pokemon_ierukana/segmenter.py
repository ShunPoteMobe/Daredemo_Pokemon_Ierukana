"""フレーズを区切ってポケモンを割り当て、組合わせ候補と個別ポケモン候補を作る。"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from .kana import Mora, to_phrase_morae
from .repository import Pokemon
from .scoring import Scorer

MAX_COMBINATIONS = 2
MAX_CANDIDATES_PER_SLOT = 3
# 重複除外で順位が入れ替わることがあるため、上位から多めに区切り方を集めてから選ぶ
_SEGMENTATION_POOL_SIZE = 10

# 序列（第1〜第3候補）ごとに、使用済みのポケモン id を持つ
UsedByRank = list[set[int]]


def empty_used() -> UsedByRank:
    return [set() for _ in range(MAX_CANDIDATES_PER_SLOT)]


@dataclass
class Candidate:
    pokemon: Pokemon
    score: int
    similarity: float  # 一致度（0〜1）


@dataclass
class Slot:
    """区切った1区間。candidates[0] が第1候補。同じ枠の候補は必ず別のポケモン。"""

    start: int
    end: int
    text: str
    candidates: list[Candidate]

    @property
    def length(self) -> int:
        return self.end - self.start


@dataclass
class Combination:
    """1つの区切り方。score は各枠の第1候補の点数の合計、similarity はその一致度（0〜1）。"""

    slots: list[Slot]
    score: int
    similarity: float

    @property
    def pattern(self) -> str:
        return " + ".join(f"{slot.length}音" for slot in self.slots)


@dataclass
class _Segmentation:
    score: int  # 枠ごとの減点を引いた点数
    boundaries: tuple[int, ...] = field(default=())  # 各区間の終端位置

    def sort_key(self) -> tuple[int, int]:
        # 同点なら匹数が少ない方を上にする
        return (self.score, -len(self.boundaries))


class Converter:
    def __init__(self, pokemon: Sequence[Pokemon], scorer: Scorer | None = None):
        self.scorer = scorer or Scorer()
        self._by_length: dict[int, list[Pokemon]] = defaultdict(list)
        for p in pokemon:
            self._by_length[len(p.morae)].append(p)

    def convert(
        self, phrase: str, used: UsedByRank | None = None, fixed_positions: Iterable[int] = ()
    ) -> list[Combination]:
        """フレーズを変換して組合わせ候補を一致度の高い順に返す。

        used を渡すと重複禁止モードとして扱い、各序列で使用済みのポケモンを除外する。
        選んだ候補のポケモンは used に追加される。変換できない場合は空リスト。
        fixed_positions（0始まりの文字の位置）の ー・っ は省略しない。
        """
        morae = to_phrase_morae(phrase, fixed_positions)
        ranked = self._rank_all_segments(morae)
        excluded = used if used is not None else empty_used()

        pool = self._top_segmentations(len(morae), ranked, excluded[0])
        combinations: list[Combination] = []
        while pool and len(combinations) < MAX_COMBINATIONS:
            # 既に選んだ組合わせで使ったポケモンを除外して評価し直し、最も良いものを採用する
            evaluated = []
            for seg in pool:
                combination = self._assign(morae, seg, ranked, excluded if used is not None else None)
                if combination is not None:
                    evaluated.append((seg, combination))
            if not evaluated:
                break
            seg, best = max(evaluated, key=lambda item: self.rank_key(item[1]))
            combinations.append(best)
            pool.remove(seg)
            if used is not None:
                for slot in best.slots:
                    for rank, candidate in enumerate(slot.candidates):
                        used[rank].add(candidate.pokemon.id)
        return combinations

    def score_sequence(
        self, phrase: str, sequence: Sequence[Pokemon], fixed_positions: Iterable[int] = ()
    ) -> Combination | None:
        """指定したポケモンの並びでフレーズを区切ったときの、最も良い区切り方を返す。対応付けられなければ None。

        正解例の評価や、手入力したポケモンがどれだけ近いかを見るために使う。区切りのルールは convert と同じ。
        """
        morae = to_phrase_morae(phrase, fixed_positions)
        n, k = len(morae), len(sequence)
        tail_allowed = n > 0 and not morae[-1].is_extendable_tail
        # best[i][j]: フレーズの i 音目までを、並びの j 匹目までで区切ったときの (点数, 区間の終端位置)
        best: list[list[tuple[int, tuple[int, ...]] | None]] = [[None] * (k + 1) for _ in range(n + 1)]
        best[0][0] = (0, ())
        for start in range(n):
            if start > 0 and morae[start].attaches_to_previous:
                continue
            for j in range(k):
                current = best[start][j]
                if current is None:
                    continue
                for end in range(start + 1, n + 1):
                    allow_extra_tail = tail_allowed and end == n
                    score = self.scorer.align_score(morae[start:end], sequence[j].morae, allow_extra_tail)
                    if score is None:
                        continue
                    candidate = (current[0] + score, current[1] + (end,))
                    if best[end][j + 1] is None or candidate[0] > best[end][j + 1][0]:
                        best[end][j + 1] = candidate
        if best[n][k] is None:
            return None

        total, boundaries = best[n][k]
        slots = []
        start = 0
        for pokemon, end in zip(sequence, boundaries):
            segment = morae[start:end]
            score = self.scorer.align_score(segment, pokemon.morae, tail_allowed and end == n)
            candidate = Candidate(pokemon, score, self.scorer.similarity(score, len(segment)))
            slots.append(Slot(start, end, "".join(m.text for m in segment), [candidate]))
            start = end
        return Combination(slots, total, self.scorer.similarity(total, n))

    def rank_key(self, combination: Combination) -> tuple[int, int]:
        """組合わせ候補の順位付けの値（大きいほど上）。点数の合計から枠ごとの減点を引き、同点なら匹数が少ない方を上にする。"""
        penalty = sum(self.scorer.slot_penalty(slot.candidates[0].score, slot.length) for slot in combination.slots)
        return (combination.score - penalty, -len(combination.slots))

    def _rank_all_segments(self, morae: list[Mora]) -> dict[tuple[int, int], list[Candidate]]:
        """全区間について、対応付け可能なポケモンを一致度の高い順に並べる。"""
        n = len(morae)
        # フレーズ末尾が ー・っ・ん のときは、ポケモン側の余分な末尾音を許さない（仕様で合意済み）
        tail_allowed = n > 0 and not morae[-1].is_extendable_tail
        ranked: dict[tuple[int, int], list[Candidate]] = {}
        for start in range(n):
            # ー・っ は直前の音に付く音なので、そこから始まる区切りは作らない
            if start > 0 and morae[start].attaches_to_previous:
                continue
            for end in range(start + 1, n + 1):
                segment = morae[start:end]
                allow_extra_tail = tail_allowed and end == n
                candidates = []
                for pokemon in self._candidates_for(segment, allow_extra_tail):
                    score = self.scorer.align_score(segment, pokemon.morae, allow_extra_tail)
                    if score is not None:
                        candidates.append(Candidate(pokemon, score, self.scorer.similarity(score, len(segment))))
                if candidates:
                    candidates.sort(key=lambda c: (-c.score, c.pokemon.id))
                    ranked[(start, end)] = candidates
        return ranked

    def _candidates_for(self, segment: list[Mora], allow_extra_tail: bool) -> list[Pokemon]:
        """音数の条件で対応付けの可能性があるポケモンだけに絞り込む。"""
        optional_count = sum(1 for mora in segment if mora.is_optional_in_phrase)
        lengths = range(len(segment) - optional_count, len(segment) + (2 if allow_extra_tail else 1))
        return [p for length in lengths for p in self._by_length.get(length, [])]

    def _top_segmentations(
        self, n: int, ranked: dict[tuple[int, int], list[Candidate]], excluded_first: set[int]
    ) -> list[_Segmentation]:
        """各区間の第1候補の点数の合計（枠ごとの減点を引く）が高い区切り方を、上位から集める（k-best DP）。"""
        best_score: dict[tuple[int, int], int] = {}
        for key, candidates in ranked.items():
            first = next((c for c in candidates if c.pokemon.id not in excluded_first), None)
            if first is not None:
                start, end = key
                best_score[key] = first.score - self.scorer.slot_penalty(first.score, end - start)

        # prefix[i]: 位置 i までを区切る上位の区切り方
        prefix: list[list[_Segmentation]] = [[] for _ in range(n + 1)]
        prefix[0] = [_Segmentation(0)]
        for end in range(1, n + 1):
            options = []
            for start in range(end):
                score = best_score.get((start, end))
                if score is None:
                    continue
                for seg in prefix[start]:
                    options.append(_Segmentation(seg.score + score, seg.boundaries + (end,)))
            options.sort(key=_Segmentation.sort_key, reverse=True)
            prefix[end] = options[:_SEGMENTATION_POOL_SIZE]
        return prefix[n] if n > 0 else []

    def _assign(
        self,
        morae: list[Mora],
        seg: _Segmentation,
        ranked: dict[tuple[int, int], list[Candidate]],
        used: UsedByRank | None,
    ) -> Combination | None:
        """区切り方の各枠に個別ポケモン候補を割り当てる。第1候補が決まらない枠があれば None。"""
        local_used = [set(s) for s in used] if used is not None else None
        slots = []
        start = 0
        for end in seg.boundaries:
            picks: list[Candidate] = []
            picked_ids: set[int] = set()
            for rank in range(MAX_CANDIDATES_PER_SLOT):
                blocked = local_used[rank] if local_used is not None else set()
                pick = next(
                    (c for c in ranked[(start, end)] if c.pokemon.id not in picked_ids and c.pokemon.id not in blocked),
                    None,
                )
                if pick is None:
                    if rank == 0:
                        return None
                    # 序列がずれないよう、下位の候補は詰めずに打ち切る
                    break
                picks.append(pick)
                picked_ids.add(pick.pokemon.id)
                if local_used is not None:
                    local_used[rank].add(pick.pokemon.id)
            slots.append(Slot(start, end, "".join(m.text for m in morae[start:end]), picks))
            start = end
        score = sum(slot.candidates[0].score for slot in slots)
        return Combination(slots, score, self.scorer.similarity(score, len(morae)))
