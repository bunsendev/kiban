# 日次出荷・在庫最適化 Gap Analysis

調査日: 2026-09-24
対象Repository: `bunsendev/kiban`
基準Branch: `main`
基準Commit: `29ce80aef923fb0de99d40e547d1e4518faa8f0c`

## 1. 結論

現在のkibanは、出荷実績の取込、商品・倉庫単位の日次需要データ作成、複数OSSによる需要予測、比較、採用、Worker実行、監査までを持つ。需要予測を作る基盤としては利用できる。

一方、最終目的である「今日、どの商品を、どの倉庫へ、何個送るべきか」の算出は未実装である。現在の在庫機能は日付・商品・倉庫・単位・数量の日次集約までであり、会社側在庫、ロット、賞味期限、引当、入庫予定、製造予定を保存しない。将来在庫、欠品、期限切れ、倉庫偏在、推奨出荷数量を計算するDecision Engineも存在しない。

新機能は予測モデルへ組み込まず、次の責務に分ける。

```text
Forecast Engine
  ↓ 需要予測値
Inventory / Supply Ledger
  ↓ 時点付き在庫・予定
Inventory Projection
  ↓ 商品・倉庫・日別の将来在庫
Risk Evaluation
  ↓ 欠品・期限切れ・偏在・会社在庫不足
Shipment Recommendation Engine
  ↓ 本日の商品・倉庫別推奨出荷数量と根拠
Human-in-the-loop
  ↓ 採用・修正・不採用・確定
Actuals / Business KPI
```

最初に実装すべきPhaseは、賞味期限・ロットを失わない時点付き在庫基盤と業務データ契約である。ここを確定せずに推奨数量を実装すると、FEFO、期限切れリスク、会社在庫制約を正しく計算できない。

## 2. 調査範囲

次を確認した。

- `CODEX_START_HERE.md`、統合仕様v2.9、実装仕様v2.2
- Phase 1G〜1Tの取込、日次build、予測、比較、採用、Lifecycle
- Phase 2P〜2Zの在庫診断、正規化、採用、特徴ビュー、CSV発行
- Phase 3A〜3RのAPI契約、分析Worker、比較キャンペーン、レビュー
- PostgreSQL / SQLite schema、store、Worker、UI、テスト
- 提供済み実データのCSVヘッダーと項目充足率。行値は記録していない

今回、大規模な機能実装は行わない。本書は実装可否と設計境界を確定するための調査成果物である。

## 3. 現在地

### 3.1 需要予測基盤

次は実装済みである。

- 原本取込、checksum、重複・訂正版・隔離台帳
- 出荷CSVの版付き列mapping、正規化、数量照合
- JAN名寄せ、canonical product、商品×center取扱期間
- 商品×center×暦日の6種類の日次状態
- `available_at`と`as_of`による時点安全なdataset snapshot
- Baseline、StatsForecast AutoETS、MLForecast Ridge、TimesFM 2.5
- 起点別Run Ledger、Worker lease、再開、timeout、失敗記録
- WAPE、MAE、RMSE、Bias、成功率、比較対象集合
- 比較キャンペーン、モデル安定性、精度変化、レビュー
- モデル採用、champion/challenger、rollback、将来trial
- role別API、OIDC、監査、readiness、バックアップ・復元

Forecast Engineは新しいDecision Engineへの入力として利用できる。予測値から出荷数量を直接出す設計には変更しない。

### 3.2 現在の在庫基盤

Phase 2P〜2Zは次を実装している。

- 在庫CSVの構造・mapping候補診断
- 商品コードからJANへの対応表作成・検査・保存
- 在庫正規化プレビューと全件Worker
- 日付・JAN・倉庫・単位・数量への集約
- 採用数量と正規化数量の照合
- APPROVED / REJECTEDの追記型判断
- JAN有効期間に従うcanonical productへの時点安全な接続
- 在庫特徴ビューとchecksum付きCSV発行台帳

保存粒度は次である。

```text
inventory_date
× JAN / canonical_product_id
× center_id
× unit
× quantity
```

現在の`inventory_daily_quantities`には、location種別、ロット番号、製造日、賞味期限、利用可能数量、引当数量、入庫予定、製造予定がない。Phase 2Xの特徴ビューも同じ集約粒度である。

### 3.3 現在の自動処理

独立Worker、PostgreSQLの`FOR UPDATE SKIP LOCKED`、冪等なrun、heartbeat、失敗記録、再開は利用できる。Lifecycle Schedulerは月次モデルcycleを作成できる。

ただし、毎営業日の業務日を起点に、データ更新、予測、在庫Projection、リスク、推奨数量を一つの処理系列として実行する日次オーケストレーターはない。既存Schedulerは新しいsnapshotや日次出荷推奨を自動生成しない。

## 4. 対応率

| 対象 | 判定 | 根拠 |
|---|---|---|
| 需要予測 | 対応済み | 日次snapshot、4 Provider、Run Ledger、比較、採用、予測値表示を利用できる |
| 会社在庫 | 未対応 | 在庫に`center_id`はあるが、会社・倉庫のlocation種別と会社側出荷可能数量を区別しない |
| 倉庫在庫 | 部分対応 | 商品×倉庫×日×単位×数量を正規化・採用・CSV化できるが、引当・ロット・期限を保持しない |
| 賞味期限 | 未対応 | 原本に列はあるが、現行正規化とDBが保存しない |
| ロット | 未対応 | schemaがなく、提供済み在庫データでは列自体はあるが値は全行空欄 |
| 将来在庫 | 未対応 | 現在庫、入庫、補充、需要を日別に繰り越すProjectionがない |
| 欠品リスク | 未対応 | 不足日、数量、安全在庫、リードタイムの計算がない |
| 期限切れリスク | 未対応 | FEFO消費、期限までの累積需要、未消化数量の計算がない |
| 倉庫偏在 | 未対応 | 複数倉庫の不足・過剰を同時評価する機能がない |
| 日次推奨出荷 | 未対応 | 必要補充量、会社在庫配分、丸め、根拠生成がない |
| 担当者承認 | 部分対応 | モデル・データ採用の追記型承認は再利用可能だが、推奨数量の修正・確定・実績台帳がない |
| 日次自動実行 | 部分対応 | Worker・lease・heartbeat・月次Schedulerはあるが、日次業務フローはない |
| 業務KPI | 未対応 | 予測KPIと資源費用はあるが、欠品・廃棄・倉庫間移動のKPIがない |

## 5. A. 現在利用できる機能

1. **需要履歴の準備**
   出荷原本から商品・倉庫別の日次需要を作り、0、欠測、取扱期間外を区別できる。

2. **需要予測**
   同じsnapshotを複数モデルで実行し、予測値と精度を保存できる。

3. **時点管理**
   `known_at` / `available_at` / `as_of`を使い、締切後の情報を過去の判断へ混入させない設計を利用できる。

4. **ジョブ実行基盤**
   PostgreSQLキュー、複数Worker、lease、heartbeat、timeout、再開、冪等性を利用できる。

5. **不変履歴と監査**
   version、checksum、認証subject、判断理由を追記保存するパターンを利用できる。

6. **認証・権限・運用**
   READ、ANALYZE、APPROVE、EXPORT、ADMIN、OIDC、監査ログ、バックアップ・復元を利用できる。

7. **操作画面の共通部品**
   認証、APIエラー、処理状態、一覧、詳細、判断履歴、CSV取得、操作イベントを再利用できる。

## 6. B. 一部変更で利用できる機能

### 6.1 在庫取込

Phase 2P〜2Zの安全なpath検査、encoding判定、商品対応表、Worker、数量照合、承認、CSV発行は再利用できる。ただし、日次合計へ集約する前に次の明細を保持する拡張が必要である。

- location種別: `COMPANY` / `WAREHOUSE`
- 商品
- location
- lotまたは期限別在庫bucket
- 賞味期限
- 製造日
- on-hand数量
- allocated数量
- available数量
- 単位
- `as_of` / `known_at`

既存の`inventory_daily_quantities`を破壊的に変更せず、新しい明細台帳を追加する。既存集約は互換read modelとして残せる。

### 6.2 Human-in-the-loop

既存の採用判断、champion event、レビューtaskは、認証主体、理由、revision、409競合、不変履歴の設計例として利用できる。出荷推奨専用には次が追加で必要である。

- システム推奨数量
- 担当者修正数量
- 最終確定数量
- 修正・不採用理由
- 実際の出荷数量
- 後日判明した実績需要

### 6.3 日次自動処理

既存Worker基盤とSchedulerの冪等登録パターンは利用できる。新しい日次処理は`business_date + policy_version + input_fingerprint`で一意にし、処理段階ごとの再開点を持たせる必要がある。

### 6.4 UI

かんたん予測画面と分析画面の認証・進捗・エラー表示は利用できる。ただし担当者の朝の業務画面は新規に必要である。予測モデル名やrun IDを主画面へ出さず、「今日対応が必要な商品と倉庫」を優先順に表示する。

## 7. C. 新規実装が必要な機能

- 商品×location×lot×賞味期限の時点付き在庫台帳
- 会社在庫と倉庫在庫のlocationマスター
- 受注、引当、入庫予定、出荷予定、製造予定の時点付き供給・需要イベント
- FEFOによる期限順消費
- 日別の将来在庫Projection
- 欠品、期限切れ、倉庫偏在、会社在庫不足のRisk Engine
- 会社在庫制約と出荷単位を考慮するShipment Recommendation Engine
- 推奨理由の構造化生成
- 推奨・修正・不採用・確定・実績の追記型ワークフロー
- 日次オーケストレーター
- 欠品、廃棄、倉庫間移動の業務KPI
- 担当者向け「今日の推奨」一覧・詳細画面

## 8. D. 賞味期限対応状況

### 8.1 現行実装

未対応である。`inventory_normalization.processor`は`明細バラ数`を日付・JAN・倉庫・単位別に合算し、ロット、製造日、賞味期限を読み取らない。DB schemaと特徴CSVにも該当列はない。

したがって、現在の正規化結果からFEFOや期限内消化可能数量を復元できない。後から集約データへ期限を足すのではなく、原本から新しい明細台帳を作る必要がある。

### 8.2 提供済み実データの確認結果

在庫CSV 1,926ファイル、200,917行を、値を出力せず項目充足だけ集計した。

| 項目 | 非空行 | 充足率 | 判定 |
|---|---:|---:|---|
| 商品コード | 200,917 | 100% | 利用候補 |
| 明細倉庫コード | 200,917 | 100% | 利用候補 |
| 明細バラ数 | 200,917 | 100% | 単位の業務確認が必要 |
| 賞味期限 | 200,840 | 99.962% | 利用候補。77行の欠損理由確認が必要 |
| ロット番号 | 0 | 0% | 現ファイルでは利用不可 |
| 製造年月日 | 0 | 0% | 現ファイルでは利用不可 |
| 明細入荷日 | 0 | 0% | 現ファイルでは利用不可 |
| 事業所コード | 0 | 0% | 会社在庫識別には利用不可 |
| 出荷禁止フラグ | 0 | 0% | 現ファイルでは利用不可 |

賞味期限は`YYYY/MM/DD`または`YYYY-MM-DD`相当の日付と任意の時刻を持つ形式として技術的に解釈可能だった。ロット列は存在するが値がないため、「商品×倉庫×賞味期限」を暫定bucketとして扱うことはできても、正式なロット追跡や実際のピッキング指示には使えない。

Phase 3Sの業務受入前に、ロット番号を別データから取得できるか、倉庫システムが期限bucketだけを管理しているかを確認する。取得できない場合は、`EXPIRY_BUCKET`運用を明示し、ロット単位FEFO対応済みとは判定しない。

## 9. E. 会社側在庫対応状況

未対応である。現在の在庫には`center_id`しかなく、会社在庫、外部倉庫、製造拠点、出荷元を区別するlocation種別がない。

必要補充量と実際に出荷可能な数量は別値として保存する。

```text
required_replenishment_quantity
company_available_quantity
recommended_shippable_quantity
company_shortage_quantity
```

会社在庫不足を倉庫の欠品へ混ぜず、製造計画や供給不足へ連携できる固定risk codeとして残す。

## 10. F. 将来在庫シミュレーション

未実装である。最小のProjectionは商品・倉庫・日単位で次を計算する。

```text
projected_closing_inventory[d]
= projected_opening_inventory[d]
 + confirmed_inbound[d]
 + confirmed_replenishment[d]
 - effective_demand[d]
 - other_committed_outbound[d]
```

`effective_demand`は受注と需要予測を単純加算しない。予測が受注を含むかをデータ契約で固定し、二重計上を防ぐ。例として、予測が総需要の場合は次のような構成を候補とする。

```text
effective_demand = confirmed_orders + max(0, forecast_total - forecast_order_covered)
```

安全在庫、輸送リードタイム、休業日、最低出荷単位は版付きpolicyとして入力する。Projectionは予測run、在庫snapshot、予定event集合、policy versionを固定し、同じ入力から再現できるようにする。

## 11. G. 日次出荷推奨

未実装である。最初のルールベース案は次とする。

1. 倉庫ごとに到着日から補充対象期間末までの有効需要を計算する。
2. 現在庫、引当、確定入庫を反映して安全在庫を下回る数量を`必要補充量`とする。
3. 賞味期限別在庫をFEFOで消費し、期限内に消化できない数量を過剰・廃棄riskとして分ける。
4. 全倉庫の必要補充量を集約する。
5. 会社側の出荷可能在庫を上限として、欠品日、欠品数量、優先度、リードタイムの順で配分する。
6. ケース入数と最低出荷単位で丸め、丸めによる不足・過剰を記録する。
7. 推奨数量と構造化された理由を保存する。

理由はLLMで生成せず、計算根拠を固定codeと数値で保存し、UIで文章化する。

```text
理由code: PROJECTED_STOCK_BELOW_SAFETY
7日需要予測: 650
利用可能在庫: 300
確定入庫: 0
安全在庫: 100
必要補充量: 450
会社側出荷可能在庫: 2,100
推奨出荷数量: 450
```

## 12. H. Human-in-the-loop

業務数量のHuman-in-the-loopは未実装である。モデル採用等の既存パターンを利用し、次のeventを追記保存する。

| event | 内容 |
|---|---|
| `RECOMMENDED` | システムが数量と根拠を提示 |
| `ACCEPTED` | 担当者が推奨どおり採用 |
| `MODIFIED` | 担当者が数量を変更。理由必須 |
| `REJECTED` | 担当者が不採用。理由必須 |
| `CONFIRMED` | 当日の確定数量を固定 |
| `ACTUAL_RECORDED` | 実際の出荷数量を後日記録 |

推奨値を更新せず、修正値と確定値を別eventとして保存する。各eventは認証subject、時刻、期待revisionを持ち、競合を409で拒否する。確定後の訂正は新revisionと理由を必要とする。

## 13. I. 日次自動処理

基盤は部分対応、業務処理は未対応である。

再利用できるもの:

- 独立Worker process
- PostgreSQL job queueとlease
- heartbeatとキュー診断
- 冪等な内容アドレスID
- 失敗code、再開、監査
- 常駐Schedulerの実行形態

新規に必要な日次run状態:

```text
WAITING_FOR_DATA
DATA_READY
FORECAST_QUEUED
FORECAST_READY
PROJECTION_READY
RISK_READY
RECOMMENDATION_READY
AWAITING_CONFIRMATION
CONFIRMED
FAILED
```

自動処理はデータの締切と完全性を満たした場合だけ進める。不完全データを0として処理しない。初期運用では担当者が手動実行できるようにし、入力・出力が安定してから毎日決まった時刻の自動登録を有効にする。

## 14. J. 不足データ（ブンセン側から必要なデータ）

### 14.1 必須

| データ | 必須項目 | 用途・確認事項 |
|---|---|---|
| 商品マスター | 商品コード、JANまたはcanonical対応、商品名、基本単位 | 出荷・在庫・予定を同一商品へ接続 |
| locationマスター | locationコード、名称、`COMPANY` / `WAREHOUSE`、有効期間 | 会社在庫と倉庫在庫を分離 |
| 倉庫在庫snapshot | 基準日時、商品、倉庫、数量、単位、賞味期限、lotまたは期限bucket | FEFO、期限切れrisk、将来在庫 |
| 会社在庫snapshot | 基準日時、商品、出荷元、on-hand、allocated、available、単位、賞味期限 | 出荷可能上限と会社在庫不足 |
| 過去出荷実績 | 出荷日、商品、倉庫、数量、単位 | 需要予測。現行データを利用可能 |
| 最新受注 | 受注日、納品予定日、商品、納入倉庫、数量、状態、known_at | 直近確定需要。予測との重複定義が必要 |
| 引当・出荷予定 | 商品、出荷元、出荷先、予定日、数量、状態、known_at | 利用可能在庫と二重引当防止 |
| 入庫予定 | 商品、入庫先、予定日、数量、状態、known_at | 将来在庫加算 |
| 製造予定 | 商品、完成予定日、会社側入庫先、数量、状態、known_at | 会社側の将来出荷可能数量 |
| 物流policy | 輸送リードタイム、休業日、ケース入数、最低出荷単位 | 到着日と実行可能数量 |
| 安全在庫policy | 商品・倉庫、有効期間、数量または計算規則、承認者 | 必要補充量 |

lot番号は正式なロット単位FEFOと実際のピッキングへ必要である。取得できない場合、賞味期限bucketでの試験は可能だが、正式受入条件を満たさないものとして扱う。

### 14.2 推奨

| データ | 用途 |
|---|---|
| 製造日 | 残存日数、品質調査、期限異常検知 |
| 発注残・調達予定 | 会社側の中期供給不足評価 |
| 商品・倉庫別目標在庫日数 | 安全在庫の業務設定 |
| 商品原価、廃棄単価、販売単価 | 廃棄金額、推定失注金額 |
| 輸送費、距離、便・曜日制約 | 推奨の実行可能性と費用評価 |
| 出荷禁止・品質保留 | 利用可能在庫からの除外 |
| 温度帯、保管制約 | 倉庫・在庫の割当制約 |

### 14.3 将来必要

| データ | 用途 |
|---|---|
| 倉庫間移動実績 | 移動件数、数量、費用KPI |
| 廃棄・期限切れ実績 | 廃棄数量・金額KPI |
| 欠品・受注残・失注実績 | 欠品数量・推定失注KPI |
| 担当者の推奨修正履歴 | policy改善、説明改善 |
| 実際の納品・入庫時刻 | リードタイム実績と遅延risk |
| 販促・価格・得意先イベント | 需要予測の追加特徴候補。効果検証後に採用 |

### 14.4 現在の提供データで不足しているもの

- 会社側在庫として識別できるsnapshot
- locationの会社・倉庫区分
- lot番号の実値
- 利用可能在庫と引当済在庫の区別
- 最新受注、入庫予定、出荷予定、製造予定
- ケース入数、最低出荷単位、輸送リードタイム、安全在庫
- 倉庫間移動、廃棄、欠品・失注の実績

## 15. リスク分類と設定方針

画面表示候補は次とする。

- 正常
- 欠品注意
- 欠品高リスク
- 賞味期限注意
- 廃棄高リスク
- 倉庫偏在注意
- 会社在庫不足

判定値はコードへ固定せず、`risk_policy_version`へ保存する。

- 何日以内の不足を注意・高リスクにするか
- 安全在庫率または数量
- 期限内未消化数量・比率・金額の閾値
- 倉庫間の在庫日数差の閾値
- 会社不足数量の閾値
- リードタイム、休業日、対象期間

判定結果はpolicy版、入力snapshot、Projection run、数値根拠を固定する。閾値変更で過去の判定を書き換えない。

## 16. 推奨するモジュール構成

ファイル肥大化と予測コードへの混入を避けるため、次を独立moduleにする。

| module | 責務 |
|---|---|
| `inventory_lot/` | location、lot・期限在庫、利用可能数量、時点付きsnapshot |
| `supply_events/` | 受注、引当、入庫、出荷、製造予定の共通契約 |
| `inventory_projection/` | 日別ProjectionとFEFO消費。純粋計算をDBから分離 |
| `risk_engine/` | 欠品、期限切れ、偏在、会社不足の版付き判定 |
| `shipment_recommendation/` | 必要補充、会社配分、出荷単位丸め、理由code |
| `shipment_workflow/` | 推奨、修正、不採用、確定、実績の追記event |
| `daily_optimization/` | 日次runと段階別Worker orchestration |
| `business_kpi/` | 導入前・推奨運用の業務KPI |
| `ui/daily_operations/` | 今日の一覧、詳細、確認UI。計算を持たない |

各moduleは`contracts.py`、純粋な`domain.py`、永続化`store.py`、結合検証`service.py`を基本とする。HTTP routeとWorker CLIに業務計算を置かない。

## 17. 推奨Phase構成

既存はPhase 3Rまで使用済みであるため、Phase 3S以降を使う。

### Phase 3S: 賞味期限・ロット在庫基盤と実データ契約

- locationマスターと会社・倉庫区分
- 商品×location×lot/期限×数量の時点付きsnapshot
- on-hand、allocated、availableの分離
- 賞味期限、lot欠損、単位、重複、数量照合
- 既存在庫正規化との互換read model
- FEFO順に参照できるread API
- 実データ項目充足レポートと業務確認

### Phase 3T: 将来在庫Projection

- 受注、引当、入庫、出荷、製造予定のevent契約
- 需要予測runとの接続
- 商品・倉庫・日別在庫推移
- FEFOによる期限別消費
- 安全在庫、リードタイム、休業日policy
- 同一入力からの決定的再現

### Phase 3U: Risk Engine

- 欠品日・欠品数量
- 期限内未消化数量・廃棄risk
- 複数倉庫の在庫日数差・偏在risk
- 会社在庫不足
- 版付き閾値、固定risk code、数値根拠

### Phase 3V: Shipment Recommendation Engine

- 倉庫別必要補充量
- 会社在庫制約下の配分
- ケース入数・最低出荷単位の丸め
- 推奨数量、未充足数量、説明根拠
- ルールベースの決定的計算

### Phase 3W: 担当者確認・修正・確定UI

- 「今日すること」一覧
- 商品・倉庫別詳細、将来需要、将来在庫、期限在庫
- 採用、修正、不採用、確定
- revision競合、理由、認証主体
- 実績出荷の後日記録

### Phase 3X: 日次Batch / Scheduler

- 締切とデータ完全性の確認
- 需要予測から推奨までの段階実行
- 冪等な日次run、再開、heartbeat、通知対象
- 初期は手動起動、受入後に時刻指定を有効化

### Phase 3Y: 業務KPI検証

- 欠品件数・数量・推定失注
- 期限切れ・廃棄数量・金額
- 倉庫間移動件数・数量・費用
- システム導入前と推奨運用の比較
- 推奨、確定、実績需要を結ぶ検証レポート

## 18. 最初に実装すべきPhase

**Phase 3S: 賞味期限・ロット在庫基盤と実データ契約**を最初に実装する。

### 理由

1. 賞味期限は最重要制約だが、現在の処理で失われている。
2. 原本の賞味期限はほぼ利用可能で、既存データから改善を開始できる。
3. ロット、会社在庫区分、引当、利用可能数量は不足しており、推奨計算前に取得方法を決める必要がある。
4. Projection、Risk、Recommendationのすべてが同じ在庫契約に依存する。
5. 既存在庫集約を破壊せず、新しいmoduleとして段階導入できる。

### 完成条件

- 会社・倉庫を区別する版付きlocationマスターがある。
- 商品×location×lotまたは明示した期限bucket×賞味期限×数量を保存できる。
- on-hand、allocated、availableの定義と数量照合がある。
- snapshot日時、`known_at`、原本・mapping・採用判断を追跡できる。
- 賞味期限不正、欠損、lot欠損、負数量、単位不明を固定codeで隔離できる。
- 同じ原本とmappingから同じsnapshot IDとchecksumになる。
- FEFO順のread modelを返せる。
- 会社在庫と倉庫在庫を混ぜない。
- 現行の`inventory_daily_quantities`とPhase 2X〜2Zを壊さない。
- PostgreSQL / SQLite、Worker、API、人工データ試験、実データ項目充足レポートが揃う。
- 実データはGitへ保存せず、人工fixtureで自動試験する。
- lotが取得できない場合は期限bucket modeを明示し、「ロット対応済み」と判定しない。

## 19. 最大のGap

重要度順に5件を示す。

1. **在庫データ契約の不足**
   会社・倉庫区分、lot、賞味期限、allocated、available、予定eventを同じ時点で扱えない。

2. **将来在庫Projectionがない**
   どの日に、どの商品・倉庫が不足または過剰になるかを計算できない。

3. **賞味期限を需要と結び付けたRisk Engineがない**
   残存日数だけでなく、期限までに消化できる数量を判定できない。

4. **会社在庫制約付きShipment Recommendation Engineがない**
   必要補充量と出荷可能数量を分離し、複数倉庫へ配分できない。

5. **日次業務ワークフローと業務KPIがない**
   担当者の修正・確定・実績、欠品・廃棄・倉庫間移動の改善を追跡できない。

## 20. 毎日の画面案

朝の初期画面には、モデルや実験ではなく対応優先順を表示する。

| 表示項目 | 内容 |
|---|---|
| 商品・倉庫 | 担当者が識別できる名称とコード |
| 会社在庫 | 当日出荷可能数量 |
| 倉庫在庫 | on-hand / allocated / available |
| 需要予測 | 補充対象期間の合計と日別詳細 |
| 期限注意在庫 | 期限までに消化できない見込み数量 |
| 推奨出荷数量 | 会社制約と出荷単位反映後 |
| 未充足数量 | 会社在庫不足等で送れない数量 |
| リスク | 欠品、期限切れ、偏在、会社不足 |
| 推奨理由 | 固定reason codeから生成した説明 |
| 操作 | 採用、数量修正、不採用、確定 |

詳細画面には日別需要、日別Projection、賞味期限bucket、会社側配分、丸め前後、根拠数値を表示する。正常行は折りたたみ、対応が必要な行を先に表示する。

## 21. 業務KPI方針

予測KPIと業務KPIを分ける。

### 予測KPI

- WAPE
- MAE
- RMSE
- Bias
- 成功率、被覆率

### 業務KPI

- 欠品件数、数量、推定失注数量・金額
- 期限切れ数量、廃棄数量・金額
- 倉庫間移動件数、数量、費用
- 推奨採用率、修正率、修正量、理由
- 推奨と実際の出荷数量差

業務KPIはモデル単独の成績としない。需要予測run、在庫snapshot、policy、推奨、担当者確定、実績を同じ系譜で結び、導入前と推奨運用期間を比較する。

## 22. 今回実装しないもの

- 完全自動出荷
- 基幹システムへの自動書込み
- 自動発注、製造指示
- LLMによる数量決定
- 複雑な数理最適化
- 不足データを推測して埋める処理
- 担当者確認を省略する自動確定

初期Decision Engineは、版付きルール、需要予測、在庫Projection、説明可能な計算で構成する。

## 23. 調査根拠

- `forecast_provider/inventory_normalization/schema.sql`
- `forecast_provider/inventory_normalization/processor.py`
- `forecast_provider/inventory_normalization/features.py`
- `forecast_provider/daily/contracts.py`
- `forecast_provider/daily/schema.sql`
- `forecast_provider/jobs/`
- `forecast_provider/lifecycle/scheduler.py`
- `forecast_provider/lifecycle/schema.sql`
- `forecast_provider/reporting/schema.sql`
- `forecast_provider/acceptance/schema.sql`
- `forecast_provider/operation_events/schema.sql`
- `docs/Phase1J_予定完全性と日次状態.md`
- `docs/Phase1S_継続学習とモデル切替.md`
- `docs/Phase2P_在庫CSV構造診断.md`〜`docs/Phase2Z_在庫特徴CSV発行台帳.md`

## 24. 完了判定

この調査時点で、kibanは需要予測まで対応済み、倉庫在庫の集約・採用・受渡しまで部分対応、日次出荷・在庫最適化は未対応である。

次工程はPhase 3Sの実装計画を作り、ブンセン側と次を確認してから着手する。

1. 会社在庫データの取得元とlocation区分
2. lot番号を取得できる別データの有無
3. 賞味期限77欠損行の意味
4. `明細バラ数`の単位とケース換算
5. 受注・引当・入庫・出荷・製造予定の取得可否と確定時刻
6. 輸送リードタイム、安全在庫、最低出荷単位
7. 欠品、廃棄、倉庫間移動の実績取得可否

この確認なしに推奨数量を実装しても、業務上正しい出荷提案にならない。
