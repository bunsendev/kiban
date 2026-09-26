# Phase 3S-8 確認済み商品mapping台帳

## 目的

Phase 3S-7で作成した確認用JAN対応表を、Inventory Foundationが実際に利用する版付き商品mappingへ登録する。確認支援の候補を自動承認せず、CSVの全行で`確認メモ=確認済み`になった場合だけ登録する。

## 登録条件

CSVはUTF-8 BOM付きで、列を次の順序にする。

```csv
商品コード,商品名,JAN,確認メモ
P-001,人工商品A,4901234567894,確認済み
```

- 商品コードとJANは全行必須
- JANは8桁または13桁でcheck digitが正しい
- 商品コードはmapping内で一意
- 確認メモは全行が完全に`確認済み`
- 最大5 MiB、10,000行

商品名は担当者の確認用であり、正式mappingの同一性には含めない。正式versionは商品コード、JAN、既存canonical商品IDの組み合わせを商品コード順に並べたcanonical JSONのSHA-256から決まる。同じ対応関係は行順や商品名が変わっても同じversionになる。

## 登録方法

SQLiteの例:

```powershell
kiban-product-mapping-import `
  --sqlite .kiban/inventory-foundation.sqlite3 `
  --csv <確認済みJAN対応表.csv> `
  --created-by <担当者ID> `
  --reason "商品マスター照合済み"
```

PostgreSQLでは`--sqlite`の代わりに`--postgres-dsn`を指定する。`--source-reference`を省略すると、元CSVのSHA-256から値を生成し、OS上のファイルpathを台帳へ保存しない。

成功時は次だけをJSONで表示する。

- `product_mapping_version`
- `content_sha256`
- `row_count`
- `source_reference`
- 作成者、理由、作成日時
- canonical商品接続件数

商品コード、商品名、JANは標準出力へ表示しない。

## canonical商品との関係

商品コード→JANの確認と、JAN変更を跨ぐcanonical商品の確定は別の業務判断である。既存masterでJAN→canonical商品が確定している場合はadapterへその対応を渡して再利用できる。未確定の場合は`canonical_product_id=NULL`で保存し、JANによるInventory Snapshot作成を継続する。架空のcanonical商品IDは生成しない。

## Worker接続

`InventoryInputMappingVersion`で`product_identifier_kind=PRODUCT_CODE`と正式な`product_mapping_version`を指定する。Inventory Snapshot Workerは同versionのレコードだけをDBから読み込む。対応がない商品コードは従来どおり`PRODUCT_MAPPING_MISSING`、同一コードが曖昧な場合は`PRODUCT_MAPPING_AMBIGUOUS`として隔離し、正式snapshotへ混入させない。

## 運用上の現在地

台帳とWorker接続は実装済みである。実データ147商品の正式登録は、担当者が一意候補130件を確認し、複数候補15件と候補なし2件を解決して、全147行を`確認済み`にした後に行う。未確認候補CSVを正式台帳へ登録してはいけない。
