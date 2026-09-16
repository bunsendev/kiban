# Phase 2Z 在庫特徴CSVの発行台帳と改ざん検知

## 目的

Phase 2Yの在庫特徴CSVについて、誰が・いつ・どの条件で発行したかを不変台帳へ保存し、後続処理が固定された発行IDを参照できるようにする。再取得時は元条件からCSVを再生成し、台帳checksumと照合する。

## 発行台帳

`inventory_feature_exports`は次を保存する。

- 内容アドレス方式の発行ID
- 特徴ビューID
- JAN名寄せ版
- UTC参照時点
- CSV bytesのSHA-256
- 行数
- 認証された発行者
- 発行時刻

発行IDは`inventory-feature-<content_sha256>`とする。同じ条件・同じ内容の再発行は同じIDへ収束し、最初の発行記録を変更しない。

## API

- `POST /api/inventory-feature-exports`: ANALYZE権限。Phase 2X/2Yの検査とCSV生成を行い、発行記録を保存する。
- `GET /api/inventory-feature-exports`: READ権限。発行履歴を新しい順に返す。
- `GET /api/inventory-feature-exports/{export_id}`: EXPORT権限。台帳条件からCSVを再生成し、特徴ビューIDとchecksumを再検証して返す。

再生成したビューIDまたはchecksumが台帳と一致しない場合は409で停止し、CSVを返さない。存在しない発行IDは404とする。

## 画面

`/ui/intake`ではREADYの特徴ビューに対し「在庫特徴CSVを発行・ダウンロード」を表示する。発行後は内容アドレス方式の発行IDとSHA-256を表示し、発行IDを使う再取得endpointからCSVを取得する。

## データ保護と範囲

発行台帳は系譜とchecksumだけを保持し、CSV本文や原JANを重複保存しない。実データ、資格情報、CSV本文はGitと配布ZIPへ含めない。本機能は分析成果物の管理であり、予測datasetへの自動結合や本番システムへの書戻しを行わない。
