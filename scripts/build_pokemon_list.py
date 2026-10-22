"""PokeAPI の pokemon-species 生データから、アプリで使うポケモン一覧を生成する。

使い方:
    python scripts/build_pokemon_list.py [--raw-dir DIR] [--overrides FILE] [--output FILE]

species 単位のデータを使うので、フォルム違い・リージョンフォーム・メガシンカ・ゲンシカイキは含まれない。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pokemon_ierukana.kana import is_valid_reading, to_reading  # noqa: E402

NAME_LANGUAGE = "ja-hrkt"


def load_species_names(raw_dir: Path) -> list[tuple[int, str]]:
    """生データから (図鑑番号, カタカナ表記の名前) を読み込む。"""
    entries = []
    for path in raw_dir.glob("*.json"):
        species = json.loads(path.read_text(encoding="utf-8"))
        names = [n["name"] for n in species["names"] if n["language"]["name"] == NAME_LANGUAGE]
        if not names:
            raise ValueError(f"{path.name}: {NAME_LANGUAGE} の名前がありません")
        entries.append((species["id"], names[0]))
    return sorted(entries)


def build_pokemon_list(entries: list[tuple[int, str]], overrides: dict[str, str]) -> list[dict]:
    pokemon = []
    for pokedex_id, name in entries:
        reading = overrides.get(name) or to_reading(name)
        if not is_valid_reading(reading):
            raise ValueError(f"{pokedex_id} {name}: 読み '{reading}' に変換できない文字があります。overrides に追加してください")
        pokemon.append({"id": pokedex_id, "name": name, "reading": reading})
    return pokemon


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--raw-dir", type=Path, default=PROJECT_ROOT / "data" / "raw" / "pokeapi" / "pokemon-species")
    parser.add_argument("--overrides", type=Path, default=PROJECT_ROOT / "data" / "reading_overrides.json")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "data" / "pokemon.json")
    args = parser.parse_args()

    overrides = json.loads(args.overrides.read_text(encoding="utf-8"))
    pokemon = build_pokemon_list(load_species_names(args.raw_dir), overrides)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(pokemon, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(pokemon)} 件を {args.output} に出力しました")


if __name__ == "__main__":
    main()
