# 環境構築・開発手順

## 環境
- Python 3.11（`.venv` の仮想環境）
- 外部ライブラリ: pytest のみ（`requirements.txt`）

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## ポケモン一覧の生成
`data/raw/pokeapi/pokemon-species/*.json` から `data/pokemon.json` を生成する。
生データは容量が大きい（約300MB）ためリポジトリに含めていない（.gitignore で除外）。
生成済みの `data/pokemon.json` はリポジトリに含まれているので、アプリを動かすだけなら生成は不要。

```powershell
.venv\Scripts\python.exe scripts\build_pokemon_list.py
```

記号などで読みに変換できない名前があるとエラーで止まる。その場合は `data/reading_overrides.json` に読みを追加する。

## コンソールアプリの実行
```powershell
.venv\Scripts\python.exe main.py
```

操作例:
```
add あらたな ひかりを たどりつくばしょ
conv all          # 全フレーズを変換
show 3            # フレーズ3の候補を表示
sel 3 1 1 1       # フレーズ3の 組合わせ1・枠1・候補1 を選択情報に追加
sel 3 2 2 3       # 続けて 組合わせ2・枠2・候補3 を追加（組合わせや枠をまたいでよい）
swap 3 1 2 1 2    # 選択情報の1番目を 組合わせ2・枠1・候補2 と入れ替え
manual 3 ピカチュウ    # 選択情報の末尾に手入力で追加（manual 3 ピカチュウ 2 なら2番目を入れ替え）
unsel 3 2         # 選択情報の2番目を削除（unsel 3 all で全消去）
edit 2 ひかりをー  # フレーズ2を変更（候補・選択情報・省略しない設定はリセット）
fix 1 4           # フレーズ1の4文字目（ー・っ）を「省略しない」に（unfix 1 4 / unfix 1 all で解除）
mode              # 重複OK / 重複NG を切り替え（反映は conv all で）
merge 1 2         # 連続したフレーズ1と2を合体
split 1 4         # フレーズ1を先頭から4文字目の後ろで2つに分割
group 1 2 サビ    # フレーズ1と2をグループ「サビ」(g1) にする
channel g1 2      # g1 のメンバーの重複チャンネルを2に
conv g1           # g1 のメンバーだけ変換
lock g1           # g1 のメンバーをロック（unlock で解除）
ungroup g1        # グループを解除
save              # data/songs/<曲名>.json に保存
load data\songs\song.json
```
フレーズは表示順の番号（1から）、グループは `g<番号>` で指定する。
`help` でコマンドの一覧を表示する。

## テスト
```powershell
.venv\Scripts\python.exe -m pytest
```

## 一致度の調整
`data/tuning_examples.json` に正解例（フレーズ → ほしいポケモンの並び）を書き、評価スクリプトで結果を確認する。

```powershell
.venv\Scripts\python.exe scripts\evaluate_scoring.py
.venv\Scripts\python.exe scripts\evaluate_scoring.py --vowel-weight 3 --consonant-weight 1 --penalty 1.5 --dropped 2 `
    --weak-threshold 0.65 --weak-penalty 1 --long-vowel-penalty 0.5
```

例ごとに上位の組合わせ候補と、正解の並びが「出た / 候補内 / 出ない」のどれだったかを表示する。
出なかった並びは、その並びで区切ったときの一致度も表示する。よい値が見つかったら `scoring.ScoringParams` の既定値に反映する。
