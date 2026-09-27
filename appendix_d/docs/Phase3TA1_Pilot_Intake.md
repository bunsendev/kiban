# Phase 3T-A-1 Pilot対象の登録と在庫CSV取込

この経路は、正式に確認された10〜20商品のJAN×倉庫だけを、原本CSVから部分的に取り込む。
生成物は`PILOT_PARTIAL`であり、全社・全商品の在庫として参照しない。実データの登録・承認は
担当者の業務確認後に行う。原本CSVと確認用CSVをGitへ追加しない。

## 事前条件

Phase 3S-8〜3S-11の正式な商品mapping、location master、Inventory Input Mapping、
snapshot時刻policyを登録しておく。`known_at`はPilot ScopeとIntakeの登録後の時刻を指定する。
原本CSVの日時・数量は既存mappingの契約に従う。数量は正規化後`CASE`として扱う。

## 確認用CSV

すべてUTF-8で保存し、最後の列は全行`確認済み`にする。列名・列順は固定。

| 登録対象 | 列 |
| --- | --- |
| Scope | `JAN,warehouse_id,確認メモ` |
| Intake | `原本商品値,原本拠点コード,JAN,warehouse_id,確認メモ` |
| 予測identity bridge | `JAN,warehouse_id,canonical_product_id,forecast_center_id,effective_from,effective_to,確認メモ` |

Intakeの原本値は在庫CSVに実際に現れる値を記入する。対象JAN×倉庫をすべて網羅し、
登録済みの商品・拠点mappingとの一致を確認する。bridgeのIDは正式に確認された値だけを記入する。
bridgeは次工程の予測接続用であり、この段階の在庫取込には必須ではない。

## 登録・投入

以下はSQLiteの例。`kiban-pilot-gate`が利用できなければ
`python -m forecast_provider.pilot_gate_import`に置き換える。PostgreSQLでは
`--sqlite <DB>`を`--postgres-dsn <DSN>`に置き換える。出力のversionを次のコマンドへ渡す。

```powershell
kiban-pilot-gate --sqlite pilot.sqlite3 scope --csv scope.csv --effective-from 2026-10-01 --approved-by 担当者 --reason 業務確認
kiban-pilot-gate --sqlite pilot.sqlite3 bridge --csv bridge.csv --created-by 担当者 --reason 業務確認
kiban-pilot-gate --sqlite pilot.sqlite3 intake --csv intake.csv --pilot-scope-version <scope-version> --mapping-version <mapping-version> --created-by 担当者 --reason 原本対応確認
kiban-pilot-gate --sqlite pilot.sqlite3 enqueue --source-root C:\inventory-input --source-reference inventory_20261001.csv --pilot-scope-version <scope-version> --pilot-intake-version <intake-version> --known-at 2026-10-01T12:00:00+09:00 --requested-by 担当者
```

Workerは既存のInventory Snapshot Workerを使用する。対象外行は数量を検証して集計し、
Pilot対象JAN×倉庫の行が原本に一つでも欠ければジョブを失敗させる。数量0は明示的な0行として扱う。
対象内の異常行は隔離して当該Pilot snapshotの生成を止める。対象外の数量が解釈不能な場合は
ジョブを失敗させる。原本と対象内・対象外・隔離の件数と数量はジョブ別照合に記録し、
在庫照合APIの`pilot_scope`にも表示する。隔離行に数量異常がある場合、照合の数量は
**解釈可能な数量のみ**であり、正式snapshotは作らない。

技術的に成功したsnapshotも、業務担当者のAPPROVED decisionまでは正式利用しない。
通常のas-of照会は`PILOT_PARTIAL`を除外し、Pilot利用側はscope versionを明示して参照する。
同じ原本SHA-256・scope・Intake・known_atの再投入は同じジョブIDになる。

## 次工程との境界

Phase 3T-Aは業務APPROVEDの部分snapshotと、同じas-ofの需要予測を入力に倉庫別Projectionを
計算する。bridgeを用いたJAN×倉庫と予測IDの接続、欠測・0の区別、snapshotの版固定が必要。
本工程ではProjection・推奨出荷量・実データ受入判定を実施しない。
