from pokemon_ierukana.kana import to_morae
from pokemon_ierukana.scoring import SCALE, Scorer, ScoringParams

scorer = Scorer()
FULL = round(ScoringParams().max_mora_points * SCALE)


def score_of(phrase: str, pokemon: str, allow_extra_tail: bool = False):
    return scorer.align_score(to_morae(phrase), to_morae(pokemon), allow_extra_tail)


def single(a: str, b: str) -> int:
    return scorer.mora_score(to_morae(a)[0], to_morae(b)[0])


def test_exact_match_is_full_score():
    assert single("か", "か") == FULL
    assert single("しょ", "しょ") == FULL


def test_vowel_matters_more_than_consonant():
    assert single("か", "さ") > single("か", "き")  # 母音だけ一致 > 子音だけ一致
    assert single("か", "が") > single("か", "さ")  # 清濁違いは子音も近い


def test_consonant_similarity():
    assert single("か", "が") > single("ま", "ば") > single("か", "さ")
    assert single("な", "ら") > single("な", "か")


def test_vowel_preference_for_different_vowels():
    # あ段: え > い > う > お
    assert single("ら", "れ") > single("ら", "り") > single("ら", "る") > single("ら", "ろ")
    # い段: え > あ > う > お
    assert single("り", "れ") > single("り", "ら") > single("り", "る") > single("り", "ろ")


def test_long_vowel_uses_vowel_of_previous_mora():
    # くー の ー は「う」なので、ミュウ の「う」とは一致し、ワンリキー の ー（い）とは一致しない
    phrase = to_morae("くー")
    assert scorer.mora_score(phrase[1], to_morae("みゅう")[1]) == FULL
    assert scorer.mora_score(phrase[1], to_morae("きー")[1]) < FULL // 2


def test_sokuon_and_hatsuon_only_match_themselves():
    assert single("っ", "っ") == FULL
    assert single("ん", "ん") == FULL
    assert single("っ", "ん") == 0
    assert single("ん", "む") == 0


def test_similarity_is_ratio_to_full_score():
    assert scorer.similarity(score_of("ひかりを", "ひかりを"), 4) == 1.0


def test_mora_count_must_match():
    assert score_of("ひかりを", "るかりお") is not None
    assert score_of("ひかりを", "るかり") is None


def test_optional_long_vowel_and_sokuon_in_phrase():
    assert score_of("だれもーが", "ぷろとーが") is not None  # ー を含む5音
    assert score_of("だれもーが", "さぼねあ") is not None  # ー を除いた4音
    assert score_of("いつだって", "こすもっぐ") is not None
    assert score_of("いつだって", "ぜにがめ") is not None
    assert score_of("でゅえるー", "こもるー") is not None
    assert score_of("でゅえる", "こもるー") is None


def test_dropped_mora_gets_fixed_points():
    params = ScoringParams(dropped_mora_points=2.0)
    scorer2 = Scorer(params)
    with_drop = scorer2.align_score(to_morae("かーな"), to_morae("かな"))
    assert with_drop == 2 * FULL + round(2.0 * SCALE)


def test_hatsuon_in_phrase_is_not_optional():
    assert score_of("かんな", "かな") is None


def test_pokemon_side_morae_are_not_skipped():
    assert score_of("でるぞ", "けむっそ") is None


def test_extra_tail_only_when_allowed():
    assert score_of("くばしょ", "くましゅん") is None
    assert score_of("くばしょ", "くましゅん", allow_extra_tail=True) is not None
    # 末尾の ー・ッ・ン 以外は余分な音として許さない
    assert score_of("くばし", "くまのみ", allow_extra_tail=True) is None


def test_long_vowel_against_consonant_mora_is_slightly_lower():
    # たからもの の「か」に対して、マーシャドー の「ー」（あ）は母音が同じでも、別の行の「ら」より少し下
    phrase = to_morae("たか")[1]
    long_vowel = to_morae("まー")[1]
    other_row = to_morae("ら")[0]
    assert scorer.mora_score(phrase, long_vowel) < scorer.mora_score(phrase, other_row)
    assert scorer.mora_score(phrase, other_row) - scorer.mora_score(phrase, long_vowel) == round(
        ScoringParams().long_vowel_mismatch_penalty * SCALE
    )


def test_long_vowel_against_vowel_only_mora_is_exact():
    assert scorer.mora_score(to_morae("くー")[1], to_morae("う")[0]) == FULL
    assert scorer.mora_score(to_morae("う")[0], to_morae("くー")[1]) == FULL


def test_slot_penalty_adds_weak_slot_penalty_below_threshold():
    params = ScoringParams(per_pokemon_penalty=1.0, weak_slot_threshold=0.65, weak_slot_penalty=1.0)
    s = Scorer(params)
    length = 2
    strong = round(0.8 * length * params.max_mora_points * SCALE)
    weak = round(0.5 * length * params.max_mora_points * SCALE)
    assert s.slot_penalty(strong, length) == round(1.0 * SCALE)
    expected_weak = 1.0 + (0.65 - 0.5) * length * params.max_mora_points
    assert s.slot_penalty(weak, length) == round(expected_weak * SCALE)