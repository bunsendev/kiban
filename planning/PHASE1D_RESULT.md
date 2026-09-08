# Phase 1D 実装結果

## ゴールと結果

PostgreSQL RunStore、複数Worker向けlease/heartbeat、期限切れ回収、起点timeoutを実装した。DB更新はworker ID・lease token・attemptで所有権を検査し、停止済みWorkerの遅延結果を拒否する。

## 構成

| ファイル | 役割 |
|---|---|
| `jobs/contracts.py` | lease付きRunStore契約 |
| `jobs/postgres_store.py` | psycopg接続とSKIP LOCKED claim |
| `jobs/migrations/001_run_ledger.sql` | PostgreSQL制約・索引 |
| `jobs/sqlite_store.py` | 同じlease契約の参照実装 |
| `jobs/worker.py` | heartbeat、timeout、失敗記録 |
| `compose.yaml` | ローカルPostgreSQL |

## 検証

- pytest: 262 passed、PostgreSQL実DB試験1件skip。
- ruff: All checks passed。
- demo、scale_check、artifact_demo: 成功。
- wheel: migration同梱を確認。
- 配布checksum: 最終生成後に全件一致。

PostgreSQL実DB試験は`KIBAN_TEST_POSTGRES_DSN`指定時に実行する。この端末にはDocker、psql、PostgreSQL serviceがないため、実DB接続だけは未実施。migration構造、パッケージ同梱、共有lease契約、SQLite上の動作は検証済み。

## 未対応

- PostgreSQLを起動するCIでの必須適合ゲート。
- OS/process単位のCPU・メモリ隔離、run全体timeout。
- API/UI、分散queue、費用計測、クラウド運用。

次はHTTPで長時間処理を行わない最小APIと独立worker processを作り、run作成・状態確認・キャンセル・再開をこのRunStoreへ接続する段階が適切。
