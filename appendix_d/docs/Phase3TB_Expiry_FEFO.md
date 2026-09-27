# Phase 3T-B 賞味期限別FEFOシミュレーション

Phase 3T-Aの承認済みPilot在庫snapshot・確定済みPOINT予測を再利用し、JAN×倉庫ごとに
翌日から14日間の賞味期限順消化を試算する。単位はCASE。結果は`SHADOW`参考値であり、
出荷指示、廃棄確定量、在庫補充推奨ではない。

## 業務ポリシー

計算前に担当者が以下を確認し、確認者・理由・確定時刻を指定する。値と確認情報から
`policy_version`を決定的に作り、結果へ埋め込む。業務値が未確認なら計算を実行しない。

- `minimum_remaining_days`: 賞味期限まで何日以上残る商品を利用可能と扱うか。例えば0なら期限当日まで、1なら前日まで。
- `attention_days`: 計算日から何日以内に利用期限を迎える残量を注意数量とするか。

ポリシーは今回DB登録せず、計算ごとに明示指定する。同じ条件と確認情報から同じ版を再作成できる。
このCLIの確認者・理由は申告値であり、承認ワークフローによる検証ではない。

## 計算と読み方

日ごとに利用期限を過ぎたbucketを除外し、予測需要を期限の早いbucketから消化する。
期限当日の需要を処理した後に残った数量を`unconsumed_by_cutoff_cases`へ計上する。
その数量は予測に基づく期限内未消化リスクであり、実際の廃棄量ではない。
期限不明・不正、CASE以外、snapshotとbucketの数量不一致は停止する。
未消化数量を0需要と見なして補完しない。

`days[].attention_cases`はその日の計算終了時点で、指定日数以内に利用期限を迎える
残量である。同じ在庫を複数日で表示するため日別値を合計しない。
`days[].unmet_cases`はその日に満たせない予測需要で、`unmet_demand_cases`は14日合計。
各bucketの開始数量は、消化量・期限内未消化量・14日後残量に厳密に分解する。

この計算は補充、工場供給、生産予定、輸送、実績需要、安全在庫を含めない。
欠品と期限切れは予測に基づく試算であり、3T-C/Dの供給・到着時点計算や
正式なShipment Recommendationとは区別する。

## 実行

`kiban-expiry-simulation`がない環境では`python -m forecast_provider.expiry_simulation.cli`を使う。
PostgreSQLでは`--sqlite <DB>`を`--postgres-dsn <DSN>`へ置き換える。
時刻には必ずtimezoneを含める。結果JSONには在庫・需要が含まれるため管理された保存先に置く。

```powershell
kiban-expiry-simulation --sqlite pilot.sqlite3 --pilot-scope-version <scope-version> --identity-bridge-version <bridge-version> --forecast-run-id <run-id> --calculation-at 2026-09-27T12:00:00+09:00 --minimum-remaining-days <confirmed-days> --attention-days <confirmed-days> --policy-confirmed-by <reviewer> --policy-reason <reason> --policy-confirmed-at 2026-09-27T11:00:00+09:00 > expiry_simulation.json
```

同じsnapshot、run、policy、計算時刻、bucket数量から同じ`simulation_id`になる。
snapshot時刻とknown_at、予測originのcutoff・run完了時刻も結果に含める。
実データをRepositoryに保存しない。`minimum_remaining_days`などの正式業務値は
クライアント確認後に指定する。
