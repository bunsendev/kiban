# Phase 1D 実装計画

## ゴール

Phase 1CのRunStoreをPostgreSQLへ移植し、複数Workerでも起点を重複実行せず、異常終了・timeout後に安全に回収できる実行基盤を作る。

## 範囲

1. PostgreSQL migrationとpsycopg RunStore。
2. `FOR UPDATE SKIP LOCKED`による競合しないclaim。
3. worker ID、推測不能なlease token、期限、heartbeat、期限切れ回収。
4. 古いlease/attemptの完了・失敗書込み拒否。
5. daemon実行境界による起点timeoutと遅延結果の破棄。
6. ローカルPostgreSQL用Docker Composeと、DSN指定時の適合試験。

## モジュール境界

既存`jobs/contracts.py`へlease契約、`sqlite_store.py`へ参照動作、`postgres_store.py`へPostgreSQL固有接続とclaim、`worker.py`へheartbeat/timeoutを置く。DDLは`jobs/migrations`へ分離する。

## 完了条件

複数Worker排他、heartbeat、期限切れ回収、新attempt、timeout、stale書込み拒否を検証し、既存pytest・ruff・demo・scale・artifact復元・配布checksumを維持する。PostgreSQL実DB試験は`KIBAN_TEST_POSTGRES_DSN`指定環境で同じ起点transactionを確認する。

## 対象外

API/UI、分散queue、run全体timeout、CPU/メモリ強制隔離、費用計測、クラウド運用、原本取込、追加OSS。
