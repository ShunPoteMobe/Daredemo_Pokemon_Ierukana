import pytest

from pokemon_ierukana.kana import to_reading
from pokemon_ierukana.repository import load_pokemon, make_pokemon
from pokemon_ierukana.segmenter import Converter, empty_used


def fake_converter(*names: str) -> Converter:
    return Converter([make_pokemon(i, name, to_reading(name)) for i, name in enumerate(names, 1)])


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
    assert combinations[0].score >= combinations[1].score


def test_tie_prefers_fewer_pokemon():
    # 「あらたな」1匹と「あら」+「たな」2匹が同点になる組み合わせ
    combinations = fake_converter("アラタナ", "アラ", "タナ").convert("あらたな")
    assert combinations[0].pattern == "4音"
    assert combinations[0].score == combinations[1].score


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


@pytest.mark.parametrize(
    ("phrase", "expected"),
    [
        ("あらたな", "コマタナ"),
        ("だれもーが", "プロトーガ"),
        ("ひかりを", "ルカリオ"),
        ("きみしだい", "イシズマイ"),
        ("たどりつくばしょ", "クマシュン"),
    ],
)
def test_spec_examples_appear_in_candidates(real_converter, phrase, expected):
    combinations = real_converter.convert(phrase)
    names = {c.pokemon.name for comb in combinations for slot in comb.slots for c in slot.candidates}
    assert expected in names


def test_pokemon_side_is_not_shortened(real_converter):
    names = {c.pokemon.name for comb in real_converter.convert("でるぞ") for slot in comb.slots for c in slot.candidates}
    assert "ケムッソ" not in names
