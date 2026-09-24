# Phase 3S-3 実装・監査結果

実施日: 2026-09-24
対象Repository: `bunsendev/kiban`
基準Branch / Commit: `main` / `25bdad7`

## 1. Branch / Commit

- 実装Branch: `codex/phase3s3-snapshot-worker`
- 初期実装Commit: `66d3ae3`
- 監査修正Commit: `74db752`
- PR: `#87`（初期実装`#86`のマージ後監査差分）

## 2. 実装概要

Phase 3S-2のCSV validationを、追記型job台帳、独立Worker、SQLite / PostgreSQL
storeへ接続した。監査では既存実装を再利用し、`known_at`、業務承認の責務分離、read
model、実PostgreSQL検証に必要な差分だけを追加した。

```text
immutable CSV reference + SHA-256 + mapping version + known_at
  -> content-addressed job
  -> lease付きWorker
  -> CSV parse / reference resolution / strict validation
  -> 1 transaction
     snapshot + expiry buckets + quarantine + reconciliation + job完了
  -> review可能なsnapshot
  -> 追記型APPROVED / REJECTED decision
```

原本byte、実データ、raw row、ローカルpath、資格情報はRepositoryへ追加していない。

## 3. Service

- job IDをsource reference、source SHA-256、mapping version、明示された`known_at`から生成する。
- Worker処理時刻を`known_at`へ上書きしない。
- Phase 3S-2の厳格validationが採用可能な場合だけsnapshotを組み立てる。
- quarantine、数量不一致、bucketなしの場合はsnapshotを作らず、固定理由のsystem
  `REJECTED`を作る。
- 技術的に正常なsnapshot生成時は業務`APPROVED`を自動作成しない。
- JAN、canonical product ID、location、location type、expiry、CASE数量、各versionを既存domainへ渡す。

## 4. Store

SQLite / PostgreSQLで共通の業務契約を使用する。保存対象は次のとおり。

- job、lease、attempt、heartbeat、固定error code
- snapshot header、EXPIRY_BUCKET
- quarantine、reconciliation
- 追記型decision
- job別snapshot一覧
- JAN × location × expiry昇順のread model。location codeと`FACTORY / WAREHOUSE`を返す。

業務判断は`append_snapshot_decision`で技術生成済みsnapshotへ追記する。同一内容の再送は
同じdecision IDへ収束し、過去判断を更新しない。

## 5. Worker

Workerはjob取得、原本読取、heartbeat、参照version取得、Service呼出、成功・失敗記録に限定した。
JAN正規化、賞味期限、CASE変換、snapshot決定性は既存domain / validationを再利用する。

- source root外の参照、絶対path、`..`、size上限超過を拒否する。
- 読取後にSHA-256を再照合する。
- 内部障害は最大3 attemptまで再試行する。
- 失敗記録へraw row、原本byte、OS例外本文を保存しない。
- 独立processはSQLite / PostgreSQL、1回実行 / 常駐実行を選択できる。

## 6. Transaction設計

finalizeは次を同じDB transactionで処理する。

1. job ID、attempt、worker ID、lease token、lease期限を再検証する。
2. 採用可能な場合はsnapshot headerと全expiry bucketを保存する。
3. quarantineの行番号、行hash、固定reasonを保存する。
4. source数量、normalized数量、一致結果を保存する。
5. validation不採用時だけsystem `REJECTED`を保存する。
6. jobを`SUCCEEDED`へ変更し、active leaseを解除する。

途中失敗ではtransaction全体をrollbackする。headerだけ、bucketの一部だけ、decisionだけを
利用可能状態にしないことを人工障害試験で確認した。

## 7. Job lifecycle

状態は既存schemaの`QUEUED / RUNNING / SUCCEEDED / FAILED`を維持した。

- `QUEUED`: 未取得または再試行待ち
- `RUNNING`: worker、lease token、期限を持つ
- `SUCCEEDED`かつsnapshotあり・decisionなし: 技術生成済み、レビュー可能
- `SUCCEEDED`かつsystem `REJECTED`: validation不採用、正式snapshotなし
- `FAILED`: source、CSV全体契約、mappingまたはretry上限の障害

期限切れleaseは別Workerが再取得できる。旧Workerはattemptとtokenによるfencingでheartbeat、
完了、失敗を記録できない。

## 8. Idempotency

- 同じjob登録は同じjob IDへ収束する。
- 完了済みjobは再claimされない。
- snapshot ID、content SHA-256、bucket主キーは既存canonical contractで決定する。
- 再登録・retryで数量、bucket、snapshotを重複させない。
- 同一業務decisionの再送は同じdecision IDへ収束する。

同一jobの再実行後もsnapshot 1件、bucket 1件、数量8 CASEのままであることを試験した。

## 9. Snapshot決定性

決定性の入力はsource、mapping、location master、product mapping、`snapshot_at`、
`known_at`、canonical inventory rowsである。`created_at`、Worker ID、attempt、処理完了時刻は
content hashへ含めない。

明示された`known_at`をjobへ保存し、snapshotへそのまま渡す。同じcanonical inputを
SQLite / PostgreSQLへ投入し、同じsnapshot IDとcontent SHA-256になることを実DBで確認した。

## 10. SQLite結果

PASS。人工fixtureで次を確認した。

- CSV -> validation -> job -> Worker -> snapshot -> expiry bucket E2E
- FACTORY、WAREHOUSE A、WAREHOUSE Bを別locationとして保持
- 同一JAN・同一WAREHOUSEの複数賞味期限を別bucketとして保持
- expiry昇順read
- canonical product IDとproduct mapping versionの保持
- 技術生成と業務APPROVEDの分離
- quarantine時のsnapshot非生成
- fail-then-success retry、3回上限、heartbeat、stale Worker fencing
- 2 Worker同時claimで取得1件
- transaction rollback、完了job再実行の冪等性
- 既存SQLite jobの`known_at` backfillを含む非破壊migration

## 11. PostgreSQL結果

PASS。WindowsからWSL上の実PostgreSQL 18.6へ接続し、skipせず検証した。

- schema / migration / advisory lock
- `FOR UPDATE SKIP LOCKED`による2 Worker競合
- lease、heartbeat、retry、fencing、transaction、unique constraint
- Worker E2E
- SQLiteとのsnapshot ID / content SHA-256一致

Phase 3S-1〜3S-3対象はPostgreSQL実接続を含め`57 passed`。本番標準のPostgreSQL 17でも
同じ対象試験をCIまたは復旧後のDocker環境で継続確認する。

## 12. E2E結果

PASS。人工CSVだけを使用し、CSV原本参照とSHA-256からjob登録、Worker処理、厳格validation、
snapshot、FACTORY / WAREHOUSE別expiry bucket、数量照合、review可能状態、追記型APPROVEDまで確認した。

## 13. Regression結果

PASS。Windows非対応のLinux専用peak RSS 1件を除く全回帰は`624 passed / 16 skipped /
1 deselected`。ruff、既存lint、release preflightも成功した。Phase 3S-1 / 3S-2、
Forecast Provider、既存APIの契約変更は検出されなかった。16 skipはDSNなしの通常回帰で
既存の任意PostgreSQL試験を分離した結果であり、Phase 3S-3 PostgreSQL対象3件は別途実接続で成功した。

## 14. 既存機能への影響

- `inventory_snapshot_jobs`へ`known_at`を追加した。既存行は`requested_at`からbackfillする。
- 既存lease列とquarantine reason migrationを維持した。
- job登録関数は`known_at`の明示を必須にした。Phase 3S-3外の呼出元は存在しない。
- 既存の在庫正規化、予測、比較、API、UI、既存Workerは変更していない。
- `inventory_daily_quantities`を変更していない。

## 15. 未実装

指示どおり次は実装していない。

- Phase 3S-4本格API、担当者UI、role / permission / API監査event
- PDF parser、OCR、LLM抽出
- 生産予定、需要予測、将来在庫Projection、arrival-time inventory
- FEFO消費計算、Risk Engine、Shipment Recommendation、日次Scheduler、自動出荷
- source archive登録との自動接続、本番商品mapping provider、実業務CSV preflight

## 16. 技術的懸念

- Docker DesktopはWindowsのstale `sailor-ingest.sock`によりLinux Engineを起動できない。
  Phase 3S-3試験はWSL PostgreSQLで完了したが、Docker復旧にはWindows再起動後の再確認が必要。
- 今回の実DBはPostgreSQL 18.6。本番標準の17でも対象suiteを継続実行する。
- migrated SQLite tableではSQLite制約の制限により`known_at NOT NULL`をdomain/storeでも保証する。
- APPROVED / REJECTEDの最新判断をどう解釈するかはPhase 3S-4 API契約で固定する。

## 17. Phase 3S-4への引継ぎ

次工程は既存認証・認可・監査契約を再利用し、次のread / command APIを小さく追加する。

1. source参照、SHA-256、mapping version、known_atを指定するjob登録
2. job状態、attempt、件数、固定error codeの参照
3. quarantine reason集計とreconciliation参照
4. review可能snapshot一覧と追記型APPROVED / REJECTED
5. JAN × location × expiry_date ASCのFEFO入力read model
6. READ / ANALYZE / APPROVE権限と監査event

API応答へraw row、原本byte、path、DSN、例外本文を出さない。Phase 3Tは承認済みsnapshotの
expiry昇順read modelを入力にし、今回の`known_at`を用いてdata leakageを防ぐ。
