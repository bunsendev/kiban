# Phase 3S-1 実装結果

実施日: 2026-09-24  
対象Repository: `bunsendev/kiban`  
基準Branch: `main`  
基準Commit: `67be0df`  
実装Branch: `codex/phase3s1-inventory-foundation`

## 1. 実装概要

Phase 3S-1として、Shipment Recommendationの前提になるinventory foundationのdomainとadditive schemaを追加した。既存の`inventory_daily_quantities`とPhase 2P〜2Zは変更していない。

V1では、次を正式なdomain境界とした。

```text
JAN
× FACTORY / WAREHOUSE location
× 賞味期限(EXPIRY_BUCKET)
× 数量(Decimal / CASE)
× snapshot_at / known_at
```

CSV取込、PDF解析、Projection、Risk、Recommendation、UI、Workerは実装していない。

## 2. 追加module

| file | 責務 |
|---|---|
| `inventory_foundation/contracts.py` | 固定enum、quarantine reason、PDF approval参照 |
| `inventory_foundation/locations.py` | location master、FACTORY / WAREHOUSE、route lead time policy |
| `inventory_foundation/mapping.py` | Phase 3S-2へ渡す版付き入力mapping contract |
| `inventory_foundation/domain.py` | JAN、Decimal、時刻、EXPIRY_BUCKET、決定的snapshot identity |
| `inventory_foundation/adapters.py` | PDF原本・抽出・人間確認と入力adapter protocol |
| `inventory_foundation/schema.sql` | SQLite / PostgreSQL共通のadditive schema |
| `inventory_foundation/store.py` | SQLite schema初期化とdomain保存 |
| `inventory_foundation/postgres.py` | PostgreSQL schema初期化とadvisory lock |
| `inventory_foundation/__init__.py` | 公開contract |

業務計算、DB接続、入力adapterを分離し、後続機能が1ファイルへ集中しない構成にした。

## 3. 追加table

次の13 tableを追加した。

1. `inventory_location_master_versions`
2. `inventory_locations`
3. `inventory_route_lead_time_policies`
4. `inventory_input_mapping_versions`
5. `inventory_snapshot_jobs`
6. `inventory_snapshots`
7. `inventory_expiry_buckets`
8. `inventory_snapshot_quarantines`
9. `inventory_snapshot_reconciliations`
10. `inventory_snapshot_decisions`
11. `inventory_source_documents`
12. `inventory_extractions`
13. `inventory_extraction_reviews`

既存tableの削除、rename、column追加・削除、値更新は行っていない。

## 4. Domain Contract

### location

- `LocationType`: `FACTORY` / `WAREHOUSE`
- 有効期間付きlocation master version
- routeは同じmaster version内のFACTORYからWAREHOUSEへ接続

### route lead time

- minimum / standard / maximum
- `RecommendationBasis`: `MINIMUM` / `STANDARD` / `MAXIMUM`
- V1境界で`12 <= minimum <= standard <= maximum <= 36`
- 選択時間を`selected_lead_time_hours`としてPhase 3Tから利用可能

12〜36時間制約は`RouteLeadTimePolicy`内に閉じ込め、アプリケーション全体の定数にはしていない。

### inventory snapshot

- `snapshot_at`: 在庫状態の基準時刻
- `known_at`: システムが利用可能になった時刻
- 両方ともtimezone必須で、内部・hash表現はUTCへ統一
- `SourceKind`: `CSV` / `PDF_EXTRACTED`
- `NormalizedUnit`: `CASE`
- JANはJAN-8 / JAN-13のcheck digitまで検証
- 数量はDecimalとcanonical文字列で扱い、binary floatを拒否

### expiry bucket

- 一意性: snapshot ID、JAN、location、賞味期限、CASE
- ロット番号を要求しない
- snapshot時点で期限切れでも削除しない
- 期限切れbucketには`EXPIRED_AT_SNAPSHOT`を付与可能
- ロット管理またはロット単位FEFOに対応したとは扱わない

### mapping / quarantine

- 原本数量列名、原本単位表記、正規化単位を分離
- `明細バラ数`という名称だけでは`CASE`へ変換しない
- JAN直接入力とPRODUCT_CODE経由を区別
- quarantineは自由文字ではなく固定`QuarantineReason`を使用

### PDF境界

```text
PDF原本 → Extraction → Validation → Human Review → APPROVED → Inventory Snapshot
```

domainは承認参照を要求し、schemaはAPPROVED reviewへの複合foreign keyを要求する。未承認またはREJECTED extractionから正式snapshotを作れない。

## 5. Migration結果

- schemaはすべて`CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS`で追加する。
- 空SQLite DBへの初期化を確認した。
- 既存の在庫schemaと任意の既存tableを持つSQLite DBへの追加を確認した。
- migration後も`inventory_daily_quantities`と既存データが残ることを自動試験した。
- PostgreSQLは専用advisory lock IDを使い、同一schemaをtransaction内で適用する。
- rollbackは新moduleを呼ばないことで行える。既存機能を戻すためのdata rollbackやtable削除を必要としない。

## 6. PostgreSQL確認

- `TIMESTAMPTZ`、`DATE`、foreign key、unique、check constraintを共通schemaへ定義した。
- SQLite固有のDDLを使用していないことをschema testで確認した。
- packageへ`inventory_foundation/schema.sql`を含める設定を追加した。
- PostgreSQL storeはmigration用advisory lockを持つ。
- `KIBAN_TEST_POSTGRES_DSN`が設定された環境で同じlocation、mapping、snapshot、bucket保存試験を実行できる。
- このPCでは`KIBAN_TEST_POSTGRES_DSN`が未設定でDocker daemonも停止中のため、実PostgreSQL接続試験はskipとなった。

## 7. SQLite確認

- 空DBで13 tableを作成できる。
- foreign keyを接続ごとに有効化している。
- location role、mapping version、PDF承認、snapshotとbucketの整合を検証する。
- 既存DBへ追加しても既存tableと値を変更しない。
- 期限切れbucketを`EXPIRED_AT_SNAPSHOT`付きで保存・取得できる。

## 8. Snapshot ID / checksum再現性

hash対象は次である。

- source SHA-256、source kind、source reference
- mapping version、location master version、product mapping version
- UTC化したsnapshot_at / known_at
- normalized unit `CASE`
- JAN、location、賞味期限、unitでsortしたcanonical bucket
- Decimalのcanonical文字列
- PDF経路の場合は承認済みextraction / review参照

Worker ID、DB自動採番、処理開始時刻、実行マシン、created_atは含めない。`1`、`1.0`、`1.00`は同じ`1`としてhash化し、入力順を変えても同じsnapshot IDとcontent SHA-256になる。

## 9. テスト結果

- Phase 3S-1対象試験: 21件成功、PostgreSQL実接続1件skip
- FACTORY / WAREHOUSE、route 12〜36時間、順序、recommendation basisを確認
- JAN check digit、expiry date、CASE、Decimal canonicalizationを確認
- snapshot ID / checksum、入力順非依存、timezone、期限切れbucketを確認
- 既存SQLite DBへのadditive migrationとPDF承認境界を確認
- `ruff check .`: 合格
- `make_release.py --check`: 649 / 649一致

## 10. Regression結果

- Windows非対応のLinux `resource`試験1件だけを除外して全件実行した。
- 591件成功、14件skip、1件deselect、既存失敗0件。
- skipには既存の任意依存・PostgreSQL DSN未設定試験を含む。
- Forecast、在庫、API、Worker、UI、Phase 2P〜2Zの既存試験は変更せず合格した。

## 11. 既存機能への影響

- 既存Forecast Providerを変更していない。
- 既存予測ロジックへ在庫処理を追加していない。
- `inventory_normalization`と`inventory_daily_quantities`を変更していない。
- 既存API、Worker、UI、Schedulerを変更していない。
- `pyproject.toml`へ新schemaのpackage-data指定だけを追加した。

新storeは明示的に生成したときだけ新tableを初期化する。3S-1では既存API起動経路へ暗黙に接続しない。

## 12. 未実装事項

- CSV本取込、正規化、隔離処理
- PDF parser、OCR、LLM抽出
- API、Worker、UI
- FEFO消費計算
- 需要予測との接続
- 生産予定取込
- 将来在庫Projection、arrival-time inventory
- 欠品・賞味期限・偏在Risk
- Shipment Recommendation
- 日次Scheduler、自動出荷、基幹システム書込み

## 13. Phase 3S-2へ引き継ぐ内容

1. `InventoryInputMappingVersion`を使うCSV adapter
2. JAN / PRODUCT_CODE、location、expiry、Decimal CASEの行validation
3. 固定`QuarantineReason`による隔離
4. 原本数量と正規化数量の照合
5. `inventory_snapshot_jobs`の状態遷移
6. 正式snapshotのAPPROVED / REJECTED判断
7. 実ファイル名からsnapshot日時を得る場合の版付き規則
8. 原本値をlog・error・Repositoryへ出さない実装

Phase 3Tは、Phase 3Sのsnapshot IDに加えて独立した`production_schedule_snapshot_id`とroute policy versionを参照する。生産予定をinventory foundationへ混入させない。

## 14. 技術的懸念

- 実PostgreSQL接続試験はDSNまたは稼働中Docker環境で再実行が必要である。
- 工場・倉庫の正式location master、CASE mapping、route policyの業務値は未受領である。
- 賞味期限欠損行は3S-2で隔離するが、再取得・業務判断方法は未確定である。
- PDF schemaは境界のみであり、帳票ごとの抽出品質を保証しない。
- `quantity_cases`はDB間で同じhash表現を保つためcanonical TEXTとして保存する。計算時は必ずDecimalへ復元する。
