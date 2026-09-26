# Phase 3S-9 location master正式取込 実装結果

## ゴール

Phase 3S-6で候補止まりだった2倉庫を、担当者確認後にInventory Foundationの正式location masterへ登録できる経路を追加する。FACTORY、拠点名、有効期間を推測しない。

## 実装結果

- 確認済みlocation master CSVの専用adapterを追加した。
- 拠点コード、名称、種別、有効期間を固定し、入力順に依存しないcontent hashとversionを生成する。
- 拠点コードから安定した内部location IDを生成する。
- SQLite / PostgreSQL共通の登録CLIを追加した。
- location masterとroute policyのstore処理を専用mixinへ分離した。
- 同一内容の再登録は冪等とし、同一versionの内容変更を拒否する。
- 倉庫だけのmaster登録を許可し、FACTORYが必要なroute policyの既存検証は維持した。

## 安全性

- 全行が`確認済み`になるまで登録しない。
- `COMPANY`等の未定義種別、空のコード・名称、不正日付、重複コードを拒否する。
- 実データに存在しないFACTORYを生成しない。
- CLI出力へ拠点コードと名称を含めない。
- 実CSVと実拠点値をRepositoryへ保存していない。

## テスト

- 行順に依存しないversionとchecksum
- FACTORY / WAREHOUSEの型固定
- 決定的な内部location ID
- 未確認、欠損、不正種別、不正日付、重複の拒否
- SQLite round trip、冪等再登録、内容変更拒否
- CLI出力へ業務値を含めないこと
- 既存location / route / Worker回帰

## 残タスク

1. 2倉庫の正式名称、適用開始日、業務承認者を確認する。
2. 確認済みCSVを正式台帳へ登録する。
3. 生成versionをInventory Input Mappingへ設定する。
4. FACTORY在庫の提供元とFACTORYコードを確認する。
5. FACTORY確定後、工場→各倉庫の12〜36時間route policyを登録する。

登録経路は完成したが、実拠点の業務承認が未完了であるため実location masterは登録していない。
