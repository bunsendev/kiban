# Phase 2I ローカルデータ検証UI

## 目的

管理対象入力rootへ配置したCSVを、登録済みの不変な列mappingで検査する要求を`/ui/intake`から登録できるようにする。HTTP request内ではCSVを開かず、独立WorkerがPhase 2Gと同じクレンジング・数量照合規則を実行する。

この検査は原本取込、archive、正規化行、業務承認を作成しない。合格しても実データ受入や予測精度を保証しない。

## 構成

- `mapping_dry_run_jobs`: `QUEUED`、`RUNNING`、`SUCCEEDED`、`FAILED`を保持する追記型の実行台帳。相対path、mapping ID、登録者、行上限、時刻、証跡IDだけを保持する。
- `kiban-mapping-dry-run-worker`: PostgreSQLからjobをclaimし、入力rootをread-onlyで参照して証跡rootへ内容アドレス方式JSONを保存する。
- `POST /api/mapping-dry-run-jobs`: `ANALYZE`権限でjobを登録する。登録済みmapping以外は受け付けない。
- `GET /api/mapping-dry-run-jobs`、`GET /api/mapping-dry-run-jobs/{job_id}`: `READ`権限で状態と証跡参照を返す。
- `/ui/intake`: 相対path、登録済みmapping、1〜10,000のsample行上限を指定し、job状態と既存の検証済み証跡を分けて表示する。

入力不備はWorker異常にしない。安全でないpath、未存在file、size、文字コード、ヘッダー、必須列、CSV構造、数量照合の不備は`BLOCKED`証跡になる。予期しない実行障害だけを固定`error_code`で`FAILED`にし、例外本文をAPIへ返さない。

## ローカル実行

1. CSVを`KIBAN_IMPORT_DIR`で指定した入力rootへ配置する。既定はrepository直下の`import_input`。
2. `docker compose --profile worker up -d --build api mapping-dry-run-worker`を実行する。
3. `http://127.0.0.1:58000/ui/intake`へ接続し、必要なら先に列mappingを登録する。
4. 「00 ローカルデータ検証jobを登録」で入力rootからの相対path、mapping、sample行上限を指定する。
5. 「検証job」で完了状態を確認し、「ドライラン」で`READY_FOR_NORMALIZATION`、`REVIEW_REQUIRED`、`BLOCKED`と各検査結果を確認する。

Workerの入力mountはread-only、証跡mountだけがwrite可能である。APIは証跡mountをread-onlyで参照し、返却時にchecksumと固定schemaを再検証する。APIとWorkerが同時に初回起動しても、PostgreSQL schema初期化はadvisory lockで直列化する。

## 残る受入作業

実業務CSVによるmapping確認、サンプル外を含む全行正規化、全件数量照合、隔離理由の業務判断は未実施である。ドライラン確認後はPhase 1Xの取込・正規化へ進む。
