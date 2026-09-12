# Phase 2B 実装計画

## ゴール

TimesFM 2.5専用Workerを本番候補環境へ置く前に、固定checkpoint、resource隔離、初期化・推論時間、process peak RSSを同じ条件で検証し、機械可読な不変レポートを残せるようにする。

## 実装範囲

1. 固定SHA-256とsizeのローカルcheckpointを計測開始前に完全検証する。
2. 3系列、context 512日、horizon 15の人工データを既定負荷とし、モデル初期化、warm-up 1回、計測3回を分離する。
3. wall time、CPU time、process peak RSS、実行環境、cgroup CPU・memory上限をJSONへ記録する。
4. 入力契約、process計測、環境取得、実行、判定、内容アドレス保存、CLIを別moduleにする。
5. CPU 2、memory 4 GiB、初期化・予測各600秒を`cpu-timesfm`技術プロファイルとしてComposeへ固定する。
6. benchmark serviceはnetworkを無効化し、checkpointをread-only、レポート領域だけをwrite可能にする。
7. 仕様、テスト、wheel、配布checksum、日本語PRを更新する。

## 完了条件

- checkpoint改変または欠落時はモデルロード前に停止する。
- API imageへPyTorch、checkpoint、ベンチマーク出力を追加しない。
- モデル初期化、warm-up、計測runが混同されず、予測値とローカルpathをレポートへ保存しない。
- checkpointが実行processからwrite不可で、cgroupの実上限がプロファイル以下である場合だけ隔離チェックを通す。
- 同じ内容のレポートは同じSHA-256 URIへ保存し、既存内容を上書きしない。
- 公式checkpointを使うDocker計測、pytest、ruff、Compose、wheel、配布checksumが成功する。
- 人工データの処理時間を実データ精度、本番SLA、業務効果として扱わない。
