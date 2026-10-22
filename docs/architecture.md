# 全体設計

## 構成
```
main.py                          コンソールアプリの起動
scripts/build_pokemon_list.py    PokeAPI 生データ → data/pokemon.json
data/reading_overrides.json      特殊な読みの上書き
src/pokemon_ierukana/
  kana.py        かなの正規化、モーラ分割、母音と行の判定（Mora）
  scoring.py     区間とポケモン1匹の一致度（align_score）
  segmenter.py   分割と候補の生成（Converter）
  song.py        曲・フレーズ・グループのモデルと操作（Song）
  song_json.py   曲の JSON での保存と読み込み
  repository.py  data/pokemon.json の読み込み（Pokemon）、名前からの検索（PokemonIndex）
  cli.py         対話型 UI。入出力のみを担当する
tests/           pytest
```

依存の向き: `cli → song_json → song → segmenter → scoring → kana`、`segmenter/song → repository → kana`。
GUI化するときは `cli.py` を差し替え、`Song` と `Converter` をそのまま使う想定。

## 一致度の表現（scoring.py）
各評価項目の件数を、基数1000の桁に詰めた1つの整数で表す。
整数の大小がそのまま辞書式の比較になり、区間ごとの足し算もできるので、DP で扱いやすい。
表示するときは `decode_score` で件数に戻す。

## 対応付け（scoring.align_score）
フレーズの区間とポケモンの読みを1音ずつ対応付ける。
フレーズ側の ー・っ を省略できるので、省略する位置を DP（フレーズ側の位置 × ポケモン側の位置）で選んで一致度を最大にする。
末尾の余分な音を許す場合は、ポケモンの最後の1音を除いた読みでも対応付けて、良い方を採用する。

## 変換（segmenter.Converter.convert）
1. 全区間 (start, end) について、音数が合う可能性のあるポケモンを（音数で索引して）一致度順に並べる。
2. 各区間の第1候補の一致度を使う k-best DP で、合計が高い区切り方を上位10件まで集める。
3. その中から、使用済み（序列ごと）のポケモンを除外して各枠に第1〜第3候補を割り当て、最も良い区切り方を採用する。
   採用した候補を使用済みに加えてから、もう一度評価し直して2つ目を選ぶ。

重複を許すモードでは、使用済みによる除外をしない（同じ枠の中で候補が重ならないことだけを保証する）。
重複禁止モードの使用済み情報（`UsedByRank`: 序列ごとの id 集合）は呼び出し側の `Song` が管理し、フレーズ間で共有する。

## 曲のモデル（song.py）
```
Song:   title, allow_duplicates, phrases, groups, next_phrase_id, next_group_id
Phrase: id, text, channel, locked, group_id, combinations, selected
Group:  id, name
Slot:   start, end, text, candidates, selected, manual（segmenter.py。result が選択中のポケモン）
```
- フレーズとグループは固定の ID で扱う。合体・分割・削除で位置が変わっても ID は変わらない（合体は先頭の ID、分割は前半が元の ID を使う）。
  表示上の番号と ID の変換は cli.py が行う。
- グループのメンバーは `Phrase.group_id` だけに持たせる（所属を1か所で管理し、合体・分割で更新しやすくするため）。
- 変換はすべて `Song._convert_targets` を通る。重複禁止モードでは、チャンネルごとに `UsedByRank` を持つ。
  まず対象外のフレーズの候補と手入力を入れ、それから対象を歌詞の順に `Converter.convert` で変換して積み上げる。

## 曲の JSON 形式（song_json.py）
```json
{
  "version": 2, "title": "...", "allow_duplicates": false,
  "next_phrase_id": 3, "next_group_id": 2,
  "groups": [{"id": 1, "name": "サビ"}],
  "phrases": [{
    "id": 1, "text": "たどりつくばしょ", "channel": 1, "locked": false, "group_id": 1, "selected": 0,
    "combinations": [{
      "score": 0,
      "slots": [{"start": 0, "end": 4, "text": "たどりつ", "selected": 0, "manual": null,
                 "candidates": [{"id": 451, "name": "スコルピ", "reading": "すこるぴ", "score": 0}]}]
    }]
  }]
}
```
- 候補のポケモン情報は JSON の中だけで完結する形にしてあり、読み込むときにポケモン一覧を必要としない。
- version 1（ID・チャンネル・ロック・グループ・手入力なし）も読み込める。ID は順番に振り、チャンネルは 1 にする。
