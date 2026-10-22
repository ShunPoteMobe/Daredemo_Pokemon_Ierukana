from pokemon_ierukana.kana import is_valid_reading, split_morae, to_morae, to_reading


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


def test_to_morae_vowel_and_row():
    morae = to_morae("しょーがん")
    assert [(m.vowel, m.row) for m in morae] == [("o", "s"), ("o", None), ("a", "k"), (None, None)]


def test_voiced_kana_share_row_with_unvoiced():
    assert to_morae("と")[0].row == to_morae("ど")[0].row
    assert to_morae("は")[0].row == to_morae("ぱ")[0].row == to_morae("ば")[0].row


def test_optional_morae_in_phrase():
    morae = {m.text: m for m in to_morae("たっどーりん")}
    assert morae["っ"].is_optional_in_phrase
    assert morae["ー"].is_optional_in_phrase
    assert not morae["ん"].is_optional_in_phrase
    assert morae["ん"].is_extendable_tail
