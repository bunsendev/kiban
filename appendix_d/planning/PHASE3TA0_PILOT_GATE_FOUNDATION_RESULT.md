# Phase 3T-A-0 Pilot Gate Foundation 実装結果

## 1. ゴール

Phase 3S-12で特定した3つの阻害要因を、Warehouse Projectionより先に固定した。

1. 10〜20商品の版付きPilot Scope
2. 在庫`JAN × warehouse_id`と予測`canonical_product_id × center_id`のidentity bridge
3. System参考値、担当者判断、後日実績を分けるFeedback Ledger

実データ、実JAN、倉庫名、担当者名はRepositoryへ保存していない。本実装だけではShadow運用を開始せず、
参考値を正式な出荷指示として扱わない。

## 2. モジュール構成

| module | 責務 |
|---|---|
| `forecast_provider/pilot_scope/` | Pilot版、対象JAN×倉庫、適用期間、部分snapshot照合 |
| `forecast_provider/inventory_forecast_bridge/` | JAN/locationとcanonical product/centerの時点接続 |
| `forecast_provider/field_learning/` | reference case、担当者判断event、Actual event |

各moduleをdomain、store、schemaへ分割した。既存`inventory_foundation`、予測run、匿名操作telemetryへ
責務を追加していない。

## 3. Pilot Scope

- `PILOT_PARTIAL`を固定し、10〜20種類のJANを必須とする。
- 対象は`JAN × warehouse_id`で保持し、適用開始日・終了日、承認者、理由を内容hashで版にする。
- 同一内容は入力順に関係なく同じversionとなる。
- 原本、対象内、対象外、対象内隔離の行数とCASE数量を別々に保持する。
- 行数または数量が一致しない照合、対象内隔離がある照合は正式なscope付きsnapshot参照にできない。
- 既存inventory snapshotを変更せず、`pilot_scoped_snapshot_references`で
  `inventory_snapshot_id × pilot_scope_version × reconciliation`を結ぶ。
- scope外bucketやsource SHA-256・数量不一致を拒否し、部分在庫を全在庫として扱わない。

## 4. Identity Bridge

- `JAN × warehouse_id`から`canonical_product_id × forecast_center_id`を解決する。
- mappingの有効期間とbridge作成時刻を固定する。
- `known_at`時点で未作成のversion、該当なし、複数候補をそれぞれ固定codeで停止する。
- 後日登録したmappingを過去のreference caseへ遡及適用しない。

## 5. Feedback Ledger

### Reference case

業務日、JAN、canonical product、倉庫、forecast center、forecast run、inventory snapshot、scope、
identity bridge、system forecast、system reference、policy、mode、known_atを内容hashで固定する。
Serviceはscope対象とidentity解決を検証してから保存する。

### Operator decision

`OBSERVED`、`ACCEPTED`、`INCREASED`、`DECREASED`、`REJECTED`、`NO_ACTION`をrevision付きで追記する。
増減・不採用は固定reason codeを必須とし、`OTHER`は500文字以下のcommentを必須とする。
古い`expected_revision`による上書きを拒否する。

### Actual outcome

出荷、需要、欠品、期限切れ、倉庫間移動を独立したnullable Decimal CASEとして保持する。
欠測を0へ変換せず、確定ゼロだけ文字列`0`として保存する。訂正はsource version、source SHA-256、
revision、known_atを持つ新しいeventとして追記する。

## 6. 安全境界

- Serviceの既定許可modeは`SHADOW`だけ。Advisory / OperationalはGate解除時に明示設定する。
- Feedbackからモデル、特徴量、policyを自動更新する処理はない。
- Reference、Operator、Actualを同じ可変行へ統合しない。
- 数量へbinary floatを使わず、すべて非負Decimal CASEとする。
- SQLiteとPostgreSQLで同じadditive schemaとStore contractを提供する。

## 7. 検証

人工fixtureで次を確認した。

- scope hashの決定性と10〜20商品制約
- 原本・対象内・対象外・隔離の行数・数量照合
- 部分snapshotのscope外bucket、隔離、source SHA-256、数量不一致拒否
- identityの有効期間、known_at、未登録・曖昧判定
- scope外reference、未許可modeの拒否
- 担当者判断の数量規則、reason、revision競合、追記履歴
- Actualの欠測と確定ゼロ、訂正revisionの保持

## 8. 次工程

次は`Phase 3T-A Warehouse Projection`へ進む前に、正式な15商品scope / identity CSV登録adapterと、
既存Inventory Snapshot Workerのscope-aware intakeを接続する。現時点のscope付きsnapshotは正式契約と
永続化境界までであり、実CSVから自動生成する運用経路は未接続である。

その後、APPROVED scope付きsnapshotと同一as-ofのforecastを入力として、WAREHOUSE日別予測在庫、
不足見込み日、7日・14日需要、参考補充量を決定的に計算する3T-Aへ進む。
