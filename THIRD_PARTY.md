# 依存OSS・参考資料

このリポジトリは以下のライブラリを依存パッケージとして使用します。ソースや仮想環境そのものは同梱していません。
各依存ライブラリの利用・再配布条件は、それぞれのライセンスを参照してください。

- [HighwayEnv](https://github.com/Farama-Foundation/HighwayEnv): MIT。運転シミュレーション。
- [Gymnasium](https://github.com/Farama-Foundation/Gymnasium): MIT。環境インターフェース。
- [pygame-ce](https://github.com/pygame-community/pygame-ce): LGPL-2.1。GUI・描画。
- [python-shogi](https://github.com/gunyarakun/python-shogi): GPL-3.0。将棋の合法手生成・盤面管理。
- [Requests](https://github.com/psf/requests): Apache-2.0。HTTP通信。
- [NumPy](https://github.com/numpy/numpy): BSD-3-Clause。運転制御の数値配列。
- [Pillow](https://github.com/python-pillow/Pillow): HPND。画像の読み込み・特徴抽出用の縮小。

画像検品は [MVTec AD](https://www.mvtec.com/research-teaching/datasets/mvtec-ad) のボトル画像を使用します。
提供元はMVTec Software GmbH、データはCC BY-NC-SA 4.0（非商用）。画像は本リポジトリには同梱せず、
固定したHugging Faceミラーからローカルに取得します。詳細は [docs/VISION.md](docs/VISION.md)。

将棋の候補に王手・詰み・駒交換の補助情報を付ける方針は、
[mizchi/jev-playground のチェス実験](https://github.com/mizchi/jev-playground/blob/research/docs/03-chess.md)
を参考にしています。本実装は将棋の持ち駒・成駒の価値を含む独自の簡易計算です。

Jev API: [TypeSafe AI](https://typesafe.ai/) / [ドキュメント](https://docs.typesafe.ai/)。
モデルのアクセス権・利用料金・利用条件は提供元に従います。
