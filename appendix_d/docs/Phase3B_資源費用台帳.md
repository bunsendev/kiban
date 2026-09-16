# Phase 3B Provider共通の資源・費用台帳

## 目的

実装仕様書 v2.2 の14章、AC-16、AC-21に対応し、予測runの時間、CPU/GPU、最大メモリ、モデル取得、保存容量をProvider共通形式で記録する。登録済み単価から費用を計算し、単価不明を0円へ変換しない。

## 記録項目

`ResourceMetric`は次の8項目を固定する。

| metric | unit | 標準Workerでの取得 |
|---|---|---|
| `PREPROCESSING_SECONDS` | second | 固定学習共通Executorがsnapshot読込・実行準備を計測 |
| `TRAINING_SECONDS` | second | 新規fitを行った時だけ固定学習共通Executorが計測 |
| `INFERENCE_SECONDS` | second | 固定学習共通Executorが推論区間を計測。内訳を返さないExecutorはWorker全体時間を記録 |
| `CPU_SECONDS` | second | Workerがprocess CPU時間の差分を計測 |
| `GPU_SECONDS` | second | GPU対応Executorが明示的に返す。未計測はNULL |
| `PEAK_MEMORY_BYTES` | byte | Workerがprocess peak working set/RSSを計測。OSで取得不能ならNULL |
| `MODEL_DOWNLOAD_SECONDS` | second | checkpoint取得を行う専用処理が明示的に返す。実行時download禁止ProviderではNULL |
| `STORAGE_BYTES` | byte | model/context artifactのbyte数を内容識別子ごとに1回記録 |

`OriginOutput.resources`を拡張点とし、追加Providerは共通APIや比較出力へ個別分岐を足さずに詳細計測を返せる。Worker境界では全ProviderにCPU時間と取得可能なpeak memoryを加える。

## 再開と重複防止

通常の計測IDは`run_id + origin_date + attempt + metric + source`から決定する。同じ試行を再登録しても合計は増えない。artifact容量は`run_id + metric + artifact identity`から決定し、起点や再試行で同一artifactを再利用しても一度だけ数える。

成功値の確定前に計測を保存するため、Provider失敗やtimeoutで結果が残らない試行も消費資源として追跡できる。成功済み起点は従来どおり再実行されず、予測値のattempt fencingも維持する。

## 単価と費用

単価は`provider_id`、metric、unit、単価、3文字通貨コード、取得日、参照元、認証済み登録者を不変記録にする。`provider_id="*"`は共通単価で、Provider固有単価を優先する。最新取得日の単価を使用し、計測量に乗算する。

計測済み項目の単価が1件でも不明、または通貨が混在する場合は`pricing_complete=false`、`total_cost_amount=null`とする。各項目の数量は維持し、未知の費用を0円として過小表示しない。単価0は管理者が明示登録した既知の0円として区別される。

## API

- `GET /api/runs/{run_id}`: `resources`へ集計を含める。
- `GET /api/runs/{run_id}/resources`: 8項目の数量、適用単価・取得日、項目費用、総費用を返す。
- `POST /api/resource-unit-prices`: `MANAGE_RESOURCE`権限を持つADMINだけが単価を登録する。要求の`created_by`は使わず認証subjectで確定する。
- `GET /api/resource-unit-prices`: READ権限で単価履歴を参照する。

登録例:

```json
{
  "provider_id": "*",
  "metric": "CPU_SECONDS",
  "unit_price": "0.0025",
  "currency": "JPY",
  "retrieved_on": "2026-09-16",
  "source_ref": "社内計算資源単価表 2026-09"
}
```

比較CSVには8項目の計測量、`pricing_complete`、`total_cost_amount`、`cost_currency`をrun別に追加する。精度、失敗率、適合証跡、時間、費用を同じ比較行で確認できる。

専用の`GET /api/runs/{run_id}/resources`は集計に加えて`attempt_measurements`を返す。起点日、attempt、metric、数量、計測元、計測時刻を確認できるため、部分成功runで成功・失敗双方の消費資源を追跡できる。通常のrun状態応答と比較CSVは集計だけを使い、試行明細で応答を肥大化させない。

## 保存先

SQLite参照実装とPostgreSQL本番実装は次の追記専用tableを使用する。

- `resource_measurements`
- `resource_unit_prices`

計測値と単価は`Decimal`で扱い、浮動小数点への暗黙変換をしない。PostgreSQLは`NUMERIC`、SQLiteは10進文字列で保存する。時間と保存容量はrun内の計測を合計し、`PEAK_MEMORY_BYTES`だけは最大値を集計する。

## 検証範囲

自動テストは試行の冪等登録、artifact容量のrun内重複防止、Provider固有単価の優先、未知単価のNULL、Worker自動計測、ADMIN限定登録、run API、比較CSV、SQLite/PostgreSQL schemaを確認する。

人工データによる機能試験はAC-16/AC-21の実データ実施を代替しない。AC-21完了には、FULL選定版の20〜50品目を用い、対象環境の実単価を登録して複数OSSの比較CSVを発行する必要がある。GPU時間とモデル取得時間は利用する実行基盤が値を提供した場合だけ記録し、未計測はNULLのまま提出する。
