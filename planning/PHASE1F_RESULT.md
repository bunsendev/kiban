# Phase 1F 実装結果

## 結果

dataset snapshotと実験定義を版付き・内容アドレス方式でSQLite/PostgreSQLへ不変保存するcatalogを追加した。run APIは保存済みexperiment IDだけを受け取り、snapshot契約から起点と予測予定をサーバー側で生成する。

## 実行と再現性

- builtin baseline executorがsnapshot checksumを検証し、Phase 1B ModelRef/ContextRefを保存・復元する。
- 動的な将来特徴量はURI・SHA-256・known_at付き版テーブルを必須とする。
- 別Workerプロセス間で同一model artifactを復元し、再fitせず後続起点を処理する。
- result APIは予測、失敗、model/context artifact参照を返す。
- 改ざんされたsnapshotは失敗として台帳へ記録し、予測値を残さない。

## 互換性

catalog schemaは既存run台帳へ追加適用できる。既存のRunStore境界、lease、attempt fencing、cancel/resumeを維持した。任意のorigin plan、module、コードをAPIから指定できない。

## 検証

最終件数とコマンド結果は`appendix_d/test_results.txt`に記録する。PostgreSQL実DBとCompose実起動は利用可能なDocker/DSNがある環境で追加確認する。

## 未対応

データupload・訂正ワークフロー、原本取込・JAN名寄せ、role別認可、Web UI、分散queue、2方式目のOSS、本番運用構成。
