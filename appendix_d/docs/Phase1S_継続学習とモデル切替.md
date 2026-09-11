# Phase 1S 継続学習と安全なモデル切替

Phase 1Sは、採用済みrunをchampionとして月次再学習を継続し、比較基準を満たしたchallengerだけを承認者が昇格できる運用境界を追加する。昇格・rollback・将来trialの履歴は上書きせず、SQLite/PostgreSQLへ追記する。

## 月次拡大学習

Experimentの`training_policy`は次の2値を取る。

| 値 | 学習動作 | 固定ランキング |
|---|---|---|
| `FIXED` | 初回TRAIN_ENDで1回fitし、各originでcontextだけ更新 | 適合条件を満たせば対象 |
| `MONTHLY_EXPANDING` | 各月の最初の予定originで、TRAIN_STARTから当該締切まで再fit | referenceのみ |

既定値は`FIXED`であり、既存Experiment作成requestはそのまま動作する。月次回数はorigin scheduleから導出し、12回に固定しない。各fitは当該originの翌日00:00 JSTを情報利用締切とし、未来の実績を使わない。

同期実行は`run_monthly_provider`を使う。分散workerはExperiment定義を読み、学習締切ごとに別のmodel artifactを保存する。同じ月のoriginは成功済みartifactを再利用する。複数workerが同時にその月の最初のoriginを処理しても、同じrun、学習締切、設定から内容アドレス方式の同一artifactへ収束する。

```json
{
  "snapshot_id": "<snapshot-id>",
  "provider_id": "builtin-baseline",
  "model_name": "moving_average_28",
  "params": {},
  "interval_levels": [],
  "preprocessing_version": "daily-nan-preserving-v1",
  "seed": 7,
  "resource_profile": "cpu-small",
  "training_policy": "MONTHLY_EXPANDING"
}
```

## Lifecycle計画

`POST /api/lifecycle-plans`は、既存の`ADOPTED`判断と月次Experimentを結ぶ。採用時の`selection_version`、成功済みchampion、fallbackを再検証する。試験終了日は採用判断の`trial_period_days`から導出され、30〜366日になる。

```json
{
  "plan_version": "lifecycle-2026-10-v1",
  "adoption_id": "adoption-...",
  "experiment_id": "<monthly-experiment-id>",
  "schedule_day": 1,
  "schedule_time": "02:00",
  "timezone": "Asia/Tokyo",
  "trial_start_date": "2026-10-01",
  "metric": "wape_pct",
  "minimum_improvement_pct": 2.0,
  "maximum_failure_rate": 0.0,
  "reason": "月次継続学習を開始"
}
```

`created_by`、`approved_by`、`recorded_by`、`assessed_by`はrequestの値を信用せず、認証subjectで確定する。計画作成、昇格、rollback、trial評価は`APPROVE`、cycle処理と予測事前記録は`ANALYZE`、参照は`READ`を必要とする。

## Schedulerと月次cycle

`kiban-lifecycle-scheduler`は期限到来した`plan_id + YYYY-MM`を一意のcycleとして登録する。同じ時刻で再実行しても重複しない。

```powershell
kiban-lifecycle-scheduler --postgres-dsn-file <DSN_FILE> --once
# 常駐時
kiban-lifecycle-scheduler --postgres-dsn-file <DSN_FILE> --poll-seconds 60
```

本番Composeの`workers` profileにはschedulerが含まれる。開発Composeでは次のように起動する。

```powershell
docker compose --profile worker up -d --build lifecycle-scheduler
```

Schedulerは新しいsnapshotを推測してrunを自動作成しない。予定cycleを作成した後、担当処理は当該締切までの利用可能実績を持つ不変snapshotから月次Experimentとrunを作成し、既存workerで完了させる。これにより、更新前のsnapshotで未来originを先行実行することを防ぐ。

完了runをchampionとのreference比較へ含め、比較IDをcycleへ結ぶ。

```json
POST /api/lifecycle-cycles/<cycle-id>/complete
{
  "challenger_run_id": "<run-id>",
  "comparison_id": "<comparison-id>"
}
```

共通集合WAPEの改善率が`minimum_improvement_pct`以上で、run失敗率が`maximum_failure_rate`以下ならcycleは`READY`、それ以外は`REJECTED`になる。失敗した処理は`/fail`へ機密情報を含まない`failure_code`を記録する。

## 承認付き昇格とrollback

昇格は現在のchampion revisionを指定する。比較結果を満たした`READY` cycleだけが対象で、event追加とcycleの`PROMOTED`更新は同じtransactionで行う。

```json
POST /api/lifecycle-cycles/<cycle-id>/promote
{
  "expected_revision": 1,
  "reason": "共通WAPEが基準以上に改善し欠測なし"
}
```

revisionが古いrequestは`409`となる。rollback先は採用時fallbackまたは過去のchampionに限定し、任意runへの切替を拒否する。

```json
POST /api/lifecycle-plans/<plan-id>/rollback
{
  "target_run_id": "<fallback-or-previous-champion>",
  "expected_revision": 2,
  "reason": "監視で異常を確認"
}
```

`GET /api/lifecycle-plans/<plan-id>`は現在champion、全cycle、trial記録件数、最新trial評価を返す。現在値は追記済みchampion eventの最大revisionから導出する。

## 将来trial

`POST /api/lifecycle-plans/<plan-id>/trial-forecasts`は、成功済みoriginの予測を最初のtarget実績が利用可能になる前にサーバー時刻で固定する。trial runは現在championとProvider、model、params、前処理、selection versionが一致しなければならない。同一plan・originの記録は上書きできない。

30日以上経過し、期間末日の実績が利用可能になった後、`purpose=FUTURE_TRIAL`で作成した比較だけをtrial評価へ使える。記録済みrunが比較に含まれ、評価期間の全target日が事前保存済み予測で被覆されていることを検査する。

```json
POST /api/lifecycle-plans/<plan-id>/trial-assessments
{
  "expected_revision": 0,
  "period_start": "2026-10-02",
  "period_end": "2026-10-31",
  "comparison_id": "<future-trial-comparison-id>",
  "decision": "COMPLETE",
  "reason": "連続30暦日の将来予測を確認"
}
```

`evidence_kind`は`FUTURE_TRIAL`に固定するため、過去backtestの比較と混同しない。`ROLLBACK`評価を記録した場合も切替は自動実行せず、承認者がrollback endpointで対象runとrevisionを明示する。

## モジュール境界

| module | 責務 |
|---|---|
| `training.py` | 学習方針、月初origin、拡大学習dataset、月範囲 |
| `lifecycle/contracts.py` | 不変recordとstore protocol |
| `lifecycle/plan_domain.py` | 計画と初期championの検証 |
| `lifecycle/domain.py` | event、cycle、trial record、scheduleの純粋関数 |
| `lifecycle/store.py` | plan、cycle、championのtransaction |
| `lifecycle/trial_store.py` | trial予測・評価の追記 |
| `lifecycle/service.py` | 採用、run、比較、昇格、rollbackの整合確認 |
| `lifecycle/trial_service.py` | 未来実績利用前の記録と30日評価 |
| `lifecycle/scheduler.py` | 期限到来cycleの冪等登録 |

Lifecycleは製造・購買システムへ予測値を自動書込みしない。実データの試験運用結果が保存されるまでは、本番精度や業務効果が確認済みという扱いにしない。

Phase 1Tでこれらの操作を専用管理画面`/ui/lifecycle`へ接続した。画面の使い方と権限は[Lifecycle運用画面](Phase1T_Lifecycle運用画面.md)を参照する。
