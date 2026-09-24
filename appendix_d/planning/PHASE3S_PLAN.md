# Phase 3S 実装計画

作成日: 2026-09-24  
対象Repository: `bunsendev/kiban`  
基準Branch: `main`  
基準Commit: `783f92210a8421ad13b2d22ad8726f02ab3ea191`  
関連資料: `planning/DAILY_SHIPMENT_OPTIMIZATION_GAP_ANALYSIS.md`

## 1. 目的

Phase 3Sでは、日次Shipment Recommendationの入力になる在庫基盤を追加する。最低限、次の情報を失わず、同一入力から同一snapshotを再現できるようにする。

```text
JAN
× location
× 賞味期限
× 数量(CASE)
× snapshot日時
```

V1のlocation typeは`FACTORY`と`WAREHOUSE`である。ロット番号は必須にせず、`JAN × location × 賞味期限`を`EXPIRY_BUCKET`として扱う。これは賞味期限bucketによるFEFO評価であり、ロット管理またはロット単位ピッキングへの対応を意味しない。

本Phaseでは既存の`inventory_normalization`を破壊的に変更しない。正式入力用の新しいmoduleと台帳を追加し、Phase 2P〜2Zの既存API、CSV、DB、試験を維持する。

## 2. 確定した業務条件

1. 正式な構造化入力はCSVを優先する。
2. PDFは原本、抽出結果、確認状態を追跡し、人間が承認した構造化結果だけを正式入力へ渡す。
3. 商品識別はJANを基本とし、既存のJAN / canonical product基盤を再利用する。
4. 原本の`明細バラ数`は業務上の箱数であり、V1の正規化単位は`CASE`とする。
5. 原本列名・原本単位表記と正規化単位を別管理し、名称から単位を推測しない。
6. location typeは最低限`FACTORY`と`WAREHOUSE`を持ち、複数工場・中間拠点を後から追加できる形にする。
7. 受注、引当、入庫予定、外部出荷予定はV1入力にしない。架空の0または架空eventを生成しない。
8. 生産予定はPhase 3Tで工場将来在庫へ接続する。
9. FACTORYからWAREHOUSEへのlead timeは12〜36時間であり、route別の版付きpolicyとする。
10. Shipment Recommendationは現在庫ではなく、到着予定時点までの需要を差し引いた`arrival_time_inventory`を基準とする。

## 3. Scope

### 3.1 Phase 3Sで実装するもの

- `FACTORY` / `WAREHOUSE`を持つ版付きlocation master
- JAN、canonical product、location、賞味期限、CASE数量、snapshot時刻を持つ在庫snapshot
- `EXPIRY_BUCKET`の賞味期限昇順read model
- 原本列名と正規化単位`CASE`を分離した版付きCSV mapping
- CSVの正式取込、検証、隔離、数量照合、承認
- 同一入力から同一snapshot ID / checksumを作る決定的正規化
- PDF用のadapter contractと、原本・抽出・確認・正式入力を分ける永続化境界
- 生産予定snapshotとroute lead time policyをPhase 3Tから参照するためのID contract
- PostgreSQL / SQLiteの同等動作
- API、Worker、監査、readinessへの追加接続

### 3.2 Phase 3Sで実装しないもの

- PDFの製品固有帳票parser、OCRまたはLLM抽出器
- 需要予測との結合計算
- 生産予定の本取込と工場在庫Projection
- arrival-time inventoryの計算
- FEFO消費計算、Risk Engine、Shipment Recommendation
- 受注、引当、入庫予定、外部出荷予定の取込
- ロット追跡、ロット単位のピッキング指示
- 不足値の推測または架空データ生成

これらのうちProjectionとRecommendationはPhase 3T以降で実装する。Phase 3Sは、その計算に必要な入力の意味と系譜を固定する。

## 4. 設計原則

- **追加型migration**: 既存tableや列の意味を変更しない。
- **原本優先**: 原本はimmutable archiveとSHA-256で参照し、業務値をGitやログへ保存しない。
- **版付きmapping**: 列、単位、location、商品対応をrunごとに固定する。
- **時点安全**: `snapshot_at`と`known_at`を分け、後から判明した値を過去計算へ混入させない。
- **決定的計算**: 並び順、Decimal表現、時刻、hash入力を固定する。
- **厳格な正式採用**: V1は隔離行0件かつ数量照合一致を正式snapshotの条件とする。
- **責務分離**: HTTP route、Worker CLI、DB storeへ業務正規化ロジックを置かない。
- **互換維持**: 既存の`inventory_daily_quantities`とPhase 2X〜2Zの出力を変更しない。

## 5. Canonical contract

### 5.1 location

```text
location_id
location_code
location_name
location_type = FACTORY | WAREHOUSE
effective_from
effective_to
location_master_version
```

`location_type`はV1では2値に制限する。将来の中間拠点は既存値の意味を変えず、新しいtypeとして追加する。

### 5.2 在庫snapshot header

```text
snapshot_id
snapshot_at
known_at
source_kind = CSV | PDF_EXTRACTED
source_reference
source_sha256
mapping_version
location_master_version
product_mapping_version
normalized_unit = CASE
row_count
quantity_cases_total
content_sha256
created_at
```

### 5.3 在庫expiry bucket

```text
snapshot_id
jan
canonical_product_id
location_id
expiry_date
bucket_kind = EXPIRY_BUCKET
quantity_cases
normalized_unit = CASE
```

主な一意keyは`(snapshot_id, jan, location_id, expiry_date, normalized_unit)`とする。`quantity_cases`は浮動小数ではなくDecimalで扱い、hash化前にcanonical文字列表現へ変換する。

賞味期限がsnapshot日時以前の在庫も失わず保存する。これは廃棄リスク評価に必要であり、`EXPIRED_AT_SNAPSHOT`のissueを付けてread modelへ残す。

### 5.4 source mapping

mappingは最低限、次を版付きで保持する。

- 商品列と識別種別`JAN` / `PRODUCT_CODE`
- `PRODUCT_CODE`の場合に使用する既存product mapping version
- location列とlocation mapping version
- 賞味期限列
- 数量列
- snapshot時刻列またはファイル名規則
- 原本数量列名
- 原本単位表記
- 正規化単位`CASE`
- encoding、delimiter、header行
- 有効期間、作成者、承認者、変更理由

`明細バラ数`という列名だけで個数へ変換しない。対応するmappingが`CASE`と明示している場合だけ採用する。

## 6. 変更予定DB

既存schemaは変更せず、次のtableを新規追加する。名称は実装前の最終schema reviewで既存命名規則へ揃えるが、責務は変更しない。

| table | 役割 |
|---|---|
| `inventory_location_master_versions` | location masterの版、hash、承認情報 |
| `inventory_locations` | location code、名称、`FACTORY` / `WAREHOUSE`、有効期間 |
| `inventory_route_lead_time_policies` | factory→warehouse routeのminimum / standard / maximum時間とV1採用値 |
| `inventory_input_mapping_versions` | CSV列、商品、location、単位、snapshot時刻の版付きmapping |
| `inventory_snapshot_jobs` | 取込要求、状態、件数、lease、失敗code |
| `inventory_snapshots` | 正式在庫snapshot header、入力版、件数、checksum |
| `inventory_expiry_buckets` | JAN×location×賞味期限×CASE数量 |
| `inventory_snapshot_quarantines` | 行番号、行hash、固定reason code。業務値は保存しない |
| `inventory_snapshot_reconciliations` | 原本採用数量と正規化数量の照合 |
| `inventory_snapshot_decisions` | APPROVED / REJECTEDの追記型判断 |
| `inventory_source_documents` | PDF原本等のmedia type、archive参照、hash |
| `inventory_extractions` | extractor/version/config hash、構造化結果参照、状態 |
| `inventory_extraction_reviews` | PDF抽出結果のAPPROVED / REJECTED判断 |

### 6.1 route lead time policy

```text
policy_id
policy_version
factory_location_id
warehouse_location_id
minimum_hours
standard_hours
maximum_hours
recommendation_basis = MINIMUM | STANDARD | MAXIMUM
effective_from
effective_to
approved_by
approved_at
reason
```

V1では`12 <= minimum <= standard <= maximum <= 36`をdomain validationする。実計算は`recommendation_basis`で選択した値とpolicy versionを保存し、過去結果を再現できるようにする。

### 6.2 migrationのロックと順序

- PostgreSQLは既存方式と同じadvisory lockを使用し、一意なmigration lock IDを割り当てる。
- SQLiteにも同じ制約、index、状態遷移を可能な範囲で実装する。
- master、mapping、job、snapshot、bucket、decision、PDF境界の順に作成する。
- foreign keyとunique indexはtable作成と同じmigrationで追加する。
- 既存tableのrename、column drop、意味変更は行わない。

## 7. 新規module

ファイル肥大化を避けるため、Phase 3Sは次の構成を基本とする。

```text
forecast_provider/
  inventory_foundation/
    __init__.py
    contracts.py       # API/Worker境界の型
    domain.py          # 値object、固定code、純粋validation
    locations.py       # location masterとroute policy
    mapping.py         # CSV mappingの検証と版管理
    adapters.py        # InventoryInputAdapter protocol
    csv_adapter.py     # CSV→構造化row。DBへ直接書かない
    normalization.py   # JAN/location/expiry/CASEの決定的正規化
    reconciliation.py  # 数量・件数照合
    store.py           # 永続化interfaceとSQLite実装
    postgres.py        # PostgreSQL実装
    service.py         # transactionと正式採用条件
    schema.sql
  api/
    inventory_foundation_routes.py
  inventory_foundation_worker.py
```

目安として、1ファイルは1責務とし、routeやWorkerは引数変換とservice呼出しに限定する。将来、生産予定は`production_schedule/`、Projectionは`inventory_projection/`として別moduleへ追加する。

## 8. 既存moduleへの影響

| 既存module | 変更方針 |
|---|---|
| `inventory_normalization` | schemaと出力を変更しない。既存取込を利用する画面・APIは継続動作させる |
| `master` | JAN / canonical productの時点付きlookupをread-onlyで再利用する |
| `ingestion` | `source_files`、archive、hash、path安全性をCSV原本参照に再利用する |
| API app / factory | 新serviceとrouteを明示的に注入する。既存route契約を変更しない |
| readiness | 新schema、store、Workerを独立項目として追加し、既存結果の意味を変えない |
| audit / operation events | mapping、job、decisionの操作eventを既存形式で追加する |
| Phase 2X〜2Z | 既存feature CSVを維持する。新snapshotからの互換exportは別endpointとする |
| Forecast Provider群 | 変更しない。需要予測と在庫Decision Engineの責務を分離する |
| UI | Phase 3Sでは管理・確認に必要な最小画面だけを対象とし、日次推奨UIはPhase 3Wとする |

既存moduleから新台帳への自動backfillは行わない。既存日次集約には賞味期限がなく、正式な`EXPIRY_BUCKET`を復元できないためである。

## 9. migration方針

1. additive schemaをPostgreSQL / SQLiteへ追加する。
2. 起動時schema初期化を既存factoryへ追加する。
3. 既存データは移行せず、そのまま参照可能にする。
4. Phase 3Sの新しいCSV取込から新台帳を作る。
5. 必要な場合だけ、既存snapshotを「賞味期限なしの診断用」として読むbridgeを別途設ける。正式snapshotへ昇格させない。
6. rollback時は新routeとWorkerを無効化し、既存機能をそのまま稼働させる。新tableの削除をrollback条件にしない。

release前に、空DB、既存SQLite DB、既存PostgreSQL DBの3経路でmigrationを確認する。

## 10. 既存データ互換性

- `inventory_daily_quantities`、既存approval、特徴CSVの形式を変更しない。
- 既存の`unit`値を書き換えない。Phase 3Sの`normalized_unit=CASE`は新台帳内だけで適用する。
- 元の列名を`source_column_name`としてmappingに保存し、既存表記を失わない。
- canonical productの有効期間lookupは既存実装を利用し、結果と参照versionをsnapshotへ固定する。
- 同じ原本でもmapping versionが異なれば別snapshot候補とする。
- 既存処理からPhase 3Sを呼ぶ暗黙の副作用を作らない。

## 11. CSV取込方法

```text
CSV upload / intake
  ↓ immutable archive + SHA-256
source_filesの採用済み原本
  ↓ mapping versionを指定してjob作成
CSV adapter
  ↓ header・encoding・型の検査
JAN / canonical / location / expiry / CASE normalization
  ↓ invalid rowはquarantine
決定的aggregateと数量照合
  ↓ 厳格な採用条件
APPROVED inventory snapshot
```

### 11.1 正式採用条件

- 原本hashが固定されている。
- mapping、location master、product mappingのversionが固定されている。
- JAN、location、賞味期限、数量、snapshot日時が全行で有効である。
- 正規化単位が全行`CASE`である。
- quarantineが0件である。
- 原本採用数量と正規化後数量がDecimalで一致する。
- snapshot content hashが決定的に計算できる。
- APPROVED decisionが追記されている。

### 11.2 主な隔離code

- `JAN_MISSING` / `JAN_INVALID`
- `PRODUCT_MAPPING_MISSING` / `PRODUCT_MAPPING_AMBIGUOUS`
- `LOCATION_MISSING` / `LOCATION_UNKNOWN` / `LOCATION_TYPE_INVALID`
- `EXPIRY_MISSING` / `EXPIRY_INVALID`
- `QUANTITY_MISSING` / `QUANTITY_INVALID` / `QUANTITY_NEGATIVE`
- `SNAPSHOT_AT_MISSING` / `SNAPSHOT_AT_INVALID`
- `UNIT_MAPPING_MISSING`
- `SOURCE_DUPLICATE`
- `PDF_EXTRACTION_NOT_APPROVED`

隔離には業務値を複写せず、source reference、行番号、行hash、reason codeを保存する。再処理時も同じ入力とmappingなら同じ判定になるようにする。

## 12. PDF対応方針

PDF解析をPhase 3S本体へ依存させない。次のadapter境界を定義する。

```text
PDF原本
  ↓ immutable archive / hash
抽出器（製品固有、差し替え可能）
  ↓ extractor version / config hash / 構造化結果
共通validation
  ↓ REVIEW_REQUIRED
人間確認
  ↓ APPROVED extraction
InventoryInputAdapter
  ↓ CSVと同じcanonical contract
正式inventory snapshot
```

`InventoryInputAdapter`は、source provenanceと構造化rowを返すprotocolとする。coreはPDF library、OCR、LLMへ依存しない。PDF経路では、次が揃わない限り正式snapshot jobを作れない。

- 原本document IDとSHA-256
- extractor名、version、設定hash
- 抽出結果IDとchecksum
- validation結果
- 確認者、確認日時、APPROVED decision

抽出値を無条件で在庫へ採用しない。Phase 3Sではこのcontract、状態遷移、DB境界、fake adapter試験までを実装し、実帳票parserはサンプル帳票と確認手順が揃った後の個別sliceとする。

## 13. 再現性

snapshot IDとcontent hashは最低限、次をcanonical順でhash化して生成する。

- source SHA-256
- source kindとsource reference
- mapping version
- location master version
- product mapping version
- snapshot_at / known_atをUTC化した値
- normalized unit
- JAN、location、expiry順にsortしたbucket rows
- Decimalのcanonical文字列表現

DBの自動採番、処理開始時刻、Worker IDはcontent hashへ含めない。同じ入力と版からは、PostgreSQL / SQLiteのどちらでも同じsnapshot IDとchecksumを得る。

## 14. テスト方法

### 14.1 Unit test

- location type、route 12〜36時間、policy順序のvalidation
- JAN、賞味期限、Decimal、CASE mapping
- 同一入力のsnapshot ID / checksum一致
- 行順、改行、DB種別に依存しない決定性
- 賞味期限昇順の`EXPIRY_BUCKET`取得
- snapshot以前に期限切れのbucketを失わないこと
- 固定quarantine code

### 14.2 Adapter / service test

- UTF-8 / CP932、delimiter、header mapping
- JAN直接入力と既存商品コード→JAN mapping
- FACTORY / WAREHOUSEの分離
- `明細バラ数`→`CASE`を版付きmappingだけで行うこと
- 77件相当の賞味期限欠損を隔離し、正式採用しないこと
- 数量照合不一致時のREJECTED
- 未承認PDF抽出結果を正式入力へ渡せないこと
- 承認済みfake PDF adapterがCSVと同じcanonical contractへ到達すること

### 14.3 Store / API / Worker test

- SQLite / PostgreSQLの同等性
- transaction中断時に正式snapshotが部分作成されないこと
- job lease、再試行、heartbeat、冪等性
- API認証・role、idempotency、監査event
- 同時実行でsnapshotが重複しないこと
- raw rowやPDF内容がlog・API errorへ出ないこと

### 14.4 End-to-end / compatibility test

- 人工CSVでupload→job→validation→approval→FEFO readまで通す。
- FACTORYとWAREHOUSEを含む人工fixtureでlocation混同がないことを確認する。
- 既存テスト群を実行し、Phase 2P〜2ZのDB、API、CSV checksumが変わらないことを確認する。
- 実データはread-onlyで項目充足率と件数だけを確認し、Repositoryへcommitしない。
- 実装完了時は`pytest`、`ruff`、release preflightを実行する。

今回の計画文書変更ではコードを変更しないため、実装テストはまだ実行しない。文書のdiff、link、用語整合だけを確認する。

## 15. 実装順序

大規模な一括変更を避け、次のreview可能なsliceで進める。

1. **3S-1: domain / schema**  
   location、route policy、mapping、snapshot、bucket、decision、PDF境界のcontractとmigration。
2. **3S-2: CSV adapter / validation**  
   版付きmapping、JAN/location/expiry/CASE正規化、quarantine、数量照合。
3. **3S-3: service / store / Worker**  
   job、lease、transaction、決定的snapshot、PostgreSQL / SQLite。
4. **3S-4: API / read model**  
   upload参照、job状態、approval、snapshot一覧、FEFO read、監査。
5. **3S-5: PDF adapter boundary / compatibility**  
   document、extraction、review状態、fake adapter E2E、既存機能回帰。
6. **3S-6: 実データpreflight / 受入資料**  
   項目充足率、隔離reason集計、数量照合、運用手順。実データはcommitしない。

各sliceでmoduleの責務を維持し、前sliceのcontractを必要なく変更しない。変更が必要な場合はschema versionとmigrationを追加し、既存値の意味を上書きしない。

## 16. Phase 3Tへの接続方法

Phase 3Tは、次のIDとversionを明示してProjection runを作る。

```text
inventory_snapshot_id
forecast_run_id
production_schedule_snapshot_id
route_lead_time_policy_version
safety_stock_policy_version
shipping_unit_policy_version
calculation_at
```

WAREHOUSEの最初のProjectionは次を計算する。

```text
arrival_at = calculation_at + selected_route_lead_time
arrival_time_inventory
= current_warehouse_inventory
 - forecast_demand(calculation_at, arrival_at]
```

FACTORYのProjectionは次を計算する。

```text
future_factory_inventory
= current_factory_inventory
 + production_schedule
 - confirmed_recommendation_shipments
```

外部受注、引当、入庫予定、外部出荷予定はV1の式へ入れない。将来は`SupplyDemandEventProvider`境界へ追加するが、未取得eventを0件の実績や架空eventとして保存しない。未使用であることと契約versionをrun metadataへ記録する。

Phase 3Sの`EXPIRY_BUCKET` read modelは、Phase 3Tへ賞味期限昇順で数量を渡す。Phase 3Tはこれを消費する純粋計算moduleとし、Phase 3Sの台帳を書き換えない。

## 17. Phase 3S完成条件

- `JAN × location × 賞味期限 × 数量(CASE) × snapshot日時`を失わず保存できる。
- `FACTORY`と`WAREHOUSE`を区別できる。
- 既存inventory機能とPhase 2X〜2Zの互換性を維持する。
- `EXPIRY_BUCKET`を賞味期限順に取得できる。
- 同一入力と同一versionから同一snapshot ID / checksumを得る。
- 異常行を固定codeで隔離し、正式snapshotへ混入させない。
- CSVから正式に取り込み、数量を照合して承認できる。
- PDF原本、抽出結果、確認状態を追跡でき、未承認結果を正式入力にできない。
- 工場在庫・生産予定・route policyをPhase 3Tで参照できるID contractがある。
- ロット番号がなくても稼働し、ロット管理済みとは表示しない。
- 実データ、raw row、PDF内容をRepositoryへcommitしない。
- PostgreSQL / SQLite、API、Worker、自動試験、監査、運用手順が揃う。

## 18. 実装前に確定する入力

Phase 3S-1の開始前に、実装を止めずに仮schemaを作れるが、正式受入までに次を確定する。

1. 工場在庫CSVの列、snapshot日時、工場識別方法
2. 倉庫コードと`WAREHOUSE` locationの正式対応表
3. 生産予定CSVの列、完成予定時刻、更新頻度、データ基準時刻
4. 賞味期限77欠損行の業務上の意味と再取得可否
5. `明細バラ数`以外の数量列、すべてが`CASE`か、換算・丸めが必要か
6. route別minimum / standard / maximum lead timeと、V1の`recommendation_basis`
7. 安全在庫policyと出荷単位policyの管理単位
8. PDF原本例、抽出方法、確認担当、承認期限

これらが未確定の値をコードへ固定しない。版付きmaster / mapping / policyとして外出しし、正式値の受領後にデータ登録で切り替えられる構造にする。

## 19. 実装開始判断

本計画のreview後、最初の実装は**3S-1: domain / schema**とする。ここでは既存データを変更せず、追加table、contract、validation、migration試験だけを導入する。

計画承認前に大規模実装、既存schema変更、実データcommitは行わない。
