import json

import pytest

from pokemon_ierukana.kana import to_reading
from pokemon_ierukana.repository import PokemonIndex, make_pokemon
from pokemon_ierukana.segmenter import Converter
from pokemon_ierukana.song import Song
from pokemon_ierukana.song_json import load_song, save_song

NAMES = ["コマタナ", "アメタマ", "ギラティナ", "ルカリオ", "スコルピ", "クマシュン", "ピカチュウ"]
POKEMON = [make_pokemon(i, name, to_reading(name)) for i, name in enumerate(NAMES, 1)]


@pytest.fixture
def converter() -> Converter:
    return Converter(POKEMON)


@pytest.fixture
def index() -> PokemonIndex:
    return PokemonIndex(POKEMON)


def make_song(*texts: str, allow_duplicates: bool = True) -> Song:
    song = Song(allow_duplicates=allow_duplicates)
    for text in texts:
        song.add_phrase(text)
    return song


def ids(song: Song) -> list[int]:
    return [p.id for p in song.phrases]


def first_candidate(song: Song, phrase_id: int) -> str:
    """組合わせ候補1・枠1の第1候補の名前。"""
    return song.phrase(phrase_id).combinations[0].slots[0].candidates[0].pokemon.name


def first_candidates(song: Song) -> list[str]:
    return [first_candidate(song, p.id) for p in song.phrases]


# ---- フレーズの追加 ----


def test_add_phrase_validates_and_normalizes():
    song = Song()
    assert song.add_phrase(" だれも～が ").text == "だれもーが"
    with pytest.raises(ValueError):
        song.add_phrase("ダレモガ")


def test_phrase_ids_are_stable_after_removal():
    song = make_song("あらたな", "ひかりを", "あらたな")
    song.remove_phrase(1)
    assert ids(song) == [2, 3]
    assert song.add_phrase("ひかりを").id == 4


# ---- 重複モード・チャンネル ----


def test_convert_all_allows_duplicates_by_default(converter):
    song = make_song("あらたな", "あらたな")
    song.convert_all(converter)
    assert first_candidates(song)[0] == first_candidates(song)[1]


def test_convert_all_without_duplicates(converter):
    song = make_song("あらたな", "あらたな", allow_duplicates=False)
    song.convert_all(converter)
    assert first_candidates(song)[0] != first_candidates(song)[1]


def test_convert_single_phrase_avoids_other_phrases(converter):
    song = make_song("あらたな", "あらたな", allow_duplicates=False)
    song.convert_phrase(1, converter)
    song.convert_phrase(2, converter)
    assert first_candidates(song)[0] != first_candidates(song)[1]


def test_different_channels_may_duplicate(converter):
    song = make_song("あらたな", "あらたな", allow_duplicates=False)
    song.set_channel([2], 2)
    song.convert_all(converter)
    assert first_candidates(song)[0] == first_candidates(song)[1]


def test_channel_is_ignored_when_duplicates_allowed(converter):
    song = make_song("あらたな", "あらたな")
    song.set_channel([2], 2)
    song.convert_all(converter)
    assert first_candidates(song)[0] == first_candidates(song)[1]


def test_invalid_channel():
    with pytest.raises(ValueError):
        make_song("あらたな").set_channel([1], 0)


# ---- 選択情報 ----


def test_selection_starts_empty_and_survives_reconversion(converter):
    song = make_song("あらたな")
    song.convert_phrase(1, converter)
    assert song.phrase(1).selection == []

    song.add_selection(1, song.candidate(1, 0, 0, 1))
    selected = song.phrase(1).selected_names()
    song.convert_phrase(1, converter)
    assert song.phrase(1).selected_names() == selected


def test_selection_across_slots_and_combinations(converter):
    song = make_song("たどりつくばしょ")
    song.convert_phrase(1, converter)
    phrase = song.phrase(1)
    last = len(phrase.combinations) - 1
    a = song.candidate(1, 0, 0, 0)
    b = song.candidate(1, last, len(phrase.combinations[last].slots) - 1, 0)
    song.add_selection(1, a)
    song.add_selection(1, b)
    assert phrase.selection == [a, b]


def test_selection_replace_remove_clear_and_duplicates(converter, index):
    song = make_song("あらたな")
    song.convert_phrase(1, converter)
    pikachu = index.find("ぴかちゅう")
    song.add_selection(1, pikachu)
    song.add_selection(1, pikachu)  # 同じポケモンを2回入れてもよい
    assert song.phrase(1).selected_names() == ["ピカチュウ", "ピカチュウ"]

    song.replace_selection(1, 1, song.candidate(1, 0, 0, 0))
    assert song.phrase(1).selected_names()[1] == first_candidate(song, 1)

    song.remove_selection(1, 0)
    assert len(song.phrase(1).selection) == 1
    song.clear_selection(1)
    assert song.phrase(1).selection == []

    with pytest.raises(ValueError):
        song.replace_selection(1, 0, pikachu)


def test_candidate_lookup_errors(converter):
    song = make_song("あらたな")
    with pytest.raises(ValueError):
        song.candidate(1, 0, 0, 0)  # 未変換
    song.convert_phrase(1, converter)
    with pytest.raises(ValueError):
        song.candidate(1, 0, 0, 5)


def test_selection_counts_as_first_rank(converter, index):
    song = make_song("あらたな", "あらたな", allow_duplicates=False)
    song.convert_phrase(1, converter)
    first = first_candidate(song, 1)
    # 第1候補とは別のポケモンを選択情報に入れ、それも第1序列として避けられることを確かめる
    song.add_selection(1, index.find("コマタナ"))
    song.convert_phrase(2, converter)
    assert first_candidate(song, 2) not in {first, "コマタナ"}


def test_pokemon_index_unknown_name(index):
    with pytest.raises(ValueError):
        index.find("ミュウツー")


# ---- ロック ----


def test_locked_phrase_is_kept_and_reserved(converter):
    song = make_song("あらたな", "あらたな", allow_duplicates=False)
    song.convert_phrase(2, converter)
    locked_first = first_candidate(song, 2)
    song.set_locked([2], True)

    song.convert_all(converter)
    assert first_candidate(song, 2) == locked_first
    # フレーズ1の方が前でも、ロック中のフレーズ2の第1候補は避けられる
    assert first_candidate(song, 1) != locked_first


def test_locked_phrase_rejects_changes(converter, index):
    song = make_song("あらたな", "ひかりを")
    song.convert_all(converter)
    song.add_selection(1, index.find("ピカチュウ"))
    song.set_locked([1], True)
    for operation in (
        lambda: song.convert_phrase(1, converter),
        lambda: song.add_selection(1, index.find("ピカチュウ")),
        lambda: song.replace_selection(1, 0, index.find("コマタナ")),
        lambda: song.remove_selection(1, 0),
        lambda: song.clear_selection(1),
        lambda: song.merge([1, 2]),
        lambda: song.split(1, 2),
    ):
        with pytest.raises(ValueError):
            operation()
    song.set_locked([1], False)
    song.clear_selection(1)


# ---- 合体・分割 ----


def test_merge_concatenates_selection_and_clears_candidates(converter, index):
    song = make_song("たどりつ", "くばしょ", "ひかりを")
    song.convert_all(converter)
    song.add_selection(1, index.find("スコルピ"))
    song.add_selection(2, index.find("クマシュン"))
    song.add_selection(2, index.find("スコルピ"))

    merged = song.merge([2, 1])
    assert ids(song) == [1, 3]
    assert merged.text == "たどりつくばしょ"
    assert merged.selected_names() == ["スコルピ", "クマシュン", "スコルピ"]
    assert merged.combinations == []


def test_merge_requires_consecutive_phrases():
    song = make_song("あらたな", "ひかりを", "あらたな")
    with pytest.raises(ValueError):
        song.merge([1, 3])
    with pytest.raises(ValueError):
        song.merge([1])


def test_split_into_two_and_clear_results(converter, index):
    song = make_song("たどりつくばしょ", allow_duplicates=False)
    song.set_channel([1], 3)
    group = song.create_group([1])
    song.convert_all(converter)
    song.add_selection(1, index.find("スコルピ"))

    first, second = song.split(1, 4)
    assert [p.text for p in song.phrases] == ["たどりつ", "くばしょ"]
    assert all(p.combinations == [] and p.selection == [] for p in (first, second))
    assert first.id == 1 and second.id == 2
    assert all(p.channel == 3 and p.group_id == group.id for p in song.phrases)


@pytest.mark.parametrize("position", [0, 8, 7])
def test_split_rejects_invalid_position(position):
    # 7文字目の後ろは「し|ょ」の途中
    song = make_song("たどりつくばしょ")
    with pytest.raises(ValueError):
        song.split(1, position)


# ---- グループ ----


def test_group_operations_apply_to_members_only(converter):
    song = make_song("あらたな", "あらたな", "あらたな", allow_duplicates=False)
    group = song.create_group([1, 2], "サビ")
    members = [p.id for p in song.group_members(group.id)]

    song.convert_group(group.id, converter)
    assert song.phrase(3).combinations == []
    assert first_candidate(song, 1) != first_candidate(song, 2)

    song.set_channel(members, 2)
    song.set_locked(members, True)
    assert [(p.channel, p.locked) for p in song.phrases] == [(2, True), (2, True), (1, False)]
    with pytest.raises(ValueError):
        song.convert_group(group.id, converter)


def test_phrase_belongs_to_one_group():
    song = make_song("あらたな", "ひかりを")
    song.create_group([1])
    with pytest.raises(ValueError):
        song.create_group([1, 2])


def test_remove_group_keeps_phrases():
    song = make_song("あらたな", "ひかりを")
    group = song.create_group([1, 2])
    song.remove_group(group.id)
    assert song.groups == []
    assert len(song.phrases) == 2 and all(p.group_id is None for p in song.phrases)


def test_empty_group_is_removed_automatically():
    song = make_song("あらたな", "ひかりを")
    song.create_group([2])
    song.remove_phrase(2)
    assert song.groups == []


# ---- 省略しない設定・フレーズの変更 ----


def test_set_fixed_and_errors():
    song = make_song("だれもっがうばー")
    song.set_fixed(1, [3, 7], True)
    assert song.phrase(1).fixed_positions == {3, 7}
    song.set_fixed(1, [7], False)
    assert song.phrase(1).fixed_positions == {3}
    with pytest.raises(ValueError):
        song.set_fixed(1, [0], True)  # 「だ」は ー・っ ではない
    with pytest.raises(ValueError):
        song.set_fixed(1, [8], True)  # 範囲外


def test_fixed_positions_follow_merge_and_split():
    song = make_song("だれもっが", "うばー")
    song.set_fixed(1, [3], True)
    song.set_fixed(2, [2], True)
    merged = song.merge([1, 2])
    assert merged.fixed_positions == {3, 7}

    first, second = song.split(1, 5)
    assert (first.fixed_positions, second.fixed_positions) == ({3}, {2})


def test_edit_phrase_resets_conversion(converter, index):
    song = make_song("だれもーが", allow_duplicates=False)
    song.set_channel([1], 2)
    group = song.create_group([1])
    song.set_fixed(1, [3], True)
    song.convert_phrase(1, converter)
    song.add_selection(1, index.find("ピカチュウ"))

    phrase = song.edit_phrase(1, "ひかりを")
    assert (phrase.id, phrase.text, phrase.channel, phrase.group_id) == (1, "ひかりを", 2, group.id)
    assert phrase.combinations == [] and phrase.selection == [] and phrase.fixed_positions == set()

    with pytest.raises(ValueError):
        song.edit_phrase(1, "ヒカリヲ")
    song.set_locked([1], True)
    with pytest.raises(ValueError):
        song.edit_phrase(1, "あらたな")


# ---- JSON ----


def test_json_round_trip(converter, index, tmp_path):
    song = make_song("たどりつくばしょ", "ひかりを", allow_duplicates=False)
    song.title = "テスト"
    song.convert_all(converter)
    song.add_selection(2, index.find("ピカチュウ"))
    song.set_channel([2], 2)
    song.set_locked([1], True)
    song.create_group([1, 2], "サビ")
    song.edit_phrase(2, "ひかりをー")
    song.set_fixed(2, [4], True)

    path = tmp_path / "song.json"
    save_song(song, path)
    loaded = load_song(path)

    assert loaded == song
    assert loaded.add_phrase("あらたな").id == 3


V2_SLOT = {
    "start": 0,
    "end": 4,
    "text": "ひかりを",
    "selected": 1,
    "manual": None,
    "candidates": [
        {"id": 448, "name": "ルカリオ", "reading": "るかりお", "score": 1},
        {"id": 7, "name": "ゼニガメ", "reading": "ぜにがめ", "score": 1},
    ],
}


def test_load_version2_moves_choices_to_selection(tmp_path):
    manual_slot = {**V2_SLOT, "manual": {"id": 25, "name": "ピカチュウ", "reading": "ぴかちゅう"}}
    v2 = {
        "version": 2,
        "title": "v2",
        "allow_duplicates": True,
        "next_phrase_id": 3,
        "next_group_id": 1,
        "groups": [],
        "phrases": [
            {"id": 1, "text": "ひかりを", "channel": 1, "locked": False, "group_id": None, "selected": 0,
             "combinations": [{"score": 1, "slots": [V2_SLOT, manual_slot]}]},
            {"id": 2, "text": "あらたな", "channel": 2, "locked": True, "group_id": None, "selected": 0,
             "combinations": []},
        ],
    }
    path = tmp_path / "v2.json"
    path.write_text(json.dumps(v2, ensure_ascii=False), encoding="utf-8")

    song = load_song(path)
    assert song.phrase(1).selected_names() == ["ゼニガメ", "ピカチュウ"]
    assert song.phrase(1).combinations == []
    assert (song.phrase(2).channel, song.phrase(2).locked, song.phrase(2).selection) == (2, True, [])


def test_load_version1(tmp_path):
    v1 = {
        "version": 1,
        "title": "旧形式",
        "allow_duplicates": False,
        "phrases": [
            {"text": "あらたな", "selected": 0, "combinations": []},
            {"text": "ひかりを", "selected": 0,
             "combinations": [{"score": 1, "slots": [{k: v for k, v in V2_SLOT.items() if k != "manual"}]}]},
        ],
    }
    path = tmp_path / "v1.json"
    path.write_text(json.dumps(v1, ensure_ascii=False), encoding="utf-8")

    song = load_song(path)
    assert ids(song) == [1, 2]
    assert song.phrase(2).selected_names() == ["ゼニガメ"]
    assert all(p.channel == 1 and not p.locked and p.group_id is None for p in song.phrases)
    assert song.add_phrase("あらたな").id == 3
