# Phase 1C 実装計画

## ゴール

run・起点・予定・予測・失敗・artifact参照を同じ台帳から追跡し、Worker停止後に同じ条件のrunを起点境界から安全に再開する。成功済み起点を再実行せず、古いattemptや部分出力による二重登録を防ぐ。

## まとめる範囲

1. 製品非依存のRunStore、実行定義、起点lease、予測結果の型。
2. SQLite参照実装と、run/origin/expectation/value/failureの正規化テーブル。
3. 起点単位transactionによる必要POINT、予測値、状態、model/context artifact参照の同時確定。
4. 中断起点の再取得、成功起点の再利用、condition fingerprint照合、attempt fencing。
5. retryableなProviderErrorだけを最大3 attemptまで再試行し、未分類例外と契約違反は自動再試行しないWorker。
6. cancellation要求後に次の起点を開始しない状態遷移。

## モジュール境界

- `jobs/contracts.py`: DBやrunnerに依存しない型とProtocol。
- `jobs/sqlite_store.py`: schema、transaction、整合性制約。
- `jobs/worker.py`: 実行ループと失敗分類。

## 完了条件

中断・再開、重複防止、条件不一致、3 attempt、キャンセル、POINT完全性、artifact追跡をテストする。全pytest、ruff、demo、scale_check、artifact_demo、release checksumを通す。

## 今回含めないもの

PostgreSQL本番migration、複数Workerのheartbeat/lease期限、強制timeout、API/UI、分散queue、費用計測、原本取込、追加OSS。
