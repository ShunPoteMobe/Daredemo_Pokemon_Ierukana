"""ポケモン一覧データの読み込み。"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .kana import Mora, katakana_to_hiragana, to_morae

DEFAULT_POKEMON_PATH = Path(__file__).resolve().parents[2] / "data" / "pokemon.json"


@dataclass(frozen=True)
class Pokemon:
    id: int
    name: str
    reading: str
    morae: tuple[Mora, ...] = field(compare=False, repr=False)


def make_pokemon(pokemon_id: int, name: str, reading: str) -> Pokemon:
    return Pokemon(pokemon_id, name, reading, tuple(to_morae(reading)))


class PokemonIndex:
    """名前（カタカナ表記）またはひらがなの読みからポケモンを引く。"""

    def __init__(self, pokemon: Sequence[Pokemon]):
        self._by_key: dict[str, Pokemon] = {}
        for p in pokemon:
            # ニドラン♂/♀ のように読みが同じでも名前は違うので、名前を優先して登録する
            self._by_key.setdefault(p.reading, p)
        for p in pokemon:
            self._by_key[p.name] = p

    def find(self, key: str) -> Pokemon:
        key = key.strip()
        pokemon = self._by_key.get(key) or self._by_key.get(katakana_to_hiragana(key))
        if pokemon is None:
            raise ValueError(f"「{key}」というポケモンは見つかりません")
        return pokemon


def load_pokemon(path: Path = DEFAULT_POKEMON_PATH) -> list[Pokemon]:
    """scripts/build_pokemon_list.py が生成した一覧を読み込む。"""
    if not path.exists():
        raise FileNotFoundError(f"{path} がありません。先に scripts/build_pokemon_list.py を実行してください")
    entries = json.loads(path.read_text(encoding="utf-8"))
    return [make_pokemon(e["id"], e["name"], e["reading"]) for e in entries]
