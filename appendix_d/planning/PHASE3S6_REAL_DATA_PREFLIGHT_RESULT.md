# Phase 3S-6 実データPreflight結果

- 実施日: 2026-09-26
- 対象: Phase 3S-1〜3S-4 Inventory Foundation
- 判定: **実データPreflight COMPLETE / Phase 3T開始 NO**
- セキュリティ: 実CSV、実在庫明細、実拠点名、OS path、資格情報はRepositoryへ保存していない。本書は匿名化した件数、率、reason code、集計値のみを記録する。

## 1. 調査対象

ローカル検証環境で利用できる展開済みCSVを分類し、倉庫在庫CSVをPhase 3S-2の`parse_inventory_csv`、`InventoryReferenceResolver`、`validate_inventory_csv`へ通した。原本160列または159列はメモリ上で保持し、現行契約に必要な`基準日時`だけをファイル名の日付から一時追加した。元ファイルの変更・複製・Repository保存は行っていない。

snapshot時刻は原本に存在しないため、Dry Runではファイル名の日付を同日09:00 JSTとして固定した。これは日付をUTC変換後も同日に保つための技術上の仮値であり、正式な業務時刻ではない。

調査したCSVは合計3,869ファイル、4,108,358行である。うちValidation対象は倉庫在庫1,926ファイル、200,917行である。

## 2. ファイル分類

| 分類 | 形式 | ファイル数 | 行数 | 期間 | 判定 |
|---|---|---:|---:|---|---|
| 過去出荷実績 | CP932 CSV | 1,943 | 3,907,441 | 2022-11-15〜2025-07-29 | AVAILABLE |
| 倉庫在庫 | CP932 CSV | 1,926 | 200,917 | 2022-11-15〜2025-07-29 | AVAILABLE |
| 工場在庫 | CSV/PDF/その他 | 0 | 0 | - | MISSING |
| 商品/JANマスター | CSV/PDF/その他 | 0 | 0 | - | MISSING |
| 生産予定 | CSV/PDF/Excel/その他 | 0 | 0 | - | MISSING |
| その他の実データ | - | 0 | 0 | - | 該当なし |

倉庫別内訳は匿名化した。

| 匿名location | 在庫CSV | 出荷CSV | 在庫期間 | 出荷期間 |
|---|---:|---:|---|---|
| WAREHOUSE-A | 940 | 986 | 2022-12-31〜2025-07-29 | 2022-11-15〜2025-07-29 |
| WAREHOUSE-B | 986 | 957 | 2022-11-15〜2025-07-29 | 2022-11-15〜2025-06-30 |

出荷CSVは1種類のheader、在庫CSVは160列版940ファイルと159列版986ファイルの2種類である。両在庫schemaに今回必要な商品、location、数量、賞味期限列が存在する。PDFは今回の提供データ集合に含まれず、Phase 3S-5の優先度変更に影響しない。

## 3. JAN状況

在庫CSVにはJAN列がなく、商品コードからの変換が必要である。出荷CSVにはJANが存在し、189種類の有効JANを確認したが、出荷側の商品コード列は3,907,441行すべて空欄だった。このため出荷実績だけでは在庫の商品コードとJANを直接接続できない。外部の正式な商品/JANマスターまたは承認済み対応表もローカル検証環境では確認できなかった。

### 正式入力としての判定

| 項目 | 商品数 |
|---|---:|
| 在庫の全商品コード | 147 |
| JAN直接取得 | 0 |
| 承認済みmapping成功 | 0 |
| mapping失敗 | 147 |
| mapping曖昧 | 0 |

正式JAN接続率は **0 / 147 = 0.000%** である。

### 技術的な仮対応による可能性確認

正式mappingの候補作成可能性を確認するため、商品名の完全一致だけで仮接続した。これは業務承認済みmappingではなく、正式Snapshotには使用できない。

| 項目 | 商品数 | 在庫行数 |
|---|---:|---:|
| 一意にJAN候補を得た | 130 | 176,133 |
| JAN候補なし | 2 | 5 |
| 複数JAN候補 | 15 | 24,779 |

商品単位の仮接続率は88.435%、行単位は87.665%である。出荷CSVにはJAN形式不正が47行あった。商品名は変更・表記揺れ・同名別商品を許し得るため、仮対応を正式mappingとして自動採用してはならない。

## 4. Location状況

在庫行には2種類の`明細倉庫コード`があり、200,917行すべて非空だった。各CSVは1種類のコードだけを持ち、ファイル名の匿名倉庫区分と1対1で対応した。候補location masterは次のとおりである。

| 匿名ID | type | 対象行 | 接続状態 |
|---|---|---:|---|
| WAREHOUSE-A | WAREHOUSE | 匿名集計のみ | 接続可能 |
| WAREHOUSE-B | WAREHOUSE | 匿名集計のみ | 接続可能 |

候補masterを用いたLocation接続率は **200,917 / 200,917 = 100.000%** である。FACTORYに分類できるlocationは0件だった。候補masterは技術的に作成可能だが、正式なlocation master versionとしての業務承認は未実施である。

## 5. CASE単位状況

V1 mapping候補は次のとおりである。単位は列名から推測せず、クライアント確認済みの「明細バラ数は業務上の箱」を根拠にした。

| 対象 | source column | source unit | normalized unit | 充足 |
|---|---|---|---|---:|
| 倉庫在庫1,926 CSV | `明細バラ数` | 箱 | CASE | 200,917 / 200,917 |

全200,917行をDecimalとして解釈でき、負数量は0行だった。source columnとnormalized unitは別項目として保持できる。累積原本数量は817,353,674 CASEである。この値は約3年分の日次snapshotを単純合計した検証用照合値であり、特定日の現在庫ではない。

## 6. 賞味期限状況

| 項目 | 行数 | 全行比 |
|---|---:|---:|
| 総行数 | 200,917 | 100.000% |
| 賞味期限あり・形式有効 | 200,840 | 99.961676% |
| 賞味期限なし | 77 | 0.038324% |
| 不正形式 | 0 | 0.000000% |
| snapshot日より前 | 129 | 0.064205% |
| snapshot日と同日 | 7 | 0.003484% |
| snapshot日より後 | 200,704 | 99.893997% |

旧調査の「200,917行中200,840行」と一致した。Phase 3S-2 Validationでも欠損77行を`EXPIRY_MISSING`として再現でき、形式不正はなかった。snapshot日より前の129行は削除せず、正式Snapshot化できる場合は`EXPIRED_AT_SNAPSHOT` issueの対象となる。

## 7. 賞味期限欠損分析

77行は12商品、55 snapshot日に分散していた。最大でも1日4行であり、単一日の障害ではない。最大の商品集中は26行、次点14行である。拠点別ではWAREHOUSE-Aが75行、WAREHOUSE-Bが2行だった。

欠損対象12商品はすべて、別行では有効な賞味期限を持っていた。したがって「賞味期限を持たない商品」と断定できず、行・入荷・在庫生成時点に依存する欠損の可能性が高い。ただしデータ生成仕様は未確認であり、推測補完しない。再取得可否と欠損時の正式運用を業務側へ確認する。

## 8. EXPIRY_BUCKET状況

正式JAN mappingがないため、正式なEXPIRY_BUCKETは0件である。技術的な仮対応で一意にJAN候補を得た130商品だけをPhase 3S-2 Validationへ通した結果は次のとおりである。

| 指標 | 値 |
|---|---:|
| Validationが生成したbucket合計 | 141,370 |
| JAN数 | 130 |
| location数 | 2 |
| 期間全体の異なるJAN×location×expiry | 10,135 |
| JAN×location×snapshot group | 77,681 |
| groupあたり平均bucket数 | 1.819879 |
| 複数賞味期限を持つgroup | 43,023（55.384%） |

複数賞味期限を持つgroupが過半数であり、賞味期限順取得とFEFO評価には実データ上の意味がある。ただし仮商品対応に基づくため、正式件数ではない。

## 9. 工場在庫状況

**MISSING**。提供データからFACTORY在庫を識別できず、FACTORY locationも存在しない。架空のFACTORY在庫は生成していない。

必要な正式CSV契約は、商品識別子またはJAN、工場コード、賞味期限、数量、source unit、snapshot日時である。商品コード入力の場合は承認済みproduct mapping version、工場コードには承認済みFACTORY location master versionが必要である。

## 10. 倉庫在庫状況

倉庫在庫はAVAILABLEである。商品コード、明細倉庫コード、賞味期限、明細バラ数、ファイル名の日付を取得できる。CASE数量、location、賞味期限は高い充足率を持つ。

一方、JANは外部mappingが必要で、snapshotは日付しか確定しない。したがって「倉庫在庫原本は利用可能、正式Snapshotは未受入」が正確な状態である。

## 11. 生産予定状況

**MISSING**。提供データ集合およびローカル検証環境で、生産予定と識別できるCSV、PDF、Excelは確認できなかった。

必要な契約は次のとおりである。

- JANまたは承認済みmappingで解決できる商品コード
- FACTORY location code
- 生産予定日
- 完成予定時刻（取得できる場合）
- 数量、source unit、CASE換算規則
- データ基準時刻とknown_at
- 更新頻度、取消・差替えを識別するsource key

生産予定の欠如だけならPhase 3Tの純粋計算module設計は開始できるが、工場将来在庫を含むV1受入と推奨出荷の検証は完了できない。

## 12. Route状況

FACTORY locationが0件のため、実データから工場→倉庫route master候補は作成できない。WAREHOUSE候補は2件ある。FACTORYを確定した後、各倉庫とのrouteを定義する必要がある。

正式lead timeはすべて`UNKNOWN`である。確認済みの12〜36時間という範囲からstandard値やrecommendation basisを推測設定していない。最低限、factory ID、warehouse ID、minimum/standard/maximum hours、採用basis、適用期間、policy versionが必要である。

## 13. Validation結果

Phase 3S-2の実装を変更せず適用した。現行の正式条件はquarantine 0件かつReconciliation一致である。

| 指標 | 正式mapping | 商品名完全一致の仮mapping |
|---|---:|---:|
| 対象ファイル | 1,926 | 1,926 |
| PASS | 0 | 0 |
| FAIL | 1,926 | 1,926 |
| PASS率 | 0.000% | 0.000% |
| accepted rows | 0 | 174,159 |
| quarantined rows | 200,917 | 26,758 |

正式mappingでは全行が`PRODUCT_MAPPING_MISSING`となる。仮mappingでも15商品の曖昧性が全1,926ファイルへ現れるため、PASSは0件である。

正式商品mappingで147商品すべてを一意に解決できたと仮定し、mapping reasonだけを除外すると、構造上Strict PASS候補は786 / 1,926ファイル、40.810%である。残る阻害要因は原本重複と賞味期限欠損である。

## 14. Quarantine reason集計

仮mappingで原因の重なりを含めて集計した。

| reason code | 行数 | 該当ファイル | 該当数量CASE |
|---|---:|---:|---:|
| `PRODUCT_MAPPING_AMBIGUOUS` | 24,779 | 1,926 | 156,371,920 |
| `SOURCE_DUPLICATE` | 2,054 | 1,139 | 3,002,395 |
| `EXPIRY_MISSING` | 77 | 55 | 18,251 |
| `PRODUCT_MAPPING_MISSING` | 5 | 5 | 4,120 |
| その他 | 0 | 0 | 0 |

`JAN_MISSING`、`JAN_INVALID`、`LOCATION_MISSING`、`LOCATION_UNKNOWN`、`EXPIRY_INVALID`、`QUANTITY_MISSING`、`QUANTITY_INVALID`、`QUANTITY_NEGATIVE`、`SNAPSHOT_AT_MISSING`、`SNAPSHOT_AT_INVALID`、`UNIT_MAPPING_MISSING`は在庫Validationでは0件だった。出荷側のJAN形式不正47行は、在庫mapping候補作成時に除外した。

`SOURCE_DUPLICATE`は原本160/159列全体が同一の後続行を対象とする。同値の正当な複数明細である可能性を業務確認するまで、自動削除しない。

## 15. Reconciliation

| 条件 | 原本数量CASE | 正規化後CASE | 差分CASE | 判定 |
|---|---:|---:|---:|---|
| 正式mapping | 817,353,674 | 0 | 817,353,674 | FAIL |
| 商品名完全一致の仮mapping | 817,353,674 | 658,573,800 | 158,779,874 | FAIL |

仮mappingの差分は原本の19.426%で、主因はJAN候補が複数になる24,779行である。mapping問題を解消した後も、重複・賞味期限欠損のunion 2,131行、3,020,646 CASE（原本の0.370%）はStrict採用できない。数量差を丸めたり隠したりしていない。

### 77件問題を含む運用案

| 案 | 利点 | リスク | 現時点の提案 |
|---|---|---|---|
| A. Strict維持 | JAN、FEFO、数量照合の完全性を守る | 現状は正式Snapshot 0件 | **採用**。mappingと原本問題を先に解消する |
| B. 警告付き採用 | 稼働を継続しやすい | 曖昧JAN、期限不明、重複数量が推奨へ混入する | 不採用。例外契約と業務承認なしでは危険 |
| C. 対象行を除外 | 残りの行で処理できる | 現状は19.426%の数量を失い、欠品リスクを過小評価する | 不採用。mapping解消後に77行だけ再評価する |

## 16. Snapshot Dry Run

正式条件を満たすSnapshotは0件であり、業務`APPROVED`は0件である。

技術的生成可能性を分離して確認するため、仮mappingでValidationが受理したbucketだけを使い、全1,926ファイルについて候補Snapshot objectをメモリ上で生成した。同じ入力から同じcontent SHAを得ることを1,926 / 1,926件で確認した。これらはReconciliation FAILの部分Snapshotであり、保存・承認・Read Model公開の対象ではない。

この結果は、Snapshot domain自体ではなく、正式JAN mappingと原本受入条件が現在の阻害要因であることを示す。

## 17. Strict Mode PASS率

現在の正式PASS率は **0 / 1,926 = 0.000%** である。

- 正式product/JAN mappingなし: 1,926ファイル（100%）
- 仮mappingでのJAN曖昧: 1,926ファイル（100%）
- 原本重複: 1,139ファイル（59.138%）
- 賞味期限欠損: 55ファイル（2.856%）
- 正式mappingが解決した場合の構造上PASS候補: 786ファイル（40.810%）

Strict条件をコード側で緩和していない。

## 18. 発見したBUG

Phase 3S-1〜3S-4のInventory Foundationに再現可能なBUGは確認しなかった。reason code隔離、Decimal数量、賞味期限解析、Reconciliation、決定的Snapshot identityは設計どおり動作した。

ファイル名からsnapshot日付を取るadapterが正式mappingにない点は実装不具合ではなく、現在の入力契約との差であるためMAPPING ISSUEに分類する。重複行も業務意味が未確認のためDATA ISSUEおよびBUSINESS RULE UNKNOWNに分類する。

## 19. DATA ISSUE

| 事象 | 影響 | 分類 |
|---|---|---|
| 出荷3,907,441行の商品コードが空欄 | 在庫商品コードとJANを直接接続できない | DATA ISSUE |
| 出荷JAN形式不正47行 | 対応候補から除外 | DATA ISSUE |
| 賞味期限欠損77行 | EXPIRY_BUCKETを構成できない | DATA ISSUE |
| 原本同一の後続行2,054行 | 二重計上か正当明細か未確定 | DATA ISSUE / BUSINESS RULE UNKNOWN |
| 工場在庫なし | 出荷可能上限を計算できない | FUTURE FEATURE INPUT MISSING |
| 生産予定なし | 将来工場在庫を計算できない | FUTURE FEATURE INPUT MISSING |

## 20. MAPPING ISSUE

- 在庫147商品に対する承認済み商品コード→JAN mapping versionがない。
- 商品名完全一致では130商品を一意に候補化できるが、15商品が曖昧、2商品が未接続である。
- 在庫2拠点はWAREHOUSE候補へ100%接続できるが、正式location master versionは未承認である。
- snapshot日はファイル名から取れるが時刻がなく、現行`InventoryInputMappingVersion`は列内のtimezone付き日時を要求する。正式adapterまたは事前変換規則が必要である。
- `明細バラ数`→CASEはクライアント確認により設定可能だが、mapping versionとしての承認・配布が必要である。

## 21. BUSINESS RULE UNKNOWN

- 147商品の権威あるJANと、商品コード・JANの有効期間
- 商品名が同じで複数JANになる15商品の正しい選択条件
- 原本完全一致2,054行が二重出力か、保持すべき別在庫明細か
- 賞味期限欠損77行の再取得可否と、欠損時の業務判断
- 日次在庫の正式snapshot時刻、締め時刻、timezone
- FACTORY在庫の提供元、工場コード、更新頻度、数量の意味
- 生産予定の完成時刻、取消・変更、CASE換算、known_at
- 工場→各倉庫のminimum/standard/maximum lead timeと採用basis

## 22. Phase 3T開始可否

**Phase 3T開始: NO**

理由は次のとおりである。

1. 正式JAN接続率が0%で、承認可能Snapshotが0件である。
2. FACTORY在庫がMISSINGで、出荷可能数量を制約できない。
3. 生産予定がMISSINGで、将来工場在庫を検証できない。
4. FACTORY locationがなく、routeと正式lead time policyを作れない。
5. 重複行と賞味期限欠損の業務処理が未決定である。

再判定の最小条件は、147商品の承認済みJAN対応表、2倉庫を含む正式location master、重複・賞味期限欠損の受入方針、FACTORY在庫のサンプルと契約、生産予定のサンプルまたは確定契約、route lead time policyである。Phase 3Tの純粋計算設計を準備することは可能だが、正式開始・受入判定はこれらを満たしてから行う。

## 23. ブンセン側へ追加確認が必要な事項

1. 在庫の商品コード147種類に対する正式JAN対応表と適用期間を提供できるか。
2. 商品名完全一致で複数JAN候補になる15商品は、どの属性で識別するか。
3. 出荷CSVの商品コードが空欄であることは仕様か。コードを含む別出力を取得できるか。
4. 同一CSV内で160/159列すべてが一致する2,054後続行は重複か、別明細として加算すべきか。
5. 賞味期限欠損77行を再取得できるか。取得不能時はStrict除外、警告採用、別在庫管理のどれを選ぶか。
6. 日次在庫ファイルの締め時刻とtimezoneは何か。
7. 工場在庫CSVの提供元、工場コード、数量列、賞味期限、snapshot日時は何か。
8. 生産予定の実ファイル、更新頻度、完成予定時刻、取消・差替えkey、CASE換算は何か。
9. 工場→WAREHOUSE-A/Bそれぞれのminimum/standard/maximum lead timeと推奨計算で使うbasisは何か。
10. 候補location masterと`明細バラ数`→CASE mappingを正式versionとして承認できるか。
