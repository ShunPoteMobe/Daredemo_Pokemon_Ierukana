"""曲の JSON での保存と読み込み。

候補のポケモン情報は JSON の中だけで完結させ、読み込むときにポケモン一覧を必要としない。
"""

from __future__ import annotations

import json
from pathlib import Path

from .repository import Pokemon, make_pokemon
from .segmenter import Candidate, Combination, Slot
from .song import DEFAULT_CHANNEL, Group, Phrase, Song

FORMAT_VERSION = 3


def save_song(song: Song, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(song_to_dict(song), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_song(path: Path) -> Song:
    return song_from_dict(json.loads(path.read_text(encoding="utf-8")))


def song_to_dict(song: Song) -> dict:
    return {
        "version": FORMAT_VERSION,
        "title": song.title,
        "allow_duplicates": song.allow_duplicates,
        "next_phrase_id": song.next_phrase_id,
        "next_group_id": song.next_group_id,
        "groups": [{"id": g.id, "name": g.name} for g in song.groups],
        "phrases": [_phrase_to_dict(p) for p in song.phrases],
    }


def song_from_dict(data: dict) -> Song:
    version = data.get("version")
    if version == 1:
        data = _upgrade_v2(_upgrade_v1(data))
    elif version == 2:
        data = _upgrade_v2(data)
    elif version != FORMAT_VERSION:
        raise ValueError(f"対応していない形式です（version={version}）")
    return Song(
        title=data.get("title", ""),
        allow_duplicates=data["allow_duplicates"],
        phrases=[_phrase_from_dict(p) for p in data["phrases"]],
        groups=[Group(g["id"], g["name"]) for g in data["groups"]],
        next_phrase_id=data["next_phrase_id"],
        next_group_id=data["next_group_id"],
    )


def _upgrade_v1(data: dict) -> dict:
    """version 1（ID・チャンネル・ロック・グループ・手入力なし）を version 2 の形にする。"""
    phrases = [
        {**p, "id": i, "channel": DEFAULT_CHANNEL, "locked": False, "group_id": None}
        for i, p in enumerate(data["phrases"], 1)
    ]
    return {
        **data,
        "version": 2,
        "phrases": phrases,
        "groups": [],
        "next_phrase_id": len(phrases) + 1,
        "next_group_id": 1,
    }


def _upgrade_v2(data: dict) -> dict:
    """version 2 を version 3 の形にする。

    選択中の組合わせ候補の各枠で選んでいたポケモン（手入力を含む）を選択情報として引き継ぐ。
    候補は一致度の付け方が変わって比べられないため捨てる（変換し直して出し直す）。
    """
    phrases = []
    for p in data["phrases"]:
        selection = []
        if p["combinations"]:
            for slot in p["combinations"][p["selected"]]["slots"]:
                chosen = slot.get("manual") or slot["candidates"][slot["selected"]]
                selection.append({k: chosen[k] for k in ("id", "name", "reading")})
        phrase = {k: v for k, v in p.items() if k not in ("selected", "combinations")}
        phrases.append({**phrase, "combinations": [], "selection": selection})
    return {**data, "version": FORMAT_VERSION, "phrases": phrases}


def _pokemon_to_dict(pokemon: Pokemon) -> dict:
    return {"id": pokemon.id, "name": pokemon.name, "reading": pokemon.reading}


def _pokemon_from_dict(data: dict) -> Pokemon:
    return make_pokemon(data["id"], data["name"], data["reading"])


def _phrase_to_dict(phrase: Phrase) -> dict:
    return {
        "id": phrase.id,
        "text": phrase.text,
        "channel": phrase.channel,
        "locked": phrase.locked,
        "group_id": phrase.group_id,
        "selection": [_pokemon_to_dict(p) for p in phrase.selection],
        "fixed_positions": sorted(phrase.fixed_positions),
        "combinations": [
            {
                "score": c.score,
                "similarity": c.similarity,
                "slots": [
                    {
                        "start": s.start,
                        "end": s.end,
                        "text": s.text,
                        "candidates": [
                            {**_pokemon_to_dict(cand.pokemon), "score": cand.score, "similarity": cand.similarity}
                            for cand in s.candidates
                        ],
                    }
                    for s in c.slots
                ],
            }
            for c in phrase.combinations
        ],
    }


def _phrase_from_dict(data: dict) -> Phrase:
    combinations = [
        Combination(
            slots=[
                Slot(
                    start=s["start"],
                    end=s["end"],
                    text=s["text"],
                    candidates=[
                        Candidate(_pokemon_from_dict(cand), cand["score"], cand["similarity"]) for cand in s["candidates"]
                    ],
                )
                for s in c["slots"]
            ],
            score=c["score"],
            similarity=c["similarity"],
        )
        for c in data["combinations"]
    ]
    return Phrase(
        id=data["id"],
        text=data["text"],
        channel=data["channel"],
        locked=data["locked"],
        group_id=data["group_id"],
        combinations=combinations,
        selection=[_pokemon_from_dict(p) for p in data["selection"]],
        # 「省略しない」設定は後から追加した項目なので、無いファイルは空として読む
        fixed_positions=set(data.get("fixed_positions", [])),
    )
