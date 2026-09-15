# Phase 2U 在庫全件正規化ジョブ

## 目的

Phase 2Tで事前検査した在庫CSVを全件処理し、予測データ準備で参照できる日次在庫数量へ変換する。出荷正規化行とは意味が異なるため、既存の出荷台帳へ混在させず、専用台帳へ保存する。

## 操作フロー

1. `/ui/intake`でZIPをアップロードする。
2. JAN記入用CSVをダウンロードし、全商品のJANを確認して再アップロードする。
3. 固定単位を指定して在庫正規化プレビューを実行する。
4. 判定が`READY_FOR_INVENTORY_NORMALIZATION`の場合に「全在庫データを正規化」を押す。
5. 画面で処理済みファイル数、採用行数、隔離行数、最終状態を確認する。

APIは`POST /api/inventory-normalization-jobs`でジョブを登録し、`GET /api/inventory-normalization-jobs/{job_id}`で進捗を返す。登録にはANALYZE、参照にはREAD権限が必要である。

## Workerと保存形式

`kiban-inventory-normalization-worker`はQUEUEDジョブを取得し、対象prefix内でファイル名に「在庫」を含むCSVを全件処理する。複数WorkerではPostgreSQLの`FOR UPDATE SKIP LOCKED`を使い、同じジョブの二重取得を防ぐ。

採用行は次のキーで数量を合算し、`inventory_daily_quantities`へ保存する。

- ファイル名から取得した在庫日
- 検証済み対応表から取得したJAN
- 明細倉庫コード
- 担当者が指定した固定単位

ジョブ状態、ファイル進捗、採用・隔離件数、固定理由別件数は`inventory_normalization_jobs`へ保存する。商品名、商品コード、JAN、数量などの原値はジョブ応答やログへ出力しない。

## 検査と失敗条件

行単位では日付不正、商品未対応、倉庫欠損、数量不正を隔離する。日付は`YYYYMMDD`の見た目だけでなく実在する暦日として検査し、数量は有限かつ0以上に限定する。

対象在庫CSVがない、文字コードを判定できない、必須列がない、対応表を読めない場合は、欠落した数量を正常結果として扱わずジョブ全体を`FAILED`にする。応答には固定エラーコードだけを保存する。

## 実行

開発Composeではworker profileに専用Workerを追加した。入力領域はread-onlyでmountする。

```powershell
docker compose --profile worker up -d --build
```

実業務データの全件実行には、Phase 2Sで全143商品の確認済みJAN対応表を作る必要がある。本実装の自動試験は人工データによる機能確認であり、実データの数量照合や予測精度を保証しない。
