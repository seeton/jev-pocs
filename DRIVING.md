# Jev × HighwayEnv — ハンドルと加減速のリアルタイム実験

既存OSSの [HighwayEnv](https://github.com/Farama-Foundation/HighwayEnv) を使います。
自車のハンドル角と加速度をJevが選びます。人が質問やJSONを入力する必要はありません。

## 起動

```powershell
.\drive.cmd
```

登録済みの暗号化キーを使い、2Dの運転画面を一時停止状態で開きます。
Spaceで開始・一時停止・再開、Escまたは閉じるボタンで終了します。
終了条件に達したら画面は結果を表示したまま止まり、API呼び出しも止まります。
もう一度走らせるときは閉じて再実行してください。

既定では最大60秒またはAPI呼び出し60回、衝突・道路外への逸脱で終了します。
実行にはAPI利用量が発生します。停止時に通信中だった1件は完了する場合があります。

```powershell
# 短い実験
.\drive.cmd --duration 15 --max-calls 20

# 異なる交通配置で試す
.\drive.cmd --seed 12

# 比較用の単純なローカル制御（APIを使わない）
.\drive.cmd --controller baseline

# 描画ウィンドウを出さずに計測
.\drive.cmd --headless --duration 15 --max-calls 20
```

## 何をJevが操作するか

- ハンドル角：-0.06、-0.02、-0.006、0、+0.006、+0.02、+0.06 rad の7択。
- 加速度：-6、-3、-1、0、+1.5、+3 m/s² の6択。
- 正のハンドル角は画面の下方向（右車線）、負は上方向（左車線）。
- 選択肢をそのままHighwayEnvの `ContinuousAction` に変換します。レーン追従やPIDによる補正はありません。
- 周囲の車両はHighwayEnv標準の交通モデルで動きます。

Jevのchoiceで角度と加速度を離散的に選ぶため、任意の実数を直接出す方式ではありません。
1回のプロンプト調整後は中央車線の維持を目標とし、追い越しは指示していません。
比較結果は [POC-1-RESULTS.md](POC-1-RESULTS.md) に記録しています。
物理更新は30Hz。APIの要求開始間隔は最短0.25秒、同時要求は1件までです。
実際の判断頻度はAPI往復時間に制限されます。

## 渡す情報

自車の位置・速度・車体の向き・現在のハンドル角と加速度、各車線の前後車両との距離・相対速度です。
カメラ画像は使わず、シミュレーターから得られる正確な数値を使います。
Jevへの指示と選択肢は `driving.py` の `Jev.decide()` にあります。

## 遅延の扱いと画面表示

API呼び出しは別スレッドで行い、通信中もシミュレーションと描画は進みます。
次の応答が届くまで、直前のハンドル角と加速度を保持します。
1.5秒以上古い判断は破棄します。破棄しても自動ブレーキ・ハンドル補正は入りません。
`--max-age`、`--interval` で変更できます。

- **API**：HTTP要求開始から応答の解析までの往復時間。モデル単体の推論時間ではありません。
- **Decision age**：要求を送ってから、結果を制御ループで受け取るまでの時間。
- **Simulation / Wall**：シミュレーション時間と一時停止を除いた実経過時間。PCが重い場合の遅れを確認できます。
- **Confidence**：ハンドル・加速度の回答confidenceの小さい方。運転の安全確率ではありません。
- **Applied / Discarded**：受理・破棄した判断の件数。

認証・課金・レート制限などのHTTPエラー、または合計3回の通信・応答エラーで終了します。
ネットワーク越しの直接ハンドル制御なので、蛇行・逸脱・衝突も実験結果として扱います。

既定の開始位置は中央車線の中心から右へ0.65m、車体の向きは右へ0.03radずらしています。
直進だけで済まず、ハンドルを戻す判断を観察できる初期条件です。
まっすぐ中央から開始したい場合は `--offset 0 --heading 0` を付けてください。

## 記録

終了後、`runs/日時/summary.json` に走行距離、衝突有無、API往復の平均・p95、トークン使用量を保存します。
`decisions.jsonl` には各判断の入力、出力、経過時間を保存します。キーやHTTPヘッダーは保存しません。
画面が止まった後、Escで閉じるとサマリーの保存が完了します。

```powershell
.\drive.cmd --headless --duration 10 --screenshot runs\drive.png
```

## 環境を作り直す場合

Python 3.12を用意し、プロジェクト内で以下を実行します。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-drive.txt
.\.venv\Scripts\python.exe -m unittest test_driving.py
```

このPCでは `.venv` を作成済みです。依存関係の記録は `requirements-drive-lock.txt` にあります。

参考：
- https://highway-env.farama.org/actions/
- https://highway-env.farama.org/quickstart/
