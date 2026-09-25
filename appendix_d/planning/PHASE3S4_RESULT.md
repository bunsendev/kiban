# Phase 3S-4 API / Read Model 実装結果

実施日: 2026-09-25  
対象Repository: `bunsendev/kiban`  
基準Branch / Commit: `main` / `da38b16`

## 1. Branch / Commit / PR

- 実装Branch: `codex/phase3s4-inventory-api`
- 実装Commit: `14c7604`
- PR: 本書と配布整合性更新後に作成

## 2. 実装API

| method | path | permission | 用途 |
|---|---|---|---|
| POST | `/api/inventory-snapshot-jobs` | ANALYZE | source参照、SHA-256、mapping、known_atによる冪等job登録 |
| GET | `/api/inventory-snapshot-jobs/{job_id}` | READ | 状態、attempt、各時刻、固定error、snapshot・隔離・照合状態 |
| GET | `/api/inventory-snapshot-jobs/{job_id}/quarantine-summary` | ANALYZE | reason code別件数 |
| GET | `/api/inventory-snapshot-jobs/{job_id}/reconciliation` | ANALYZE | 原本数量、正規化数量、差分、一致状態、CASE単位 |
| GET | `/api/inventory-snapshots` | READ | current decision付きsnapshot一覧、filter、pagination |
| GET | `/api/inventory-snapshots/{snapshot_id}` | READ | 原本行を含まないmetadata詳細 |
| GET | `/api/inventory-snapshots/{snapshot_id}/decisions` | READ | revision昇順の追記型履歴 |
| POST | `/api/inventory-snapshots/{snapshot_id}/decisions` | APPROVE | APPROVED / REJECTED追記 |
| GET | `/api/inventory-snapshots/{snapshot_id}/fefo` | READ | 指定した承認済みsnapshotのFEFO入力 |
| GET | `/api/inventory-snapshots/approved/as-of` | READ | calculation_at時点の正式snapshotとFEFO入力 |

全POSTは既存`Idempotency-Key` middlewareを使用する。job ID自体も入力内容から決定するため、
同じ入力は同じjobへ収束する。

## 3. Read Model

`InventorySnapshotReadService`を追加し、APIと将来のPhase 3Tが同じapplication boundaryを
利用できるようにした。Phase 3TからHTTP自己呼出しは行わない。一覧とbucketは件数、limit、
offsetを返し、JAN、location ID、location typeで絞り込める。DB取得はcountとpage本体の
定数回queryであり、行ごとのN+1 queryを行わない。

## 4. Decision Contract

decisionは`APPROVED / REJECTED`の追記専用eventである。各eventはdecision、reason、
credential由来subject、created_at、1始まりrevisionを持つ。REJECTEDの理由は必須、
APPROVEDのコメントは任意とした。`expected_revision`が最新revisionと違う操作は
`INVENTORY_DECISION_CONFLICT`の409で拒否し、silent overwriteを防ぐ。

SQLiteは`BEGIN IMMEDIATE`、PostgreSQLはunique `(snapshot_id, revision)`とtransactionで
競合を直列化する。過去eventのUPDATE / DELETEは実装していない。既存decisionには日時順で
revisionをbackfillする追加migrationを用意した。

## 5. 最新Decisionの定義

同一snapshotの最大revision eventを現在状態とする。APPROVED後のREJECTEDも新しいeventを
追記する。管理APIは全履歴と現在状態を表示できるが、正式Readは最新状態がAPPROVEDの場合だけ
返す。decision時刻は前revisionより前へ戻せない。

## 6. As-of Snapshot選択

`calculation_at`に対し、次をすべて満たす候補だけを使用する。

1. `known_at <= calculation_at`
2. `snapshot_at <= calculation_at`
3. calculation_atまでに存在した最新decisionが`APPROVED`

候補は`snapshot_at DESC, known_at DESC, snapshot_id DESC`で決定する。後日判明したsnapshotや
後日decisionを過去計算へ混入させず、同じ時点指定から同じsnapshotを選べる。後からREJECTED
されたsnapshotは、そのREJECTED以後の正式Readから除外される。

## 7. FEFO Read Contract

返却単位は`JAN × location × expiry_date × CASE`であり、FACTORY、WAREHOUSE A、
WAREHOUSE Bを別在庫として保持する。同一JAN・locationでも賞味期限bucketを集約しない。
順序は`JAN -> location_id -> expiry_date ASC`で固定した。snapshot時点で期限切れのbucketも
数量を変えず返し、`expired_at_snapshot=true`を付ける。

## 8. Permission

既存の認証、OIDC、role / permissionをそのまま再利用した。Jobとsnapshot metadataはREAD、
validation summaryとreconciliationとjob登録はANALYZE、decision追記はAPPROVEで保護する。
ADMINは既存規則により全permissionを持つ。クライアント指定のsubjectは受け取らず、認証済み
Principalから決定者を記録する。

## 9. Audit

既存の構造化`kiban.audit`形式を拡張し、job登録、decision追記、正式FEFO / as-of参照へ固定の
`operation`を付けた。request ID、route、status、subject、roleを記録し、source path、raw row、
原本byte、DSN、bucket業務値は記録しない。

## 10. PostgreSQL結果

PASS。WindowsからWSL PostgreSQL 18.6へ接続し、Phase 3S-4全8試験をskipなしで成功した。
PostgreSQL固有試験ではpagination、as-of query、expiry sort、3主要index、2担当者の同時decision
競合を確認した。結合対象はPhase 3S-1〜3S-4、認証、監査、idempotencyを含め82件成功した。

## 11. SQLite結果

PASS。API人工fixture 6件でjob登録・状態、隔離summary、数量照合、一覧・詳細・pagination・
filter、APPROVED / REJECTED、履歴、409競合、as-of、FEFO、期限切れbucket、権限、監査を確認した。
既存DBにはrevisionを日時順で追加し、新規DBはNOT NULL / CHECK / uniqueを持つ。

## 12. API Test

PASS。API responseへsource reference、raw row、row hash、原本byte、worker lease、OS path、DSN、
内部例外本文が出ないことを確認した。not found、未承認、競合、mappingなしは固定error codeを返す。
入力validation errorも既存共通形式を使用する。

## 13. Regression

PASS。Windows非対応のLinux専用peak RSS 1件を除外した全回帰は`630 passed / 18 skipped /
1 deselected`。ruff、既存lint、release preflightも成功した。PostgreSQL 18を全回帰へ一律指定
した場合に検出された既存PostgreSQL 17固定preflightとtimezone期待差はPhase 3S-4対象外であり、
Phase 3S対象suiteは実DBで別途成功している。

## 14. Performance確認

次のindexを追加・確認した。

- `inventory_snapshots_as_of_idx (known_at, snapshot_at, snapshot_id)`
- `inventory_expiry_buckets_fefo_idx (snapshot_id, jan, location_id, expiry_date)`
- `inventory_snapshot_decisions_revision_idx (snapshot_id, revision)` unique partial index
- `inventory_snapshot_decisions_state_idx (decision, snapshot_id, revision)`

全bucket無制限返却を禁止し、最大500件のpaginationとJAN / location / location type filterを設けた。

## 15. Security確認

READ、ANALYZE、APPROVEの許可・拒否を既存credentialで試験した。decision主体はtokenのsubjectで
あり、request bodyによる詐称はできない。共通security header、HTTPS境界、OIDC実装は変更して
いない。API固有例外は固定codeと一般化した日本語messageへ変換する。

## 16. 既存機能への影響

既存の予測、Phase 2P〜2Z、在庫正規化、日次在庫、既存API pathを変更していない。
`create_app`には任意のinventory store注入を追加し、未指定のテスト・ローカル構成は従来動作を
維持する。本番factoryは同じPostgreSQL DSNから新storeを構築する。schema変更はdecisionの
revisionと検索indexだけの追加migrationで、過去decisionを削除しない。

## 17. 未実装

指示どおり、担当者UI、PDF parser / OCR / LLM抽出、生産予定、需要予測接続、将来在庫、
arrival-time inventory、FEFO消費、Risk Engine、Shipment Recommendation、日次Scheduler、
自動出荷は実装していない。実データもRepositoryへ追加していない。

## 18. Phase 3S-5 / 3S-6への引継ぎ

Phase 3S-5は既存`InventoryInputAdapter`、source document、extraction、review tableを使い、
fake PDF adapter E2Eと正式CSV境界への互換性を確認する。PDF値は人間承認前に正式snapshotへ
入れない。Phase 3S-5へ進める状態である。

Phase 3S-6は実データpreflight、項目充足率、隔離reason、数量照合、運用手順を扱う。
順序上は3S-5完了後に進めるため、現時点では開始しない。Phase 3Tは本Phaseの
`InventorySnapshotReadService.approved_as_of`を正式入力境界として利用できる。
