# Phase 3S-11 ファイル名日付snapshot時刻policy 実装結果

## ゴール

在庫CSVにsnapshot日時列がなくても、ファイル名の日付と業務確認済みの締め時刻・timezoneから、
再現可能な正式snapshot日時を生成できるようにする。既存の日時列方式は維持する。

## 実装内容

- `COLUMN`と`FILENAME_YYYYMMDD`を明示するsnapshot取得方式を追加した。
- 締め時刻、IANA timezone、作成者、理由を持つ不変なsnapshot時刻policy台帳を追加した。
- `_YYYYMMDD.csv`だけを受理し、policyからUTC日時を決定する純粋変換moduleを追加した。
- Inventory Input Mappingへ取得方式とpolicy版を追加した。
- CSV adapter、Snapshot Service、Workerをpolicy経路へ接続した。
- SQLiteの既存mapping tableを`COLUMN`方式へ無損失移行する処理を追加した。
- PostgreSQLにも追加列と整合性constraintを追加した。
- 確認済みpolicyを登録する`kiban-snapshot-time-policy-import` CLIを追加した。
- Phase 3S-10の旧mapping CSVと旧mapping hashを維持した。

## 安全境界

- 締め時刻、timezone、日付を推測しない。
- policy未登録、不一致、不正ファイル名はCSV全体の契約エラーとする。
- ファイル名方式でCSV内に仮想snapshot列が存在する場合は競合として拒否する。
- DST上で存在しない時刻または一意でない時刻は拒否する。
- CLI結果、テスト、Repositoryへ実データや実ファイル名を保存しない。

## テスト

人工fixtureにより次を確認した。

- policy IDの決定性
- `Asia/Tokyo`の明示時刻からUTCへの変換
- 不正日付・不正ファイル名の固定code拒否
- snapshot列なしCSVのWorker完了と正式snapshot保存
- policy未登録mappingの拒否
- 旧`COLUMN`方式の互換性
- 旧SQLite schemaの追加列移行
- 確認済みpolicy / mapping CSVとCLIの安全な出力

## 残る業務確認

実在庫へ適用する正式な締め時刻とtimezoneは、業務担当者の確認が必要である。確認前は実policyと
実mappingを登録しない。過去のdry runで使った09:00 JSTは正式値ではない。

確認後は、policy登録、拡張mapping登録、実データdry run、正式Snapshot Workerの順に進める。
