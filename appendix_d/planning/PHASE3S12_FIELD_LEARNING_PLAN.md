# Phase 3S-12 現場運用開始Gate・Shadow Mode計画

- 実施日: 2026-09-27
- 対象Repository: `bunsendev/kiban`
- 基準: `main` / `062b2e9`
- 実データ: 倉庫在庫1,926 CSV・200,917行、出荷1,943 CSV・3,907,441行
- 判定: **実データ再確認 INCOMPLETE / Shadow Mode BLOCKED**
- セキュリティ: 実CSV、商品名、商品コード、JAN、倉庫名、ファイル名、OS pathをRepositoryへ保存しない。本書には匿名集計だけを記載する。

## 1. 方針と結論

現場導入は、すべてのデータが揃うまで待つ方式から、限定商品を対象に安全な範囲で検証する方式へ
変更する。FACTORY在庫、生産予定、全routeがなくても、WAREHOUSE側のProjectionと賞味期限評価は
先行できる。

ただし2026-09-27時点では、現場Shadow Modeを開始できない。主な理由は次の4点である。

1. 実データ用の確認済みProduct Mapping、Location Master、Input Mapping、Snapshot Time Policyが未登録で、APPROVED Snapshotがない。
2. Warehouse ProjectionとExpiry / FEFO Simulationが未実装である。
3. 現行Inventory SnapshotはCSV全行のStrict採用であり、Pilot商品だけを明示的に対象化する版付きscopeがない。
4. 需要予測の`canonical_product_id × center_id`と在庫の`JAN × location_id`を結ぶ正式な版付きidentity bridgeがない。

3T-Aと3T-Bの純粋計算moduleは実装開始できる。一方、Shadow運用開始には、その前段としてPilot Scope、
Identity Bridge、Feedback Ledgerの最小基盤が必要である。

## 2. 現在の実装状況

| 機能 | コード | 実データ運用 | Shadowでの評価 |
|---|---|---|---|
| 需要予測 | 実装済み。Baseline、AutoETS、Ridge、TimesFMとrun台帳がある | 実データ比較実績あり | 利用可能。ただし在庫identityとの正式接続が必要 |
| Inventory Snapshot | CSV validation、隔離、数量照合、Workerを実装済み | 正式snapshot 0件 | 基盤は利用可能。Pilot scopeが必要 |
| JAN mapping | 候補生成と不変な正式台帳を実装済み | 130一意候補、15複数、2なし。業務確認未完了 | 部分開始の候補はある |
| Location Master | FACTORY / WAREHOUSEと正式取込を実装済み | 2倉庫候補。正式名称・有効期間・承認未完了 | 確認後に利用可能 |
| Input Mapping | 版付き正式取込を実装済み | 実データ版未登録 | 参照master確定後に利用可能 |
| Snapshot Time Policy | ファイル名日付＋明示時刻・timezoneを実装済み | 全1,926ファイルの日付形式は適合。締め時刻未確認 | policy登録後に利用可能 |
| APPROVED Snapshot | 追記型decisionを実装済み | 0件 | 未充足 |
| as-of Read | `known_at`、`snapshot_at`、decision時点選択を実装済み | 正式入力がないため未使用 | 利用可能 |
| EXPIRY_BUCKET | JAN×location×賞味期限×CASEを実装済み | 仮mappingでは141,370 bucket生成可能 | 3T-B入力に利用可能 |
| 監査 | API監査、認証主体、操作telemetryを実装済み | 稼働可能 | 操作telemetryはFeedback Ledgerの代用不可 |
| Worker | lease、heartbeat、retry、fencing、PostgreSQL claimを実装済み | 正式入力待ち | 利用可能 |

`operation_events`は画面改善用の匿名telemetryであり、JAN、数量、担当者判断、実績を意図的に保存しない。
このprivacy境界を変更せず、業務Feedbackは別module・別tableで管理する。

## 3. 実データ再判定

Phase 3S-7〜3S-11を反映したmainで、原本を変更せず匿名集計を再実行した。

| 検査 | 結果 |
|---|---:|
| 倉庫在庫CSV | 1,926 |
| 倉庫在庫行 | 200,917 |
| 出荷CSV | 1,943 |
| 出荷行 | 3,907,441 |
| `_YYYYMMDD.csv`一致 | 1,926 / 1,926 |
| ファイル名日付として有効 | 1,926 / 1,926 |
| 在庫商品 | 147 |
| JAN一意候補 | 130 |
| JAN複数候補 | 15 |
| JAN候補なし | 2 |
| 出荷側JAN形式不正 | 47行 |

ローカルDocker / PostgreSQLは停止しており、外部または過去の稼働DBの登録状態は確認対象外とした。
Repository内の実装結果と現在のローカル入力には、業務確認済み実Product Mapping、実Location Master、
実Input Mapping、実Snapshot Time Policyの登録証跡がない。未確認の09:00 JSTを正式policyとして再利用していない。

したがって「原本再走査」は完了したが、「正式versionを適用した実データ再受入」は未完了である。

## 4. READY / CONDITIONAL / BLOCKED

商品単位の判定は次で固定する。

### READY

- 正式な商品コード→JAN mappingがある。
- JANが既存canonical productへ一意に接続される。
- 正式WAREHOUSE locationとforecast centerの対応がある。
- 承認済みsnapshotがあり、対象日の隔離と数量差がない。
- 過去出荷実績とforecast runを同じidentity・as-of時点で取得できる。

### CONDITIONAL

- JANは一意候補で、在庫・出荷・賞味期限の技術検証が可能である。
- 業務確認、正式version、scope、または一部品質ruleが未完了である。
- 参考検証には使えるが、現場へ正式な推奨として表示しない。

### BLOCKED

- JAN候補が複数または存在しない。
- 必須履歴が不足する、または商品単位で解決不能なデータ問題がある。
- 値を推測しない限りJAN×WAREHOUSE×snapshotへ接続できない。

現在の判定は次のとおりである。

| 判定 | 商品数 | 理由 |
|---|---:|---|
| READY | **0** | 正式version・APPROVED Snapshot・identity bridgeがない |
| CONDITIONAL | **130** | JAN一意候補。業務確認と正式受入待ち |
| BLOCKED | **17** | 複数JAN候補15、候補なし2 |

全商品共通のmaster / policy不足を理由に130商品をBLOCKEDへ落とさず、解消可能なCONDITIONALとして管理する。

## 5. Pilot対象の分析と選定方法

一意候補130商品を匿名で商品別再集計した。

| 指標 | 結果 |
|---|---:|
| 在庫継続日数の中央値 | 248日 |
| 出荷発生日数の中央値 | 280.5日 |
| 賞味期限有効率99%以上 | 128商品 |
| 複数賞味期限bucket groupが10回以上 | 109商品 |
| 2倉庫に在庫実績あり | 111商品 |

予備条件を「在庫日数・出荷発生日数が各180日以上、賞味期限有効率99%以上、原本重複率2%以下、
複数賞味期限bucket groupが10回以上」とすると、**75商品**が候補になる。期間条件を365日にすると
34商品、500日にすると15商品である。

75商品の需要特性の予備分類は、安定型55、変動型5、季節型15である。また58商品が観測groupの
半数以上で複数賞味期限bucketを持つ。賞味期限重要型は他分類と重複する。

最初のPilotは**15商品**を推奨する。自動確定せず、正式mapping確認後に次の構成を目安として
担当者が承認する。

- 安定型: 6
- 変動型: 4
- 季節型: 5
- 上記15商品のうち賞味期限重要型: 8以上
- 可能な限り両倉庫の商品を含める

最長履歴の商品だけを選ぶと簡単な商品へ偏るため、500日条件の15商品をそのまま自動採用しない。
商品ID一覧は正式台帳へ保存し、Repository文書には記載しない。

## 6. Pilot Scopeの必要性

現行`InventoryCsvValidationResult.approval_ready`は、CSV内に隔離行が1行でもあればfalseとなる。
実在庫CSVにはPilot外の商品も含まれるため、Pilot 15商品のmappingだけを登録しても、Pilot外行が
`PRODUCT_MAPPING_MISSING`となり正式snapshotを作れない。

部分開始には、暗黙の行除外ではなく次の版付き契約が必要である。

- `pilot_scope_version`: 対象JAN、WAREHOUSE、適用期間、承認者、理由
- `scope_kind=PILOT_PARTIAL`: 全在庫を表すsnapshotと区別
- source SHA-256と原本総行数を保持
- scope対象行数・数量、対象外行数・数量を別々に照合
- 対象行の隔離があればその商品・日付をBLOCKED
- 対象外行を正常行や隔離行として扱わず、`OUT_OF_SCOPE`として監査集計
- as-of Readと3Tは明示したscopeだけを取得

手作業でPilot CSVを切り出し、全在庫snapshotであるかのように登録してはいけない。

## 7. Forecast / Inventory Identity Bridge

需要予測は`unique_id = canonical_product_id::center_id`、Inventory Foundationは
`JAN × location_id`を主軸にする。現在の正式商品mapping CLIはcanonical IDを自動生成しないため、
既存商品masterとの接続がない場合はNULLを保持する。またlocation IDとforecast center IDの正式な
対応versionがない。

3T-A前に次を固定する。

- JAN→canonical product mapping versionと有効期間
- WAREHOUSE location→forecast center mapping versionと有効期間
- forecast runの`origin_date / cutoff_at`とinventoryの`known_at / snapshot_at`のas-of規則
- 同一identityへ複数候補がある場合はBLOCKED
- 後から判明したmappingを過去計算へ混入させない

## 8. Shadow Mode

Shadowでは、システム値を正式な出荷指示として扱わない。画面・CSV・APIに`SHADOW`、`参考値`、
`検証中`を表示し、system referenceと担当者の独立判断を分けて保存する。

初期出力は次とする。

- 7日・14日の需要予測
- WAREHOUSE現在庫と日別予測在庫
- 不足見込み日と不足見込み数量
- 賞味期限注意数量と期限内未消化見込み
- `system_reference_quantity`（参考補充量）
- 使用したrun、snapshot、scope、policy、known_at

FACTORY在庫がない間は、工場から出荷可能かを判定せず、正式なShipment Recommendationという名称を
使わない。

## 9. Feedback Ledger

業務Feedbackは追記型の独立module `field_learning/`として設計する。1つの可変行へ後日実績を
UPDATEせず、次の不変eventを合成してread modelを作る。

### `field_reference_cases`

- `case_id`
- `business_date`
- `jan`, `canonical_product_id`, `warehouse_id`
- `forecast_run_id`, `inventory_snapshot_id`, `pilot_scope_version`
- `system_forecast_quantity`
- `system_reference_quantity`
- `policy_version`, `mode`
- `known_at`, `recorded_at`, `content_sha256`

### `field_operator_decision_events`

- `decision_event_id`, `case_id`, `revision`, `expected_revision`
- `operator_decision`, `operator_quantity`
- `operator_reason_code`, `operator_comment`
- 認証subject、`known_at`, `recorded_at`

### `field_actual_outcome_events`

- `actual_event_id`, `case_id`, `revision`, `source_version`
- `actual_shipped_quantity`, `actual_demand_quantity`
- `stockout_quantity`, `expired_quantity`, `interwarehouse_transfer_quantity`
- `known_at`, `recorded_at`, `content_sha256`

### `field_weekly_reviews` / `field_learning_candidates`

- 対象週、scope、集計版、KPI、reason code集計、reviewer、判断、次の対応
- learning candidate種別、根拠件数、影響数量、状態、承認・却下event
- モデル、特徴量、policyを自動更新しない

全数量は非負Decimal CASEとし、欠測はNULL、確定ゼロだけ0にする。`known_at`は情報が利用可能になった
時刻、`recorded_at`は台帳へ記録した時刻として混同しない。

## 10. Operator Decision

固定codeは次とする。

| code | 意味 | quantity規則 |
|---|---|---|
| OBSERVED | システム案を業務判断へ使わず独立判断を観測 | 独立した担当者数量が取得できれば保存 |
| ACCEPTED | 参考値を採用 | system referenceと一致 |
| INCREASED | 参考値より増加 | system referenceより大きい |
| DECREASED | 参考値より減少 | 0以上でsystem reference未満 |
| REJECTED | システム案を明示的に不採用 | 独立判断数量を保存可能 |
| NO_ACTION | 当日の補充操作なし | operator quantityは0 |

Shadow初期は`OBSERVED`を標準とし、システム表示前に独立判断数量を取得できる業務フローを優先する。
これによりシステム表示による判断誘導を避ける。

## 11. Operator Reason Code

次を固定enumとする。

`PROMOTION`, `SEASONAL_EVENT`, `CUSTOMER_INFORMATION`, `EXPECTED_LARGE_ORDER`,
`PRODUCTION_CONSTRAINT`, `DELIVERY_CONSTRAINT`, `EXPIRY_CONCERN`, `STOCKOUT_CONCERN`,
`WAREHOUSE_CAPACITY`, `EXPERIENCE_JUDGMENT`, `DATA_ERROR`, `OTHER`

`INCREASED`、`DECREASED`、`REJECTED`ではreason codeを必須とする。commentは補助であり必須にしない。
`OTHER`だけは短いcommentを要求する。自由記述は最大500文字とし、資格情報や原本pathを保存しない。

## 12. Actual接続

実績は後日到着するため、reference caseと別eventで接続する。取込はsource version、source SHA-256、
known_atを持ち、訂正版はrevisionを追記する。既存出荷取込・日次buildの採用済みデータを需要実績の
候補とする。

実際の出荷数量、需要、欠品、期限切れ、倉庫間移動は意味が異なるため、欠損を0で補わない。
`system_reference_quantity`と`actual_demand_quantity`の単純差を補充精度と呼ばない。補充量の妥当性は
開始在庫、安全在庫、入出庫、欠品、期限切れを含むOperational KPIで評価する。

## 13. Forecast KPI

同じPilot scope、同じas-of締切、同じ評価期間で次を算出する。

- WAPE: `sum(abs(forecast - actual)) / sum(actual)`。分母0は未算出
- MAE
- RMSE
- Bias: `sum(forecast - actual) / sum(actual)`
- horizon別、商品別、倉庫別の成功率

既存のown / common / official集合、POINT / quantile、欠測 / 確定ゼロの区別を維持する。

## 14. Operational KPI

- 欠品数量、欠品発生日数
- 賞味期限切れ数量、期限内未消化数量
- 倉庫間移動数量・回数
- 担当者修正率、修正数量、reason code比率
- System案採用時の見込みOutcomeとOperator案の見込みOutcome
- 実績到着率、実績確定までの日数

3つの最上位KPIは、在庫切れ防止、賞味期限切れ・廃棄防止、倉庫間移動防止である。需要予測指標だけで
Gateを昇格させない。

## 15. Weekly Review

毎週、Pilot scopeと集計versionを固定して次を確認する。

1. Forecast KPIと前週差
2. 担当者修正率、修正数量、reason code上位
3. 欠品、期限切れ、倉庫間移動
4. データ欠測、遅延、隔離、identity不一致
5. System / Operator / Actualの比較可能件数
6. 次週に調査するlearning candidate

週次レポートは過去版を上書きしない。商品名は認可済み画面で解決し、Repositoryや一般audit logへ
出力しない。

## 16. Learning Candidate

Reason CodeとOutcomeから改善候補を集計するが、自動学習しない。

| 観測 | 候補 | 人間の確認 |
|---|---|---|
| `PROMOTION` / `SEASONAL_EVENT`修正が継続 | 販促・季節特徴の追加 | データ取得可能性、未来情報のknown_at |
| `EXPECTED_LARGE_ORDER`が継続 | 大口予定入力 | 確定時刻、取消・訂正版 |
| `PRODUCTION_CONSTRAINT`が継続 | 生産予定連携を優先 | 工場、完成時刻、CASE、取消key |
| `DELIVERY_CONSTRAINT`が継続 | Route Policy改善 | min / standard / maxと採用basis |
| `EXPIRY_CONCERN`が継続 | FEFO・期限risk policy改善 | bucket品質、期限不明の扱い |
| `DATA_ERROR`が継続 | mapping / source品質改善 | 原本訂正、隔離rule |

候補は根拠件数と影響数量を持ち、担当者がAPPROVEした後に別versionのモデル・policy変更へ進める。

## 17. Phase 3T分割

### Phase 3T-A: Warehouse Projection

入力: APPROVED warehouse snapshot、forecast、snapshot time、JAN/location、identity bridge、scope。

出力: 日別予測需要、日別予測在庫、不足見込み日、不足見込み数量。FACTORY供給可能性は出力しない。

### Phase 3T-B: Expiry / FEFO Simulation

入力: EXPIRY_BUCKET、forecast demand、scope、policy。

出力: 賞味期限順消化、期限内未消化数量、期限切れrisk。期限不明を通常bucketへ混ぜない。

### Phase 3T-C: Factory Supply Projection

入力: FACTORY inventory、生産予定。

出力: 工場将来在庫、出荷可能数量。現在は実データ不足により業務受入BLOCKED。

### Phase 3T-D: Route / Arrival Projection

入力: Factory、Warehouse、版付きlead time policy。

出力: arrival_at、arrival-time inventory。現在はFACTORYとroute未確定により業務受入BLOCKED。

3T-A、3T-Bは独立した純粋計算として**実装開始可能**である。

## 18. 現場画面の最小案

Pilot商品×倉庫を1行とし、次を表示する。

- 商品、倉庫、現在庫
- 7日・14日需要予測
- 予測在庫、不足見込み
- 賞味期限注意数量
- 参考補充量
- 担当者判断、担当者数量、理由

主要操作は「そのまま」「増やす」「減らす」「使わない」の4つとし、理由は選択式にする。
Shadowでは上部と各数量へ`参考値・検証中・出荷指示ではありません`を常時表示する。本PhaseではUIを
実装しない。

## 19. 現場導入Gate

### Shadow Gate

STARTABLE条件:

- 10〜20商品の正式Pilot Scopeとidentity bridge
- 正式Location / Input Mapping / Snapshot Time Policy
- scope付きAPPROVED Snapshotとas-of Read
- 3T-A、3T-Bの決定的結果と人工・実データ受入
- Feedback Ledgerと後日Actual接続
- 参考値表示、権限、audit、日次再実行手順

現在: **BLOCKED**。解除可能な阻害要因であり、FACTORY在庫は絶対条件にしない。

### Advisory Gate

STARTABLE条件:

- Shadowを合意期間運用し、System / Operator / Actualが十分に揃う
- Forecast KPIとOperational KPIの基準を業務承認
- 3T-C / 3T-Dまたは供給制約を明示した代替policy
- 推奨の採用・修正・不採用と責任分界を確定

現在: **BLOCKED**。

### Operational Gate

STARTABLE条件:

- Advisory実績、運用SLA、障害時手順、教育、週次reviewが定着
- 商品・倉庫単位の昇格decisionとrollback
- 欠品、期限切れ、倉庫間移動の悪化がないことを業務承認

現在: **BLOCKED**。完全自動出荷は対象外である。

## 20. 必要な次実装

ファイル肥大化を避け、次のmoduleへ分ける。

| 順序 | slice | module | 完成条件 |
|---:|---|---|---|
| 1 | Phase 3T-A-0 Pilot Gate Foundation | `pilot_scope/`, `inventory_forecast_bridge/`, `field_learning/` | scope付きsnapshot、identity、Feedback契約を人工fixtureで固定 |
| 2 | Phase 3T-A Warehouse Projection | `warehouse_projection/` | 日別在庫と不足を決定的に計算 |
| 3 | Phase 3T-B Expiry / FEFO | `expiry_simulation/` | bucket別消化と未消化riskを計算 |
| 4 | Shadow最小UI / Actual取込 | `field_ui/`, `field_actuals/` | 15商品の日次比較と週次review |
| 5 | Phase 3T-C / 3T-D | 独立module | 工場・生産・routeデータ受入後 |

進捗（2026-09-27）：3T-Bの14日Shadow FEFO試算を実装。業務ポリシー値は計算ごとに確認して明示指定する。結果の意味と未対応の供給・輸送計算は[Phase 3T-B](../docs/Phase3TB_Expiry_FEFO.md)を参照。
進捗（2026-09-28）：後日ActualのCSV取込を実装。Shadow最小UI、reference case自動生成、週次reviewは未実装。詳細は[後日実績CSV取込](../docs/Phase3T_Field_Actual_Import.md)を参照。
進捗（2026-09-28）：[倉庫Shadow確認画面](../docs/Phase3T_Shadow_Readonly_UI.md)を実装。Projection・FEFOを参考表示するが、補充量policy未確定のためreference case自動生成・担当者判断UI・週次reviewは未実装。
進捗（2026-09-28）：[Shadow参考補充量](../docs/Phase3T_Shadow_Reference_Policy.md)の明示policy・dry-run・原子的case登録を追加。業務値の自動決定や現場承認は行わず、担当者判断UI・週次review・実データ受入は未実施。

既存`inventory_foundation`、予測run、操作telemetryへFeedback責務を混入させない。

## 21. クライアントへ追加確認する事項

1. まずPilot 15商品の商品コード→JANを正式承認できるか。
2. 既存canonical productとJANの正式version・有効期間は何か。
3. 2倉庫の正式名称、forecast centerとの対応、有効期間を承認できるか。
4. 在庫ファイルの日付が表す業務時点、正式締め時刻、timezoneは何か。
5. 原本完全一致行は重複か、別明細として加算すべきか。
6. 賞味期限欠損行を再取得できるか。Pilot対象日に欠損した場合は停止でよいか。
7. Shadowで担当者の独立数量をシステム表示前に取得できるか。
8. 実出荷、需要、欠品、期限切れ、倉庫間移動の取得元・確定時刻・訂正方法は何か。
9. Weekly Reviewの担当者、曜日、昇格基準、最低観測期間は何か。
10. 自由記述commentの閲覧権限と保持期間は何か。
11. FACTORY在庫、生産予定、route policyをいつ・どの形式で取得できるか。

## 22. 今回実装しないもの

Projection Engine、FEFO消費、Risk Engine、Shipment Recommendation、本格UI、自動学習、自動出荷は
実装していない。実データをDBへ正式登録せず、業務値をRepositoryへcommitしていない。

## 23. 最終報告

- Branch: `codex/phase3s12-field-learning-plan`
- Commit: PR作成時に確定
- PR: PR作成時に確定
- 実データ再確認: **INCOMPLETE**（原本匿名再走査は完了、正式version適用は未完了）
- READY商品: **0件**
- CONDITIONAL商品: **130件**
- BLOCKED商品: **17件**
- 3T-A: **STARTABLE**（実装開始判定）
- 3T-B: **STARTABLE**（実装開始判定）
- Shadow Mode: **BLOCKED**
- Advisory Mode: **BLOCKED**
- Operational Mode: **BLOCKED**
- 次に実装すべきPhase: **Phase 3T-A-0 Pilot Gate Foundation**
- 現場Pilot推奨商品数: **15件**
- 最大の阻害要因: **正式なPilot Scope / identity bridge / APPROVED Snapshotがなく、現行Strict Workerでは部分商品だけの正式snapshotを作れないこと**

本Phaseは計画とGate判定で停止する。
