# Phase 1J 実装結果

## 達成したゴール

予定された論理ファイルと採用済み正規化行からcenter×日付の完全性を求め、JAN有効期間、商品×center取扱期間、確認済み休業日を使って6種類の日次状態を決定できるようにした。日次buildは全上流版・選定系列・期間・availability modeを凍結し、独立Workerが決定的CSVを生成して不変dataset snapshotをcatalogへ登録する。

## 実装

- 予定ファイル定義、日次buildを正規化JSONのSHA-256で内容アドレス化した。
- 必要論理path、採用原本、正規化状態、隔離行、center、対象範囲、利用可能時刻を完全性条件にした。
- 予定0件、未到着、部分到着、隔離、0確定権限なしを区別し、欠測を0へ変換しない。
- `OBSERVED`、`CONFIRMED_ZERO`、`MISSING`、`NOT_HANDLED`、`CLOSED`、`PARTIAL_OR_INVALID`を全暦日に保存した。
- 休業日をavailable_at・承認者・理由・版付きで不変保存し、as_of以前の情報だけを使用した。
- 休業日の実出荷は消さず、数量を保持して`SHIPMENT_ON_CLOSED_DAY`を記録した。
- 日次CSV、SHA-256、上流provenance付きcatalog snapshotを決定的に発行した。
- SQLiteとPostgreSQL台帳、PostgreSQLの`SKIP LOCKED` claim、既存開発表の安全な列追加を実装した。
- Bearer認証付きAPI、独立`kiban-daily-worker`、Compose serviceを追加した。
- baseline snapshot読込時に休業・未取扱・未到着・不完全値を学習/評価用の欠測へ変換し、確定0だけを0として残した。

## モジュール構成

永続契約、入力検証、上流読出し、完全性、JAN集計、休業時点選択、状態決定、CSV出力、snapshot manifest、DB行変換、SQLite/PostgreSQL台帳、processor、CLI、HTTP schema、routeを別moduleへ分けた。新規本体moduleは最大約250行、適合試験も共通fixture・単体・E2E・PostgreSQLへ分割した。

## 検証

- pytest全302件。
- ruff全件。
- PostgreSQL 17実DBで原本取込から日次snapshot発行まで確認。
- FastAPIと日次WorkerのDocker imageをbuildし、health・route・CLIを確認。
- 別Python processのSQLite Workerで6状態とsnapshotを確認。
- 同じ入力からbuild ID、CSV checksum、snapshot IDが再現することを確認。
- 人工データdemo、100系列scale、artifact別process復元、wheel同梱、配布checksumを確認。

## 後続

実データ3〜5品目の業務受入、重要品目選定、2つ目のOSS、UI、月次再学習、本番のrole/TLS/監視を後続とする。ASSUMEDは実到着時刻を再現せず、OBSERVEDの空ファイルは原本取込時刻を到着根拠にする。日次Workerのlease・停止job回収も運用強化で追加する。
