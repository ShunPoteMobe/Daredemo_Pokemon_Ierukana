"""フレーズを区切ってポケモンを割り当て、組合わせ候補と個別ポケモン候補を作る。"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field

from .kana import Mora, to_morae
from .repository import Pokemon
from .scoring import align_score

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


@dataclass
class Slot:
    """区切った1区間。candidates[0] が第1候補。manual があれば、それが選択中の結果になる。"""

    start: int
    end: int
    text: str
    candidates: list[Candidate]
    selected: int = 0
    manual: Pokemon | None = None

    @property
    def length(self) -> int:
        return self.end - self.start

    @property
    def result(self) -> Pokemon:
        """この枠で選択中のポケモン。"""
        return self.manual if self.manual is not None else self.candidates[self.selected].pokemon


@dataclass
class Combination:
    """1つの区切り方。score は各枠の第1候補の一致度の合計。"""

    slots: list[Slot]
    score: int

    @property
    def pattern(self) -> str:
        return " + ".join(f"{slot.length}音" for slot in self.slots)


@dataclass
class _Segmentation:
    score: int
    boundaries: tuple[int, ...] = field(default=())  # 各区間の終端位置

    def sort_key(self) -> tuple[int, int]:
        # 同点なら匹数が少ない方を上にする
        return (self.score, -len(self.boundaries))


class Converter:
    def __init__(self, pokemon: Sequence[Pokemon]):
        self._by_length: dict[int, list[Pokemon]] = defaultdict(list)
        for p in pokemon:
            self._by_length[len(p.morae)].append(p)

    def convert(self, phrase: str, used: UsedByRank | None = None) -> list[Combination]:
        """フレーズを変換して組合わせ候補を一致度の高い順に返す。

        used を渡すと重複禁止モードとして扱い、各序列で使用済みのポケモンを除外する。
        選んだ候補のポケモンは used に追加される。変換できない場合は空リスト。
        """
        morae = to_morae(phrase)
        ranked = self._rank_all_segments(morae)
        excluded = used if used is not None else empty_used()

        pool = self._top_segmentations(len(morae), ranked, excluded[0])
        combinations: list[Combination] = []
        while pool and len(combinations) < MAX_COMBINATIONS:
            # 既に選んだ組合わせで使ったポケモンを除外して評価し直し、最も良いものを採用する
            evaluated = []
            for seg in pool:
                combination = _assign(morae, seg, ranked, excluded if used is not None else None)
                if combination is not None:
                    evaluated.append((seg, combination))
            if not evaluated:
                break
            seg, best = max(evaluated, key=lambda item: (item[1].score, -len(item[1].slots)))
            combinations.append(best)
            pool.remove(seg)
            if used is not None:
                for slot in best.slots:
                    for rank, candidate in enumerate(slot.candidates):
                        used[rank].add(candidate.pokemon.id)
        return combinations

    def _rank_all_segments(self, morae: list[Mora]) -> dict[tuple[int, int], list[Candidate]]:
        """全区間について、対応付け可能なポケモンを一致度の高い順に並べる。"""
        n = len(morae)
        # フレーズ末尾が ー・っ・ん のときは、ポケモン側の余分な末尾音を許さない（仕様で合意済み）
        tail_allowed = n > 0 and not morae[-1].is_extendable_tail
        ranked: dict[tuple[int, int], list[Candidate]] = {}
        for start in range(n):
            # ー・っ は直前の音に付く音なので、そこから始まる区切りは作らない
            if start > 0 and morae[start].is_optional_in_phrase:
                continue
            for end in range(start + 1, n + 1):
                segment = morae[start:end]
                allow_extra_tail = tail_allowed and end == n
                candidates = []
                for pokemon in self._candidates_for(segment, allow_extra_tail):
                    score = align_score(segment, pokemon.morae, allow_extra_tail)
                    if score is not None:
                        candidates.append(Candidate(pokemon, score))
                if candidates:
                    candidates.sort(key=lambda c: (-c.score, c.pokemon.id))
                    ranked[(start, end)] = candidates
        return ranked

    def _candidates_for(self, segment: list[Mora], allow_extra_tail: bool) -> list[Pokemon]:
        """音数の条件で対応付けの可能性があるポケモンだけに絞り込む。"""
        optional_count = sum(1 for mora in segment if mora.is_optional_in_phrase)
        lengths = range(len(segment) - optional_count, len(segment) + (2 if allow_extra_tail else 1))
        return [p for length in lengths for p in self._by_length.get(length, [])]

    @staticmethod
    def _top_segmentations(
        n: int, ranked: dict[tuple[int, int], list[Candidate]], excluded_first: set[int]
    ) -> list[_Segmentation]:
        """各区間の第1候補の一致度の合計が高い区切り方を、上位から集める（k-best DP）。"""
        best_score: dict[tuple[int, int], int] = {}
        for key, candidates in ranked.items():
            first = next((c for c in candidates if c.pokemon.id not in excluded_first), None)
            if first is not None:
                best_score[key] = first.score

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
    return Combination(slots, sum(slot.candidates[0].score for slot in slots))
