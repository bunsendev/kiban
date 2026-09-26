# Phase 3S-10 確認済みInventory Input Mapping取込

## 目的

在庫CSVの列、文字コード、商品・location master版、CASE単位、snapshot日時列を1つの正式versionとして固定する。商品mappingとlocation masterの確認を省略せず、存在しないversionを参照する設定は登録しない。

## CSV形式

UTF-8 BOM付きCSVを次の列順で1行だけ作成する。

```csv
商品列,商品識別種別,商品mapping版,拠点列,location master版,賞味期限列,数量列,snapshot日時列,原本数量列名,原本単位表記,正規化単位,文字コード,区切り文字,header行,確認メモ
商品コード,PRODUCT_CODE,inventory-product-map-<正式hash>,明細倉庫コード,inventory-location-map-<正式hash>,賞味期限,明細バラ数,基準日時,明細バラ数,箱,CASE,cp932,COMMA,1,確認済み
```

`<正式hash>`は説明用のplaceholderであり、そのまま登録しない。Phase 3S-8と3S-9で実際に登録したversionを使用する。

## 固定する契約

- 商品識別種別は`JAN`または`PRODUCT_CODE`
- `PRODUCT_CODE`では登録済みの商品mapping版が必須
- `JAN`では商品mapping版を空欄にする
- location master版は登録済みの正式versionが必須
- 正規化単位はV1では`CASE`だけ
- 文字コードは`utf-8`、`utf-8-sig`、`cp932`
- 区切り文字は`COMMA`または`TAB`
- header行は1以上の整数
- 確認メモは`確認済み`

mapping versionは上記の設定値をcanonical JSONにし、SHA-256から決定する。作成者、理由、作成日時は内容hashへ含めない。同じ契約は再登録しても同じversionになる。

## 登録コマンド

SQLiteの例:

```powershell
kiban-inventory-input-mapping-import `
  --sqlite .kiban/inventory-foundation.sqlite3 `
  --csv <確認済み-input-mapping.csv> `
  --created-by <担当者ID> `
  --reason "在庫CSV契約確認済み"
```

PostgreSQLでは`--sqlite`の代わりに`--postgres-dsn`を指定する。商品mappingとlocation masterを同じDBへ先に登録する。成功時はmapping version、checksum、参照version、識別種別、CASE、作成情報だけをJSONで表示し、業務行や在庫値を表示しない。

## 実データに残る確認

提供済み在庫CSVには正式なsnapshot日時列がなく、Phase 3S-6ではファイル名の日付を検証用に一時追加した。正式mappingは実在する列を指定するため、現状の実CSVに対して架空の`基準日時`列を指定してはいけない。

次のいずれかを業務確認後に選ぶ必要がある。

1. 上流側でtimezone付きsnapshot日時列をCSVへ追加する。
2. ファイル名日付、正式な締め時刻、timezoneを版付き規則として取り込むadapterを追加する。

締め時刻とtimezoneが未確認のまま日付の0時などを自動設定しない。この確認が終わるまで、実データ用Inventory Input Mappingと正式Snapshotは登録しない。
