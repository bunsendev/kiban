# Phase 3S-3 実装結果

実施日: 2026-09-24  
対象Repository: `bunsendev/kiban`  
基準Branch: `main`  
基準Commit: `25bdad7`  
実装Branch: `codex/phase3s3-snapshot-worker`

## 1. 完成した範囲

Phase 3S-2のCSV adapter / validationを、追記型job台帳、SQLite / PostgreSQL store、独立Workerへ接続した。

```text
immutable CSV reference + SHA-256 + mapping version
  ↓ content-addressed job
lease付き独立Worker
  ↓ source hash再検証
CSV parse / reference resolution / validation
  ↓ 同一transaction
quarantine + reconciliation
  + APPROVED snapshot / REJECTED decision
  + job SUCCEEDED
```

CSV契約不成立、原本hash不一致、参照不能、内部障害は入力の業務判定と分け、jobを`FAILED`または再試行可能な`QUEUED`へ遷移させる。

## 2. 追加module

| module | 責務 |
|---|---|
| `job_contracts.py` | job状態、固定error code、lease、fencing、finalization契約 |
| `job_store.py` | job claim、heartbeat、retry、transaction確定、参照read model |
| `sources.py` | 原本読取protocolとroot固定の安全なdirectory reader |
| `service.py` | 再現可能なjob ID、snapshot、APPROVED / REJECTED decisionの決定 |
| `worker.py` | claim、heartbeat、source読取、service実行、retry / fail制御 |
| `inventory_snapshot_worker_process.py` | SQLite / PostgreSQLを選べる独立Worker CLI |

既存の`csv_adapter.py`、`references.py`、`validation.py`、`domain.py`は変更せず利用する。CSV parsing、業務validation、判断、永続化、process制御を別moduleに保ち、APIやUIへ処理を埋め込まない。

## 3. jobと冪等性

job IDは次のcanonical情報からSHA-256で生成する。

- format version
- source reference
- source SHA-256
- mapping version

同じ原本参照、同じ内容、同じmappingの再登録は同じjobへ収束する。requesterや登録時刻をIDへ含めない。異なる入力を同じjob IDとして保存することはstoreで拒否する。

job状態は既存schemaの`QUEUED / RUNNING / SUCCEEDED / FAILED`を維持する。

- `SUCCEEDED + APPROVED`: 正式snapshotを作成した。
- `SUCCEEDED + REJECTED`: 処理は正常完了したが、入力に隔離または数量不一致があり正式snapshotを作成しなかった。
- `FAILED`: 原本参照、hash、CSV全体契約または実行環境の問題で処理を完了できなかった。

入力不採用とシステム障害を同じFAILEDへまとめない。

## 4. lease・heartbeat・fencing

`inventory_snapshot_jobs`へ次を追加した。

- `attempt`
- `worker_id`
- `lease_token`
- `leased_until`
- `last_heartbeat_at`

Workerはclaim時にattemptを増やし、一意なlease tokenを取得する。heartbeat、完了、失敗はjob ID、attempt、worker ID、lease tokenをすべて照合する。期限切れjobを別Workerが取得した後、旧Workerはsnapshot、隔離、数量照合、decision、job状態を書き込めない。

SQLiteは`BEGIN IMMEDIATE`、PostgreSQLは`FOR UPDATE SKIP LOCKED`で同時claimを制御する。heartbeatでlease期限を延長できる。内部障害は最大3 attemptまで再試行し、上限到達後に`FAILED`とする。

## 5. source reader

Worker coreは`InventorySourceReader` protocolだけへ依存する。標準のdirectory readerは次を守る。

- 設定済みroot内の相対referenceだけを読む。
- 絶対pathと`..`を拒否する。
- symlink解決後にroot外へ出る参照を拒否する。
- 既定100 MiBの上限を持つ。
- path、ファイル名、OS例外本文、原本byteをerrorへ含めない。

正式処理前にbyte列のSHA-256をjob登録値と再照合する。不一致時は`SOURCE_SHA256_MISMATCH`で停止し、validationやsnapshot保存を行わない。

## 6. transaction境界

最終確定は1つのDB transactionで次を実行する。

1. active leaseを再検証
2. APPROVEDの場合だけsnapshot headerとexpiry bucketを保存
3. 行番号、行hash、固定reasonだけのquarantineを保存
4. source数量、normalized数量、一致判定を保存
5. APPROVEDまたはREJECTED decisionを追記
6. job件数と`SUCCEEDED`を確定

途中でforeign key、unique、fencing、DB障害のいずれかが発生した場合、snapshotを含む派生行をすべてrollbackする。部分snapshotやdecisionだけを残さない。

## 7. 自動判断条件

Phase 3S-2の`approval_ready`がtrueの場合だけ、Worker主体によるAPPROVED decisionを作る。

- bucketが1件以上
- quarantineが0件
- source数量とnormalized数量がDecimalで一致
- snapshot日時が1つに確定

条件不成立時はREJECTED decisionを追記し、snapshotを作らない。理由は固定値`CSV_VALIDATION_REJECTED`とする。APPROVED理由も固定値`CSV_STRICT_VALIDATION_APPROVED`とする。原本値や例外本文は理由へ保存しない。

このAPPROVEDは入力在庫snapshotの機械的な採用判断であり、将来のShipment Recommendation承認ではない。

## 8. 再現性

- `known_at`は再試行ごとに変わる処理時刻ではなく、jobの`requested_at`へ固定する。
- `created_at`と`decided_at`は実行時刻だがsnapshot content hashへ含めない。
- 同じjobを再試行してもsnapshot ID、content SHA-256、decision IDは変わらない。
- snapshot IDはPhase 3S-1のcanonical bucket、version、source、時刻契約を利用する。
- quarantine IDとreconciliation IDもjob・行・reasonから決定的に生成する。

## 9. migration

既存tableを削除せず、job tableへlease列とindexを追加する。

- 空DBでは更新後schemaをそのまま作成する。
- Phase 3S-1 SQLite DBは起動時に不足列を`ALTER TABLE ADD COLUMN`で追加する。
- 3S-1で作られたquarantine tableは既存行を保持したまま、3S-2の3 reasonを許可するtableへ移行する。
- lease情報のない旧`RUNNING` jobは、安全に再取得できる`QUEUED`へ戻す。
- PostgreSQLはadvisory lock内で不足列とreason constraintだけを更新する。
- migration再実行時は追加変更を行わない。

追加したreasonは`ROW_SHAPE_INVALID`、`LOCATION_AMBIGUOUS`、`SNAPSHOT_AT_INCONSISTENT`である。

## 10. 独立Worker起動

SQLite:

```powershell
python -m forecast_provider.inventory_snapshot_worker_process `
  --sqlite .kiban/inventory.sqlite3 `
  --source-root raw_archive
```

PostgreSQL:

```powershell
python -m forecast_provider.inventory_snapshot_worker_process `
  --postgres-dsn $env:KIBAN_DATABASE_DSN `
  --source-root raw_archive
```

`--once`で1回だけqueueを確認できる。既定leaseは300秒、待機pollは5秒で、CLI引数から変更できる。Workerは原本登録APIを持たず、登録済みjobだけを処理する。

## 11. SQLite確認

人工CSVを使用して次を確認した。

- 有効CSVからAPPROVED snapshot、bucket、数量照合、job完了を同時保存
- 賞味期限欠損CSVをREJECTEDとし、snapshotを作らず隔離・数量差を保存
- 原本hash不一致を非再試行FAILEDにする
- CSV全体契約不成立を固定error codeでFAILEDにする
- 内部障害を再試行し、3回目で停止する
- heartbeatによるlease延長
- 期限切れleaseの再claimと旧Worker fencing
- transaction途中失敗時に派生tableをすべてrollback
- 同じ入力の再処理でsnapshot / decision IDが一致
- Phase 3S-1 schemaからの追加migrationで既存job・quarantineを保持

## 12. PostgreSQL確認

- SQLiteと同じservice・finalization・読取methodを使用する。
- claimだけを`FOR UPDATE SKIP LOCKED`へ置き換える。
- migrationを専用advisory lock内で実行する。
- PostgreSQL実接続のWorker E2E試験を追加した。
- このPCでは`KIBAN_TEST_POSTGRES_DSN`が未設定のため実接続試験はskipとなる。

## 13. 互換性

- 既存の在庫正規化、予測、比較、API、UI、Workerを変更していない。
- `inventory_daily_quantities`を変更していない。
- Phase 3S-1 / 3S-2の公開引数と意味を変更していない。
- 既存snapshot保存methodは同じtransaction helperを使う形へ内部整理した。
- 実データ、原本値、path、資格情報をRepositoryへ追加していない。

## 14. 未実装

- job登録・状態・decision・FEFO readのAPI
- 操作用UI
- role / permission / idempotency key / API監査event
- source archive登録との自動接続
- 商品コードmappingの本番provider登録
- Worker heartbeatの管理画面表示
- PDF adapter、OCR、抽出確認
- 実業務CSVでのpreflight
- 生産予定、Projection、Risk、Shipment Recommendation

## 15. Phase 3S-4への引継ぎ

次のsliceでは既存認証・認可・API共通契約を利用して、次を追加する。

1. CSV source参照とmapping versionを指定するjob登録API
2. job状態、件数、固定error codeの参照API
3. quarantine reason集計と数量照合の参照API
4. APPROVED / REJECTED decision履歴とsnapshot一覧API
5. JAN × locationの賞味期限昇順FEFO read API
6. READ / ANALYZE / APPROVE roleと監査event
7. API応答へ原本値、path、DSN、例外本文を出さない契約試験

担当者向け画面は、APIが固定された後のPhase 3S-4内で小さな確認画面として追加する。PDF adapterはPhase 3S-5、実データpreflightはPhase 3S-6で扱う。
