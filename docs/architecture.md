# 全体設計

## 構成
```
main.py                          コンソールアプリの起動
scripts/build_pokemon_list.py    PokeAPI 生データ → data/pokemon.json
scripts/evaluate_scoring.py      正解例で一致度の付け方を評価する
data/reading_overrides.json      特殊な読みの上書き
data/tuning_examples.json        一致度の調整に使う正解例
src/pokemon_ierukana/
  kana.py        かなの正規化、モーラ分割、母音と子音の判定（Mora）
  scoring.py     区間とポケモン1匹の点数（Scorer、ScoringParams）
  segmenter.py   分割と候補の生成（Converter）
  song.py        曲・フレーズ・グループのモデルと操作（Song）
  song_json.py   曲の JSON での保存と読み込み
  repository.py  data/pokemon.json の読み込み（Pokemon）、名前からの検索（PokemonIndex）
  cli.py         対話型 UI。入出力のみを担当する
tests/           pytest
```

依存の向き: `cli → song_json → song → segmenter → scoring → kana`、`segmenter/song → repository → kana`。
GUI化するときは `cli.py` を差し替え、`Song` と `Converter` をそのまま使う想定。

## 点数（scoring.py）
- `Scorer.mora_score`: 1音同士の点数。母音の近さと子音の近さに重みを掛けて足す（仕様は requirements.md の「一致度」）。
  同じ組み合わせを何度も計算するので、結果をキャッシュする。
- 点数は `SCALE`（100）倍した整数で持つ。DP で足し合わせるときに浮動小数の誤差を気にしなくてよいため。
- 調整できる値は `ScoringParams`（frozen dataclass）にまとめ、`Scorer(params)` → `Converter(pokemon, scorer)` の順に渡す。
- `Scorer.similarity(score, 音数)` で、満点に対する割合（一致度）に直す。
- `Scorer.slot_penalty(score, 音数)` は、組合わせ候補の順位付けで1つの枠から引く点数（1匹ごとの減点＋弱い枠の減点）。
  `Converter._top_segmentations`（区間ごと）と `Converter.rank_key`（組合わせ候補の比較）の両方で使い、順位付けを食い違わせない。

## 対応付け（Scorer.align_score）
フレーズの区間とポケモンの読みを1音ずつ対応付ける。
フレーズ側の ー・っ を省略できるので、省略する位置を DP（フレーズ側の位置 × ポケモン側の位置）で選んで点数を最大にする。
省略した音には固定の点数（`dropped_mora_points`）を入れる。
末尾の余分な音を許す場合は、ポケモンの最後の1音を除いた読みでも対応付けて、良い方を採用する。

## 変換（segmenter.Converter.convert）
1. 全区間 (start, end) について、音数が合う可能性のあるポケモンを（音数で索引して）点数順に並べる。
2. 各区間の第1候補の点数から枠ごとの減点（slot_penalty）を引いた値を使う k-best DP で、合計が高い区切り方を上位10件まで集める。
3. その中から、使用済み（序列ごと）のポケモンを除外して各枠に第1〜第3候補を割り当て、最も良い区切り方を採用する。
   採用した候補を使用済みに加えてから、もう一度評価し直して2つ目を選ぶ。

重複を許すモードでは、使用済みによる除外をしない（同じ枠の中で候補が重ならないことだけを保証する）。
重複禁止モードの使用済み情報（`UsedByRank`: 序列ごとの id 集合）は呼び出し側の `Song` が管理し、フレーズ間で共有する。

「省略しない」設定は `convert(..., fixed_positions)` で渡す。`kana.to_phrase_morae` が文字の位置をモーラに対応させ、
該当する ー・っ の `Mora.fixed` を立てる（`is_optional_in_phrase` が偽になる）。区切りの先頭にしない判定は、
fixed に関係なく `Mora.attaches_to_previous` で行う。

`Converter.score_sequence(phrase, ポケモンの並び)` は、指定した並びで区切ったときの最も良い区切り方を返す。
正解例の評価で、上位に出なかった並びがどれくらいの一致度だったかを見るために使う。

## 曲のモデル（song.py）
```
Song:        title, allow_duplicates, phrases, groups, next_phrase_id, next_group_id
Phrase:      id, text, channel, locked, group_id, combinations, selection, fixed_positions（0始まりの文字の位置）
Group:       id, name
Combination: slots, score, similarity（segmenter.py）
Slot:        start, end, text, candidates（segmenter.py）
Candidate:   pokemon, score, similarity（segmenter.py）
```
- フレーズとグループは固定の ID で扱う。合体・分割・削除で位置が変わっても ID は変わらない（合体は先頭の ID、分割は前半が元の ID を使う）。
  表示上の番号と ID の変換は cli.py が行う。
- `Phrase.selection` は、ユーザーが決めたポケモンの並び（選択情報）。候補（combinations）とは別に持ち、変換し直しても残る。
  候補から選ぶときは `Song.candidate(...)` でポケモンを引いてから `add_selection` / `replace_selection` に渡す（手入力も同じ操作）。
- グループのメンバーは `Phrase.group_id` だけに持たせる（所属を1か所で管理し、合体・分割で更新しやすくするため）。
- 変換はすべて `Song._convert_targets` を通る。重複禁止モードでは、チャンネルごとに `UsedByRank` を持つ。
  まず対象外のフレーズの候補と選択情報（第1序列として）を入れ、それから対象を歌詞の順に `Converter.convert` で変換して積み上げる。

## 曲の JSON 形式（song_json.py）
```json
{
  "version": 3, "title": "...", "allow_duplicates": false,
  "next_phrase_id": 3, "next_group_id": 2,
  "groups": [{"id": 1, "name": "サビ"}],
  "phrases": [{
    "id": 1, "text": "たどりつくばしょ", "channel": 1, "locked": false, "group_id": 1,
    "selection": [{"id": 451, "name": "スコルピ", "reading": "すこるぴ"}],
    "fixed_positions": [],
    "combinations": [{
      "score": 0, "similarity": 0.0,
      "slots": [{"start": 0, "end": 4, "text": "たどりつ",
                 "candidates": [{"id": 451, "name": "スコルピ", "reading": "すこるぴ", "score": 0, "similarity": 0.0}]}]
    }]
  }]
}
```
- 候補のポケモン情報は JSON の中だけで完結する形にしてあり、読み込むときにポケモン一覧を必要としない。
- fixed_positions は後から追加した項目なので、無いファイルは空として読む（version は 3 のまま）。
- 古い形式も読み込める。
  - version 2: 選択中の組合わせ候補の各枠で選んでいたポケモン（手入力を含む）を選択情報にする。
    候補は一致度の付け方が変わって比べられないので捨てる（変換し直して出し直す）。
  - version 1（ID・チャンネル・ロック・グループ・手入力なし）: ID は順番に振り、チャンネルは 1 にしてから、version 2 と同じく扱う。
