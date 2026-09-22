# Jev PoCs — 運転・自動戦闘・将棋・検品

TypeSafe AI の Jev を、会話ではなくアプリの行動選択に使う個人実験です。
数値や文字で表した状態と選択肢を渡し、ローカルのゲームが選択結果を実行します。
Windows / Python 3.12 向け。TypeSafe AI の公式プロジェクトではありません。

| PoC | 起動 | 内容 |
|---|---|---|
| 運転 | `drive.cmd` | HighwayEnvでハンドルと加減速を選択。Spaceで開始 |
| 自動戦闘 | `compare.cmd` | Jevと全スキル対応ルールAIを同条件比較。ボタンで実行・再生 |
| 将棋 | `shogi.cmd` | 人間対Jev。盤面クリック、持ち駒、成り、待ったに対応 |
| 模擬検品 | `inspection.cmd` | 製品を良品・不良品・要確認へ仕分け。固定ルールと比較 |
| 画像検品 | `vision.cmd` | 実画像のローカル異常検知とJevの仕分け。正解領域を比較 |
| API入門 | `jev.cmd` | 問い合わせ文をchoice / noul / scoreで判定 |

## フォルダー構成

```text
pocs/
  driving/       運転アプリ・診断ツール
  battle/        自動戦闘・比較・ルールAI
  shogi/         将棋アプリ・戦術情報の計算
  inspection/    模擬検品ライン・規格判定
  vision/        実画像の異常検知・評価・表示
  common/        共通のボタン描画・保存先パス
scripts/         PowerShell起動・キー管理
requirements/    PoC別の依存パッケージ
tests/          オフラインテスト
docs/           各PoCの説明と実験レポート
examples/       APIリクエストの例
results/        公開用の実験記録・棋譜
```

ルートの `.cmd` がWindows向けの入口です。Pythonは `python -m pocs.shogi.app` のようにモジュールとして起動します。
ローカル生成物は引き続きルートの `runs/` に保存するため、既存の棋譜やリプレイも利用できます。

## セットアップ

Python 3.12をインストールし、このフォルダーで実行します。

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\jev.cmd -ConfigureKey
.\jev.cmd -Check
.\compare.cmd
```

GUIには日本語フォントを使います。Windows PowerShell 5.1用の起動スクリプトが付属しています。
起動コマンドは以下の各ドキュメントを参照してください。

## 実験で分かったこと

- 運転：過剰な減速はプロンプト調整で軽減したものの、車線維持は不安定でした。
- 戦闘：90秒の1戦で双方4人生存。ボス残HPはJev 778、ルールAI 454でした。
- 将棋：合法手選択は動きますが棋力は未検証です。王手・詰み・簡易的な駒交換の損得を候補に添えています。

いずれも探索的なPoCで、モデルの一般的な性能や優劣を示すベンチマークではありません。
API往復時間にはネットワーク遅延を含みます。将棋の `jev-preview` は実験時点で `jev-1.13.0` に解決されました。
詳細は [運転結果](docs/POC-1-RESULTS.md)、[自動戦闘](docs/BATTLE.md)、[将棋](docs/SHOGI.md) を参照してください。
模擬検品の使い方・評価条件は [INSPECTION.md](docs/INSPECTION.md) を参照してください。
実画像版は [VISION.md](docs/VISION.md)。MVTec ADの非商用データをローカルにダウンロードします。

将棋の完了した2対局を [results/shogi](results/shogi/README.md) に収録しています。
その他の `runs/` の生ログ・リプレイは公開していません。ドキュメント中の過去のログパスは実験時の参照です。
初回は比較を実行するとリプレイを利用できます。API呼び出しには利用量が発生します。

## オフラインテスト

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\jev.cmd -SelfTest
```

テストは実APIを呼びません。`shogi.cmd --smoke` は実APIで1手を確認する別の動作確認です。
依存OSSと参考資料は [THIRD_PARTY.md](THIRD_PARTY.md) に記載しています。

## API入門とキー管理

**4職の自動戦闘:** `.\battle.cmd` で開始。詳しくは [BATTLE.md](docs/BATTLE.md)。

**自動運転実験:** `.\drive.cmd` でJevにハンドル・加減速を操作させます。詳しくは [DRIVING.md](docs/DRIVING.md)。

以下のAPI入門コマンドだけなら、Pythonや追加パッケージは不要です。

## 1. APIキーを伏せ字で登録

このフォルダーでターミナルを開いて実行します。

```powershell
.\jev.cmd -ConfigureKey
```

入力欄にキーを貼り付け、Enterを押してください。入力は `*****` で表示されます。キーをチャットやコマンドの引数に書く必要はありません。

キーの発行先: https://console.typesafe.ai/settings/keys

キーは `%LOCALAPPDATA%\jev\typesafe-api-key.dpapi` に Windows DPAPI で暗号化して保存します。復号には同じWindowsユーザーの資格情報が必要です。プロジェクトに平文の `.env` は作りません。通信時だけプロセス内で復号し、公式の `api.typesafe.ai` に送信します。同じWindowsユーザーで動くプログラムからのアクセスを防ぐ保管方式ではありません。

キーの変更は同じ登録コマンドを再実行します。登録を解除するには上記の `.dpapi` ファイルを削除してください。

## 2. 接続確認

```powershell
.\jev.cmd -Check
```

`GET /v1/models` を呼び、利用できるモデルの情報を表示します。

## 3. 日本語の問い合わせを判定

```powershell
.\jev.cmd
```

`examples/support-ticket.json` を送信し、担当窓口（choice）、緊急性の確率（noul）、不満の強さ（score）をJSONで表示します。実行には有効なAPIキーとAPI利用権が必要で、API利用量が発生します。結果はモデルの推定です。

JSONの `state` を自分の文章に書き換えて試せます。別のファイルを使う場合:

```powershell
.\jev.cmd -RequestFile .\examples\support-ticket.json
```

APIを呼ばずに入力JSONを確認する場合:

```powershell
.\jev.cmd -DryRun
```

通信のタイムアウトは30秒です。自動リトライは行いません。認証エラーの場合はキーを登録し直してください。

## ローカル環境の確認

```powershell
.\jev.cmd -SelfTest
```

実際のキーを読み取らず、テスト用の文字列で暗号化・復号を検証します。`jev.cmd` は子プロセスのモジュール検索先をWindows PowerShell標準に設定し、PowerShell 7のモジュールが混入する問題を防ぎます。システム全体の設定は変更しません。

公式資料:
- https://docs.typesafe.ai/introduction/quickstart
- https://docs.typesafe.ai/api
