# Windows Portable 正式出荷・14日予測Pipeline 接続結果

判定日: 2026-10-01。対象branch: `codex/portable-forecast-pipeline`。

## ゴール

承認済みInventory Snapshotを起点に、同じPilot Scopeの正式出荷実績を日次状態へ凍結し、JAN・倉庫identity bridgeを明示確認して、予測可能な商品だけを14日Baseline参考予測まで接続する。

## 完成した操作フロー

1. 在庫・出荷ZIPを分析し、確認対象を担当者が確定する。
2. 最新在庫を正式取込候補へ変換し、倉庫ごとに10〜20 JANを選ぶ。
3. Unified Inbox、既存Worker、数量照合を通し、Snapshotを明示承認する。
4. 画面に表示された`JAN → 商品ID`、`正式倉庫コード → 予測center`を確認する。
5. 日次出荷CSVが存在し、対象JAN行がない日の出荷0 policyを明示確認する。
6. 原本ZIPと担当者判断後集計のSHA-256を再検証し、最大365日の出荷を日次化する。
7. 28日以上の有効履歴と直近7日の完全性を満たす商品だけ14日予測する。
8. 予測対象外商品は、履歴不足または直近日欠測の理由を画面へ残す。

## データ契約

- `OBSERVED`: 有効な原本出荷行から集計した数量。
- `CONFIRMED_ZERO`: 日次CSVの存在と担当者が確認したpolicyに基づく0箱。
- `MISSING`: 元の日次CSVが存在しない、または0 policyが未確認。
- `PARTIAL_OR_INVALID`: 対象JANの不正行、または必要列がない出荷ファイル。

`MISSING`と`PARTIAL_OR_INVALID`は0へ変換しない。不正行がある商品だけを対象外にし、条件を満たす他商品は止めない。

## モジュール構成

- `portable/api/formal_shipment_daily.py`: 原本完全性、日次状態、商品別予測可否、内容ハッシュ。
- `portable/api/formal_forecast_pipeline.py`: 在庫承認、identity bridge、日次build、Provider実行、監査成果物の編成。
- `portable/api/formal_forecast_routes.py`: 準備状態、実行、結果取得のHTTP境界。
- `portable/api/forecast.py`: 既存Provider adapterへ任意horizonとdataset識別子を追加。
- `portable/api/static/inventory.js`: 条件確認、実行、対象外理由、結果表示。

既存の大きなAPIファイルにはroute登録だけを追加した。

## 保存先と再現性

- identity bridge: `Data/State/formal-pipeline.sqlite3`
- 日次build: `Data/FormalForecast/<build_id>/daily.csv`
- 予測結果: `Data/FormalForecast/<build_id>/predictions.json`
- 監査manifest: `Data/FormalForecast/<build_id>/manifest.json`

build IDは、承認済み在庫登録、原本ZIP、確認後集計、identity bridge、0 policy、全日次状態から決定する。同じ入力と判断は同じbuild ID・予測SHA-256へ収束する。保存結果は読出し時にSHA-256を再検証する。

## 検証結果

- 10商品×35日を日次buildし、既存Baseline Providerで14日×10商品=140点を生成した。
- 再起動後に同じ結果を読み、再実行が同じbuild IDと予測SHA-256になることを確認した。
- 直近日の1商品に不正数量を入れ、当該商品を0にせず対象外にし、残り9商品126点だけを生成した。
- identity確認または出荷0 policy確認がない要求を拒否した。
- 結果ファイル改変後のダウンロードを拒否した。

## 制約と次工程

この機能はWindows Portable試験運用のローカル参考予測である。Production側の`DailyProcessor`、Forecast run queue、複数OSS比較、補充推奨、正式出荷指示は更新しない。次工程では、現場の実データで対象外理由と操作性を確認し、承認済みPortable buildをProductionの日次Snapshot・Forecast runへ移送する境界を設計する。
