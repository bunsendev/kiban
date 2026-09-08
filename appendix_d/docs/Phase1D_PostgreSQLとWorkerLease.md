# Phase 1D PostgreSQLとWorker lease

Phase 1DはRunStoreのPostgreSQL実装と、複数Workerが安全に起点を取得・延長・回収する契約を追加する。

## PostgreSQL

`forecast_provider/jobs/migrations/001_run_ledger.sql`はrun、起点、予定、予測値、失敗を正規化して保存する。日付・時刻・予測種別・quantile・horizon・非負補正・外部キー・POINT/QUANTILE一意制約をDBでも検査する。

`PostgresRunStore`は利用時だけpsycopgを読み込む。インストールは`pip install -e ".[postgres]"`。起点claimは短いtransaction内で`FOR UPDATE SKIP LOCKED`を使い、同時Workerが同じ起点を取得しない。

ローカル確認はDockerが利用できる環境で`docker compose up -d postgres`を実行し、`KIBAN_TEST_POSTGRES_DSN=postgresql://kiban:local-development-only@localhost:55432/kiban`を設定してpytestを実行する。パスワードはローカル開発専用で、本番資格情報には使用しない。

## leaseとheartbeat

claim時にworker ID、UUID lease token、期限を保存する。完了・失敗・heartbeatはrun、origin、attempt、worker ID、tokenの全一致を必要とする。実行中Workerはlease期間の約3分の1ごとにheartbeatし、期限切れ起点はQUEUEDへ回収され、次のclaimでattemptが増える。旧Workerの遅延書込みはStaleLeaseErrorになる。

## timeoutとキャンセル

起点executorはdaemon threadで実行し、既定600秒を超えるとTimeoutProviderErrorとして失敗台帳へ記録する。遅れて返った結果はstoreへ渡さない。これはDB二重出力を防ぐ境界であり、CPU・メモリをOSレベルで停止する隔離ではない。キャンセル要求後は次起点をclaimしない。

## 検証上の制限

開発端末にDocker/PostgreSQLがない場合、PostgreSQL実DB適合試験はskipされる。migration内容、psycopg境界、SQLiteで共有するlease契約は通常テストで検証する。本番移行前にPostgreSQLを起動したCIで適合試験を必須化する。
