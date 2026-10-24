"""正解例（data/tuning_examples.json）を使って、一致度の付け方を評価する。

使い方:
    python scripts/evaluate_scoring.py [--vowel-weight 3] [--consonant-weight 1] [--penalty 1] [--dropped 2]
                                       [--weak-threshold 0.65] [--weak-penalty 1] [--long-vowel-penalty 0.5]

例ごとに、変換結果の上位と、正解の並びがどう扱われたかを表示する。
- 出た     : 正解の並びが、どれかの組合わせ候補の第1候補の並びとしてそのまま出た
- 候補内   : 正解の並びの区切り方が組合わせ候補に出て、各ポケモンがその枠の候補（3位以内）に入った
- 出ない   : 上のどちらでもない。その並びで区切った場合の一致度も表示する（区切れない場合はその旨）
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from pokemon_ierukana.repository import PokemonIndex, load_pokemon  # noqa: E402
from pokemon_ierukana.scoring import Scorer, ScoringParams  # noqa: E402
from pokemon_ierukana.segmenter import Combination, Converter  # noqa: E402

DEFAULT_EXAMPLES = PROJECT_ROOT / "data" / "tuning_examples.json"


def describe(combination: Combination) -> str:
    names = " / ".join(slot.candidates[0].pokemon.name for slot in combination.slots)
    return f"{names}  ({combination.similarity:.0%}, {combination.pattern})"


def judge(combinations: list[Combination], names: list[str]) -> str:
    for ci, combination in enumerate(combinations, 1):
        if len(combination.slots) != len(names):
            continue
        firsts = [slot.candidates[0].pokemon.name for slot in combination.slots]
        if firsts == names:
            return f"出た（組合わせ{ci}）"
        ranks = []
        for slot, name in zip(combination.slots, names):
            found = [c.pokemon.name for c in slot.candidates]
            ranks.append(found.index(name) + 1 if name in found else None)
        if all(r is not None for r in ranks):
            return f"候補内（組合わせ{ci}、" + " / ".join(f"{r}位" for r in ranks) + "）"
    return "出ない"


def main() -> None:
    defaults = ScoringParams()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--vowel-weight", type=float, default=defaults.vowel_weight)
    parser.add_argument("--consonant-weight", type=float, default=defaults.consonant_weight)
    parser.add_argument("--penalty", type=float, default=defaults.per_pokemon_penalty, help="1匹ごとの減点")
    parser.add_argument("--dropped", type=float, default=defaults.dropped_mora_points, help="省略した ー・っ の点数")
    parser.add_argument("--weak-threshold", type=float, default=defaults.weak_slot_threshold, help="弱い枠とみなす一致度")
    parser.add_argument("--weak-penalty", type=float, default=defaults.weak_slot_penalty, help="弱い枠の減点の係数")
    parser.add_argument(
        "--long-vowel-penalty", type=float, default=defaults.long_vowel_mismatch_penalty, help="ー と子音のある音の減点"
    )
    parser.add_argument("--examples", type=Path, default=DEFAULT_EXAMPLES)
    args = parser.parse_args()

    params = ScoringParams(
        vowel_weight=args.vowel_weight,
        consonant_weight=args.consonant_weight,
        per_pokemon_penalty=args.penalty,
        dropped_mora_points=args.dropped,
        weak_slot_threshold=args.weak_threshold,
        weak_slot_penalty=args.weak_penalty,
        long_vowel_mismatch_penalty=args.long_vowel_penalty,
    )
    pokemon = load_pokemon()
    converter = Converter(pokemon, Scorer(params))
    index = PokemonIndex(pokemon)
    examples = json.loads(args.examples.read_text(encoding="utf-8"))

    print(
        f"母音={params.vowel_weight} 子音={params.consonant_weight} 1匹ごとの減点={params.per_pokemon_penalty} "
        f"省略した音={params.dropped_mora_points} 弱い枠={params.weak_slot_threshold:.0%}未満×{params.weak_slot_penalty} "
        f"ーと子音のある音={params.long_vowel_mismatch_penalty}"
    )
    counts = {"出た": 0, "候補内": 0, "出ない": 0}
    for example in examples:
        phrase = example["phrase"]
        combinations = converter.convert(phrase)
        print(f"\n== {phrase}" + (f"  ※{example['note']}" if example.get("note") else ""))
        for ci, combination in enumerate(combinations, 1):
            print(f"   組合わせ{ci}: {describe(combination)}")
        for names in example["expected"]:
            result = judge(combinations, names)
            counts[result.split("（")[0]] += 1
            line = f"   正解 {' / '.join(names)}: {result}"
            if result == "出ない":
                scored = converter.score_sequence(phrase, [index.find(name) for name in names])
                line += f" … この並びの一致度 {scored.similarity:.0%}" if scored else " … この並びでは区切れない"
            print(line)

    total = sum(counts.values())
    print(f"\n集計（正解の並び {total} 件）: " + "  ".join(f"{k} {v}" for k, v in counts.items()))


if __name__ == "__main__":
    main()
