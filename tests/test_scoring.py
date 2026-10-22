from pokemon_ierukana.kana import to_morae
from pokemon_ierukana.scoring import align_score, decode_score, mora_score


def score_of(phrase: str, pokemon: str, allow_extra_tail: bool = False):
    return align_score(to_morae(phrase), to_morae(pokemon), allow_extra_tail)


def single(a: str, b: str) -> int:
    return mora_score(to_morae(a)[0], to_morae(b)[0])


def test_priority_exact_over_vowel_over_row():
    assert single("か", "か") > single("か", "さ")  # 完全一致 > 母音一致
    assert single("か", "さ") > single("か", "き")  # 母音一致 > 同じ行
    assert single("か", "き") > single("か", "せ")  # 同じ行 > 異なる母音


def test_vowel_preference_for_different_vowels():
    # あ段: え > い > う > お
    assert single("ら", "め") > single("ら", "み") > single("ら", "む") > single("ら", "も")
    # い段: え > あ > う > お
    assert single("り", "め") > single("り", "ま") > single("り", "む") > single("り", "も")


def test_decode_score_counts():
    # あらたな / こまたな: 完全一致(た,な) 母音一致(ま,た,な) 同じ行(た,な)
    assert decode_score(score_of("あらたな", "こまたな")) == (2, 3, 2, 0, 0, 0)


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


def test_hatsuon_in_phrase_is_not_optional():
    assert score_of("かんな", "かな") is None


def test_pokemon_side_morae_are_not_skipped():
    assert score_of("でるぞ", "けむっそ") is None


def test_extra_tail_only_when_allowed():
    assert score_of("くばしょ", "くましゅん") is None
    assert score_of("くばしょ", "くましゅん", allow_extra_tail=True) is not None
    # 末尾の ー・ッ・ン 以外は余分な音として許さない
    assert score_of("くばし", "くまのみ", allow_extra_tail=True) is None
