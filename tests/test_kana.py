from pokemon_ierukana.kana import is_valid_reading, split_morae, to_morae, to_phrase_morae, to_reading


def test_to_reading_converts_katakana_and_removes_symbols():
    assert to_reading("カプ・コケコ") == "かぷこけこ"
    assert to_reading("タイプ：ヌル") == "たいぷぬる"
    assert to_reading("サーフゴー") == "さーふごー"
    assert to_reading("ヴィ") == "ゔぃ"


def test_is_valid_reading():
    assert is_valid_reading("だれもーが")
    assert not is_valid_reading("abc")
    assert not is_valid_reading("ゃあ")
    assert not is_valid_reading("")


def test_split_morae_treats_youon_as_one_mora():
    assert split_morae("たどりつくばしょ") == ["た", "ど", "り", "つ", "く", "ば", "しょ"]
    assert split_morae("でゅえるー") == ["でゅ", "え", "る", "ー"]
    assert split_morae("いつだって") == ["い", "つ", "だ", "っ", "て"]


def test_split_morae_separates_small_vowel_with_same_vowel():
    # ピィ は「ぴー」と伸ばす音なので2音
    assert split_morae("ぴぃ") == ["ぴ", "い"]
    assert split_morae("けーしぃ") == ["け", "ー", "し", "い"]
    assert split_morae("でぃぐだ") == ["でぃ", "ぐ", "だ"]


def test_to_morae_vowel_and_consonant():
    morae = to_morae("しょーがん")
    assert [(m.vowel, m.consonant) for m in morae] == [("o", "s"), ("o", ""), ("a", "g"), (None, "N")]


def test_long_vowel_is_vowel_of_previous_mora():
    # くー の ー は「う」、きー の ー は「い」
    assert (to_morae("くー")[1].vowel, to_morae("くー")[1].consonant) == ("u", "")
    assert to_morae("きー")[1].vowel == "i"


def test_voiced_kana_have_different_consonants():
    assert to_morae("と")[0].consonant == "t"
    assert to_morae("ど")[0].consonant == "d"
    assert to_morae("ゔぁ")[0].consonant == "b"


def test_optional_morae_in_phrase():
    morae = {m.text: m for m in to_morae("たっどーりん")}
    assert morae["っ"].is_optional_in_phrase
    assert morae["ー"].is_optional_in_phrase
    assert not morae["ん"].is_optional_in_phrase
    assert morae["ん"].is_extendable_tail


def test_to_phrase_morae_marks_fixed_positions():
    # 「だれもっがめをうばー」の4文字目（っ）を省略しない。10文字目（ー）は省略できるまま
    morae = to_phrase_morae("だれもっがめをうばー", {3})
    sokuon, long_vowel = morae[3], morae[-1]
    assert sokuon.text == "っ" and sokuon.fixed and not sokuon.is_optional_in_phrase
    assert sokuon.attaches_to_previous
    assert long_vowel.is_optional_in_phrase


def test_to_phrase_morae_counts_characters_of_youon():
    # しょ は2文字で1音。6文字目（位置5）の ー を正しく対応させる
    morae = to_phrase_morae("しょうしょー", {5})
    assert [m.text for m in morae] == ["しょ", "う", "しょ", "ー"]
    assert morae[-1].fixed