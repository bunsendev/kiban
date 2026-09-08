# Phase 1C run台帳と再開

Phase 1Cは、Phase 1Bで保存可能にしたmodel/context artifactを業務runと起点へ結び付け、プロセス停止後に完了済み起点を再利用する境界を追加する。

## 構成

| モジュール | 責務 |
|---|---|
| `forecast_provider/jobs/contracts.py` | RunStore Protocol、run・起点・予定・予測の不変データ |
| `forecast_provider/jobs/sqlite_store.py` | 参照DB、起点transaction、attempt fencing |
| `forecast_provider/jobs/worker.py` | 再開ループ、失敗分類、再試行、キャンセル境界 |

SQLiteはローカル検証用の参照実装であり、呼出側は`RunStore`だけに依存する。本番PostgreSQL実装では同じtransaction境界と一意制約を維持する。

## 再開規則

run作成時に全起点と全POINT予定を先に登録する。`start_or_resume`はcondition fingerprintが一致する同じ未完了runだけを開始する。プロセス停止時に`RUNNING`だった起点は`QUEUED`へ戻し、attemptを増やして再取得する。`SUCCEEDED`起点は取得しない。

起点の完了処理は、必要POINTの過不足がないこと、origin/target/horizon、POINT/QUANTILE、`yhat=max(yhat_raw,0)`を検証する。その後、予測値、予定のSUCCESS、model/context artifact参照、起点状態を一つのtransactionで保存する。leaseのattemptが現在値と違う場合は`StaleLeaseError`となり、停止前Workerの遅延結果を保存しない。

retryableな`ProviderError`だけを最大3 attemptまで実行する。未分類例外と非retryable例外は1回で失敗にする。失敗attemptでは予測値を保存せず、失敗台帳だけを残す。キャンセル要求は現在の呼出し境界で確認し、次起点を開始しない。

## 状態

runはQUEUED、RUNNINGからSUCCEEDED/PARTIAL/FAILED/CANCELLEDへ進む。全起点成功だけがSUCCEEDED、一部成功はPARTIAL、成功0件はFAILEDとなる。完了runを同じIDで上書きせず、新しい条件は新runとして作成する。

## 制限

参照実装は単一ホスト上のSQLiteを対象とする。複数ホスト用のlease期限・heartbeat、強制timeout、リソース計測、費用、PostgreSQL migration、API/UIは後続Phaseで実装する。
