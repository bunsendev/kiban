# Phase 1C 実装結果

## ゴールと結果

run・起点・予定・予測・失敗・artifact参照の永続化境界と、完了済み起点を再利用するWorker再開契約を実装した。保存済み結果を上書きせず、中断中だった起点だけを新attemptで取得できる。

## 構成

| モジュール | 役割 |
|---|---|
| `jobs/contracts.py` | 製品非依存のRunStore、run・起点・予測型 |
| `jobs/sqlite_store.py` | 正規化台帳、起点transaction、attempt fencing |
| `jobs/worker.py` | 再開、失敗分類、最大3 attempt、キャンセル境界 |

新規製品コードは責務別に3ファイルへ分け、runner・予測式・評価式・Providerの6メソッドは変更していない。

## 永続化と再開契約

- run開始前に全起点と全POINT予定を登録する。
- condition fingerprintが違うrun、SUCCEEDED/CANCELLEDのrunは再開しない。
- 中断時RUNNINGだった起点をQUEUEDへ戻し、attemptを増やす。SUCCEEDED起点は再取得しない。
- 必要POINT、予測値、予定状態、model/context artifact参照、起点状態を一つのtransactionで確定する。
- 古いattemptの書込みはStaleLeaseErrorで拒否する。
- retryable ProviderErrorだけ最大3 attempt。未分類・非retryable例外は自動再試行しない。
- キャンセル後は次の起点を開始しない。
- 全起点成功はSUCCEEDED、一部成功はPARTIAL、成功0件はFAILED。

## 検証

- pytest: 257 passed（Phase 1Bの250件＋Phase 1Cの7件）。
- ruff: All checks passed。
- demo: 成功。
- scale_check: 37起点、POINT 54,500行、総行218,000、365日/系列、重複0。
- artifact_demo: 別プロセス復元24行が完全一致。
- 配布checksum: 最終生成後に全件一致。

## 未対応と残課題

- SQLiteは単一ホスト参照実装。本番PostgreSQL migrationと運用設定。
- 複数Workerのlease期限・heartbeat、強制timeout、resource/費用計測。
- API/UI、分散queue、原本取込、JAN名寄せ、追加OSS。

次は、PostgreSQL migrationとDB適合テストを作り、RunStore実装を差し替え可能にしたままAPI/worker process境界へ接続する段階が適切。
