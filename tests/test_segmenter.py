import pytest

from pokemon_ierukana.kana import to_reading
from pokemon_ierukana.repository import load_pokemon, make_pokemon
from pokemon_ierukana.scoring import Scorer, ScoringParams
from pokemon_ierukana.segmenter import Converter, empty_used


def fake_converter(*names: str, params: ScoringParams | None = None) -> Converter:
    pokemon = [make_pokemon(i, name, to_reading(name)) for i, name in enumerate(names, 1)]
    return Converter(pokemon, Scorer(params or ScoringParams()))


def candidate_names(combination, slot_index=0):
    return [c.pokemon.name for c in combination.slots[slot_index].candidates]


@pytest.fixture(scope="module")
def real_converter() -> Converter:
    return Converter(load_pokemon())


def test_single_pokemon_conversion():
    combinations = fake_converter("コマタナ", "ルカリオ").convert("あらたな")
    assert combinations[0].pattern == "4音"
    assert candidate_names(combinations[0])[0] == "コマタナ"


def test_multiple_pokemon_and_extra_tail():
    combinations = fake_converter("スコルピ", "クマシュン").convert("たどりつくばしょ")
    assert [s.text for s in combinations[0].slots] == ["たどりつ", "くばしょ"]
    assert candidate_names(combinations[0], 0)[0] == "スコルピ"
    assert candidate_names(combinations[0], 1) == ["クマシュン"]


def test_extra_tail_not_applied_when_phrase_ends_with_special_mora():
    # 5音の架空ポケモン。4音のフレーズとは末尾の余分な音を許したときだけ対応する
    assert fake_converter("クマシュンッ").convert("くばしょと") != []
    assert fake_converter("クマシュンッ").convert("くばしょん") == []


def test_extra_tail_only_for_last_slot():
    # クマシュン が先頭の枠になる区切りでは余分な音を許さない
    combinations = fake_converter("クマシュン", "ルカリオ").convert("くばしょひかりを")
    assert all(c.slots[0].text != "くばしょ" for c in combinations)


def test_no_segment_starts_with_long_vowel_or_sokuon():
    combinations = fake_converter("ダレモ", "ーガ", "ッテ", "イツダ", "モーガ").convert("だれもーが")
    for combination in combinations:
        assert all(slot.text[0] not in "ーっ" for slot in combination.slots)


def test_at_most_two_combinations_and_three_candidates(real_converter):
    combinations = real_converter.convert("たどりつくばしょ")
    assert len(combinations) == 2
    assert all(len(slot.candidates) <= 3 for c in combinations for slot in c.slots)
    assert real_converter.rank_key(combinations[0]) >= real_converter.rank_key(combinations[1])


def test_tie_prefers_fewer_pokemon():
    # 減点なしで「あらたな」1匹と「あら」+「たな」2匹が同点になる組み合わせ
    params = ScoringParams(per_pokemon_penalty=0)
    combinations = fake_converter("アラタナ", "アラ", "タナ", params=params).convert("あらたな")
    assert combinations[0].pattern == "4音"
    assert combinations[0].score == combinations[1].score


def test_penalty_prefers_long_pokemon_over_slightly_better_split():
    # 2匹に分けると1音だけ点数が上がるが、1匹ごとの減点でその差を打ち消す
    phrase = "あらたな"
    split = fake_converter("アラ", "タナ", params=ScoringParams(per_pokemon_penalty=0))
    single = fake_converter("アラタマ", params=ScoringParams(per_pokemon_penalty=0))
    gap = split.convert(phrase)[0].score - single.convert(phrase)[0].score
    assert gap > 0

    penalty = gap / 100 + 0.5
    converter = fake_converter("アラタマ", "アラ", "タナ", params=ScoringParams(per_pokemon_penalty=penalty))
    assert converter.convert(phrase)[0].pattern == "4音"


def test_candidates_in_a_slot_are_distinct_even_if_duplicates_allowed():
    for combination in fake_converter("コマタナ", "アメタマ", "ギラティナ", "カラカラ").convert("あらたな"):
        for slot in combination.slots:
            ids = [c.pokemon.id for c in slot.candidates]
            assert len(ids) == len(set(ids))


def test_similarity_is_shown_as_ratio():
    combination = fake_converter("アラタナ").convert("あらたな")[0]
    assert combination.similarity == 1.0
    assert combination.slots[0].candidates[0].similarity == 1.0


def test_used_excludes_same_rank_only():
    converter = fake_converter("コマタナ", "アメタマ", "ギラティナ")
    used = empty_used()
    first = converter.convert("あらたな", used)
    second = converter.convert("あらたな", used)
    assert candidate_names(first[0])[0] != candidate_names(second[0])[0]
    # 第1候補で使われたポケモンも、第2候補以降には出てよい
    assert candidate_names(first[0])[0] in candidate_names(second[0])


def test_used_is_shared_between_slots_and_combinations():
    converter = fake_converter("アラ", "タナ", "アマ", "カナ", "アラタナ", "サカタナ")
    used = empty_used()
    combinations = converter.convert("あらたな", used)
    firsts = [c.pokemon.id for comb in combinations for slot in comb.slots for c in slot.candidates[:1]]
    assert len(firsts) == len(set(firsts))


def test_pokemon_side_is_not_shortened(real_converter):
    names = {c.pokemon.name for comb in real_converter.convert("でるぞ") for slot in comb.slots for c in slot.candidates}
    assert "ケムッソ" not in names


def test_weak_slot_makes_split_rank_lower():
    # 「あら」+「たな」に分けると、あら→パモ は弱い（約38%）が、たな→タナー（末尾の余分な ー）は完全一致で、
    # 合計点では1匹の「カバカモ」を上回る。弱い枠の減点があると1匹の方が上になる
    names = ("パモ", "タナー", "カバカモ")
    without = fake_converter(*names, params=ScoringParams(weak_slot_penalty=0)).convert("あらたな")
    with_weak = fake_converter(*names, params=ScoringParams()).convert("あらたな")
    assert without[0].pattern == "2音 + 2音"
    assert with_weak[0].pattern == "4音"

def test_fixed_long_vowel_is_not_dropped():
    converter = fake_converter("サボネア", "プロトーガ")
    names = lambda combos: {c.pokemon.name for comb in combos for slot in comb.slots for c in slot.candidates}
    assert names(converter.convert("だれもーが")) == {"サボネア", "プロトーガ"}
    # 4文字目の ー を省略しないと、4音の サボネア には対応しない
    assert names(converter.convert("だれもーが", fixed_positions={3})) == {"プロトーガ"}