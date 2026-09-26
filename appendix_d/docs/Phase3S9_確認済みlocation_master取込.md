# Phase 3S-9 確認済みlocation master取込

## 目的

実データPreflightで接続可能と判定した倉庫コードを、Inventory Foundationの正式な版付きlocation masterへ登録する。未確認の拠点名、拠点種別、有効期間、FACTORYを推測して登録しない。

## CSV形式

UTF-8 BOM付きCSVを次の列順で作成する。

```csv
拠点コード,拠点名,拠点種別,適用開始日,適用終了日,確認メモ
W01,人工倉庫A,WAREHOUSE,2026-01-01,,確認済み
F01,人工工場,FACTORY,2026-01-01,,確認済み
```

実データの拠点コードや名称をこの文書の人工例へ置き換えて登録してはいけない。担当者が正式値を入力し、全行を確認した後に使用する。

登録条件は次のとおりである。

- 拠点コードと拠点名は全行必須
- 拠点種別は`FACTORY`または`WAREHOUSE`
- 適用日は`YYYY-MM-DD`
- 適用終了日は空欄可。指定時は適用開始日以降
- 拠点コードはmaster内で一意
- 確認メモは全行が完全に`確認済み`
- 最大1 MiB、10,000行

内部location IDは拠点コードのSHA-256から決定的に生成する。同じ拠点コードはmaster versionが変わっても同じ内部IDになる。location master versionはコード、名称、種別、有効期間をコード順に並べたcanonical JSONのSHA-256から生成する。

## 登録コマンド

SQLiteの例:

```powershell
kiban-location-master-import `
  --sqlite .kiban/inventory-foundation.sqlite3 `
  --csv <確認済みlocation-master.csv> `
  --created-by <担当者ID> `
  --reason "拠点台帳照合済み"
```

PostgreSQLでは`--sqlite`の代わりに`--postgres-dsn`を指定する。成功時のJSONはversion、checksum、全件数、FACTORY件数、WAREHOUSE件数、作成情報だけを返し、拠点コードや名称を標準出力へ表示しない。同じ内容の再実行は同じversionへ収束する。

## 現在地

実データPreflightでは2種類の倉庫コードへ全200,917行を接続できたが、正式名称、有効期間、業務承認は未完了である。Phase 3S-9は登録経路を完成させた段階であり、実location masterは担当者確認後に登録する。

FACTORY在庫とFACTORYコードは提供データで確認できていない。倉庫だけのmasterは登録できるが、工場→倉庫route lead time policyはFACTORY確定後に作成する。架空のFACTORYは追加しない。
