# Phase 3S-10 Inventory Input Mapping正式取込 実装結果

## ゴール

商品、location、賞味期限、数量、snapshot日時、CASE単位、CSV形式を版として固定し、Inventory Snapshot Workerが参照する正式mappingを安全に登録できるようにする。

## 実装結果

- 確認済み1行CSVの専用adapterを追加した。
- 列名、識別種別、参照master版、単位、encoding、delimiter、header行から決定的なversionを生成する。
- SQLite / PostgreSQL共通の登録CLIを追加した。
- 商品コード入力では正式product mapping版の存在を検証する。
- location master版の存在を検証する。
- 同一内容の再登録は冪等とし、同一versionの内容変更を拒否する。
- input mappingのstore処理を専用mixinへ分離した。

## 安全性

- 未確認CSV、複数行、未定義識別種別、不正単位、未対応encoding・delimiterを拒否する。
- `PRODUCT_CODE`で商品mapping版がない設定を拒否する。
- 存在しないproduct / location versionをDB登録時に拒否する。
- 原本の数量列名と正規化後`CASE`を別項目で保持する。
- 実データの締め時刻やtimezoneを推測しない。
- 実CSVと業務値をRepositoryへ保存していない。

## テスト

- 同一契約から同じversionとchecksumを生成
- PRODUCT_CODE、CASE、cp932、COMMA、header行の固定
- 未確認、識別種別、参照版、単位、encoding、delimiter、header行の不正を拒否
- product / location master存在検証
- SQLite round trip、冪等再登録、内容変更拒否
- CLI出力へ業務列名を含めないこと
- 既存Snapshot Worker、API、SQLite / PostgreSQL互換contractの回帰

## 残タスク

1. Phase 3S-8の商品mappingを147商品確認後に正式登録する。
2. Phase 3S-9の2倉庫location masterを正式承認後に登録する。
3. 日次在庫の締め時刻とtimezoneを確認する。
4. snapshot日時列の上流追加、またはファイル名日付規則adapterのどちらを使うか決める。
5. 確認後に実データ用Inventory Input Mappingを登録する。
6. Strict Validationを再実行する。

登録経路は完成した。実データには正式snapshot日時列がないため、締め時刻を推測したmappingは登録していない。
