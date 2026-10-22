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
combo 3 2         # フレーズ3の組合わせ候補2を選択
pick 3 2 1        # フレーズ3の枠2の候補1を選択
manual 3 1 ピカチュウ  # フレーズ3の枠1にポケモンを手入力
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
