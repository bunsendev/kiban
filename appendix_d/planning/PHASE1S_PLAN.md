# Phase 1S 実装計画 — 継続学習と安全なモデル切替

## ゴール

固定済みの採用判断を起点に、月次の拡大学習、champion/challenger 比較、承認付き昇格、即時ロールバック、30日以上の将来試験運用を、追記型の監査記録として運用できるようにする。

## 実装範囲

1. Experiment に `training_policy` を追加する。既定値は `FIXED` とし、`MONTHLY_EXPANDING` は各月の最初の予定 origin で、当時利用可能な観測だけを使って再学習する。
2. 同期 runner と分散 worker の両方で同じ学習スケジュール計算を使用する。モデル artifact は学習締切ごとに分け、再開時には同じ月の成功済み artifact を再利用する。
3. 月次再学習 run は reference として扱い、固定学習の正式ランキング対象へ混入させない。
4. `forecast_provider.lifecycle` を追加する。計画、月次 cycle、champion event、試験予測記録、試験評価を別モジュールに分ける。
5. スケジューラは計画された月次 cycle を冪等に作成する。cycle へ完了済み challenger run と比較結果を結び、改善率・成功率の基準を満たした場合だけ昇格候補にする。
6. 昇格とロールバックには APPROVER 権限と期待 revision を要求する。現在 champion は上書きせず、イベント列から導出する。
7. 試験予測は実績が利用可能になる前にサーバー時刻で記録する。試験評価は履歴 backtest と区別し、30日以上の期間を要求する。
8. SQLite/PostgreSQL、API、CLI、production Compose、運用手順を同じ変更で更新する。

## モジュール境界

- `training.py`: 学習方針と学習締切の純粋関数
- `runner.py` / `executors/fixed_provider.py`: 予測実行だけを担当
- `lifecycle/contracts.py`: 永続化境界と不変 record
- `lifecycle/domain.py`: ID、入力検証、schedule 計算
- `lifecycle/store.py`: SQLite の状態遷移と楽観的排他
- `lifecycle/postgres_store.py`: PostgreSQL 接続差分
- `lifecycle/service.py`: 既存の採用、run、比較との整合確認
- `lifecycle/scheduler.py`: 期限到来 cycle の冪等作成
- `api/lifecycle_*`: HTTP schema と route

## 完了条件

- 月をまたぐテストで実学習回数と学習締切が導出どおりになる。
- worker 再開と複数 process を想定した artifact 再利用を検証する。
- 不適格比較、二重昇格、古い revision、任意 run への rollback、実績利用可能後の試験予測を拒否する。
- scheduler を同じ時刻で繰り返しても cycle が重複しない。
- SQLite/API の統合試験、PostgreSQL 試験、全 pytest、ruff、release 再現性検査を通す。
- 日本語の commit と PR 説明で GitHub に提出する。
