# Phase 2O ZIP一括検証

## 目的

現場担当者がZIPを一度選択し、出荷CSVの判別、検証登録、進捗確認、結果CSV取得までを
`/ui/intake`で完結できるようにする。

## 対象判別

- ZIPアップロード時の安全検査と原本保存はPhase 2Nを再利用する。
- 展開したCSVのうち、ファイル名に`出荷`を含むものを検証対象とする。
- それ以外のCSVは削除せず、対象外件数としてバッチ結果に表示する。
- 対象が0件の場合はジョブを登録しない。

## バッチ契約

`POST /api/mapping-dry-run-batches`は入力prefix、既存mapping、最大検査行数を受け取り、
対象CSVごとに既存のmappingドライランjobを同一トランザクションで登録する。検証規則と
Workerは単一CSV検証と共通である。

`GET /api/mapping-dry-run-batches/{batch_id}`はQUEUED、RUNNING、SUCCEEDED、FAILEDと、
READY_FOR_NORMALIZATION、REVIEW_REQUIRED、BLOCKEDを集計する。全ジョブ終了後は
`COMPLETED`となる。

`GET /api/mapping-dry-run-batches/{batch_id}/results.csv`はUTF-8 BOM付きCSVを返す。
CSVには相対path、実行状態、判定、固定エラーcode、証跡checksumだけを含め、原値は含めない。

## 制約

ファイル分類は現場データの命名規則に基づく。在庫CSV用mappingと在庫分析は別工程で定義する。
一括検証はサンプル行によるクレンジング・mapping事前判定であり、全行正規化や実データ受入を
完了させるものではない。
