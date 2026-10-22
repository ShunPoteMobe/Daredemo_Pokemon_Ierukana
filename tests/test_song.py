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


def first_names(song: Song) -> list[str]:
    return [p.selected_names()[0] for p in song.phrases]


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
    assert first_names(song)[0] == first_names(song)[1]


def test_convert_all_without_duplicates(converter):
    song = make_song("あらたな", "あらたな", allow_duplicates=False)
    song.convert_all(converter)
    assert first_names(song)[0] != first_names(song)[1]


def test_convert_single_phrase_avoids_other_phrases(converter):
    song = make_song("あらたな", "あらたな", allow_duplicates=False)
    song.convert_phrase(1, converter)
    song.convert_phrase(2, converter)
    assert first_names(song)[0] != first_names(song)[1]


def test_different_channels_may_duplicate(converter):
    song = make_song("あらたな", "あらたな", allow_duplicates=False)
    song.set_channel([2], 2)
    song.convert_all(converter)
    assert first_names(song)[0] == first_names(song)[1]


def test_channel_is_ignored_when_duplicates_allowed(converter):
    song = make_song("あらたな", "あらたな")
    song.set_channel([2], 2)
    song.convert_all(converter)
    assert first_names(song)[0] == first_names(song)[1]


def test_invalid_channel():
    with pytest.raises(ValueError):
        make_song("あらたな").set_channel([1], 0)


# ---- ロック ----


def test_locked_phrase_is_kept_and_reserved(converter):
    song = make_song("あらたな", "あらたな", allow_duplicates=False)
    song.convert_phrase(2, converter)
    locked_name = song.phrase(2).selected_names()
    song.set_locked([2], True)

    song.convert_all(converter)
    assert song.phrase(2).selected_names() == locked_name
    # フレーズ1の方が前でも、ロック中のフレーズ2の第1候補は避けられる
    assert first_names(song)[0] != locked_name[0]


def test_locked_phrase_rejects_changes(converter, index):
    song = make_song("あらたな", "ひかりを")
    song.convert_all(converter)
    song.set_locked([1], True)
    for operation in (
        lambda: song.convert_phrase(1, converter),
        lambda: song.select_combination(1, 0),
        lambda: song.select_candidate(1, 0, 1),
        lambda: song.set_manual(1, 0, index.find("ピカチュウ")),
        lambda: song.merge([1, 2]),
        lambda: song.split(1, 2),
    ):
        with pytest.raises(ValueError):
            operation()
    song.set_locked([1], False)
    song.select_candidate(1, 0, 1)


# ---- 候補の選択・手入力 ----


def test_select_candidate(converter):
    song = make_song("あらたな")
    song.convert_all(converter)
    song.select_candidate(1, 0, 1)
    slot = song.phrase(1).combinations[0].slots[0]
    assert song.phrase(1).selected_names() == [slot.candidates[1].pokemon.name]
    with pytest.raises(ValueError):
        song.select_candidate(1, 0, 5)


def test_manual_entry_becomes_result_and_is_cleared_by_pick(converter, index):
    song = make_song("あらたな")
    song.convert_all(converter)
    song.set_manual(1, 0, index.find("ぴかちゅう"))
    assert song.phrase(1).selected_names() == ["ピカチュウ"]

    song.select_candidate(1, 0, 0)
    assert song.phrase(1).selected_names() != ["ピカチュウ"]


def test_manual_entry_is_cleared_by_reconversion(converter, index):
    song = make_song("あらたな")
    song.convert_all(converter)
    song.set_manual(1, 0, index.find("ピカチュウ"))
    song.convert_phrase(1, converter)
    assert song.phrase(1).selected_names() != ["ピカチュウ"]


def test_manual_entry_counts_as_first_rank(converter, index):
    song = make_song("あらたな", "あらたな", allow_duplicates=False)
    song.convert_phrase(1, converter)
    first = song.phrase(1).combinations[0].slots[0].candidates[0].pokemon
    # 第1候補とは別のポケモンを手入力し、それも第1序列として避けられることを確かめる
    song.set_manual(1, 0, index.find("コマタナ"))
    song.convert_phrase(2, converter)
    assert first_names(song)[1] not in {first.name, "コマタナ"}


def test_pokemon_index_unknown_name(index):
    with pytest.raises(ValueError):
        index.find("ミュウツー")


# ---- 合体・分割 ----


def test_merge_keeps_selected_results(converter, index):
    song = make_song("たどりつ", "くばしょ", "ひかりを")
    song.convert_all(converter)
    song.select_candidate(1, 0, 1)
    song.set_manual(2, 0, index.find("ピカチュウ"))
    expected = song.phrase(1).selected_names() + song.phrase(2).selected_names()

    merged = song.merge([2, 1])
    assert ids(song) == [1, 3]
    assert merged.text == "たどりつくばしょ"
    assert merged.selected_names() == expected
    assert [(s.start, s.end) for s in merged.combinations[0].slots] == [(0, 4), (4, 7)]


def test_merge_with_unconverted_phrase_clears_result(converter):
    song = make_song("たどりつ", "くばしょ")
    song.convert_phrase(1, converter)
    assert song.merge([1, 2]).combinations == []


def test_merge_requires_consecutive_phrases():
    song = make_song("あらたな", "ひかりを", "あらたな")
    with pytest.raises(ValueError):
        song.merge([1, 3])
    with pytest.raises(ValueError):
        song.merge([1])


def test_split_into_two_and_clear_results(converter):
    song = make_song("たどりつくばしょ", allow_duplicates=False)
    song.set_channel([1], 3)
    group = song.create_group([1])
    song.convert_all(converter)

    first, second = song.split(1, 4)
    assert [p.text for p in song.phrases] == ["たどりつ", "くばしょ"]
    assert first.combinations == [] and second.combinations == []
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
    assert song.phrase(1).selected_names() != song.phrase(2).selected_names()

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


# ---- JSON ----


def test_json_round_trip(converter, index, tmp_path):
    song = make_song("たどりつくばしょ", "ひかりを", allow_duplicates=False)
    song.title = "テスト"
    song.convert_all(converter)
    song.set_manual(2, 0, index.find("ピカチュウ"))
    song.set_channel([2], 2)
    song.set_locked([1], True)
    song.create_group([1, 2], "サビ")

    path = tmp_path / "song.json"
    save_song(song, path)
    loaded = load_song(path)

    assert loaded == song
    assert loaded.add_phrase("あらたな").id == 3


def test_load_version1(tmp_path):
    v1 = {
        "version": 1,
        "title": "旧形式",
        "allow_duplicates": False,
        "phrases": [
            {"text": "あらたな", "selected": 0, "combinations": []},
            {
                "text": "ひかりを",
                "selected": 0,
                "combinations": [
                    {
                        "score": 1,
                        "slots": [
                            {
                                "start": 0,
                                "end": 4,
                                "text": "ひかりを",
                                "selected": 0,
                                "candidates": [{"id": 448, "name": "ルカリオ", "reading": "るかりお", "score": 1}],
                            }
                        ],
                    }
                ],
            },
        ],
    }
    path = tmp_path / "v1.json"
    path.write_text(json.dumps(v1, ensure_ascii=False), encoding="utf-8")

    song = load_song(path)
    assert ids(song) == [1, 2]
    assert song.phrase(2).selected_names() == ["ルカリオ"]
    assert all(p.channel == 1 and not p.locked and p.group_id is None for p in song.phrases)
    assert song.add_phrase("あらたな").id == 3
