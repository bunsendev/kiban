# Phase 3S-8 商品mapping正式台帳 実装結果

## ゴール

Phase 3S-7の確認済みJAN対応表を、Phase 3Sの`ProductMappingRecord`とInventory Snapshot Workerへ接続できるようにする。候補生成、業務確認、正式登録の境界を維持し、未確認値や架空のcanonical商品を正式入力へ混入させない。

## 実装結果

- `inventory_product_mapping_versions`と`inventory_product_mappings`を追加した。
- UTF-8の確認済みCSVを検証し、商品コード・JAN・canonical商品IDから決定的なversionを生成するadapterを追加した。
- SQLite/PostgreSQL共通の専用store mixinへ登録・version取得・レコード取得を分離した。
- Inventory Snapshot Workerは入力mappingが指定する商品mapping versionを自動取得する。
- 既存の2引数resolver factoryとの互換性を維持した。
- SQLite/PostgreSQLを選べる登録CLIを追加した。
- 商品名、行順、作成日時をmapping内容hashへ含めず、業務上同じ対応関係から同じversionを再現する。

## 安全性

- `確認メモ`が1行でも`確認済み`でなければ登録前に拒否する。
- 商品コード欠損、JAN欠損、不正JAN、商品コード重複を拒否する。
- 商品名は確認用のまま正式台帳へ複写しない。
- CLIの標準出力へ商品コード、商品名、JANを出さない。
- canonical商品が未確定でも架空IDを作らずNULLで保持する。
- 実CSV、実商品、実JANをRepositoryへ保存していない。

## 互換性

既存schemaの削除・rename・意味変更はない。`ProductMappingRecord`のcanonical商品IDだけをnullableへ拡張し、既存の文字列指定は従来どおり有効である。既存の2引数resolver factoryも引き続き利用できる。

## テスト

- 同一対応関係から同じversionを生成
- 行順と商品名変更の影響を排除
- 既存canonical商品IDの再利用
- 未確認、欠損、不正JAN、重複の拒否
- 版metadataとレコードのSQLite round trip
- 同一内容の再登録は冪等、同一versionの内容変更は拒否
- WorkerによるDB mapping自動取得とsnapshotへのversion・canonical ID保持
- 既存Phase 3S-1〜3S-3回帰

## 残タスク

1. 担当者が一意候補130件を確認する。
2. 複数候補15件を正式商品マスター等で解決する。
3. 候補なし2件へ正式JANを補う。
4. 全147行を`確認済み`にして正式台帳へ登録する。
5. 生成されたversionを`InventoryInputMappingVersion`へ設定する。
6. Phase 3S-6 Strict Validationを再実行する。

コード側の登録経路は完成したが、実データの業務確認が未完了であるため、実商品mappingの登録とStrict Validationは実施していない。
