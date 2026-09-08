# 付録D ForecastProvider契約とリファレンス実装 v2.9

対象：BUNSEN-FCST-IMPL-002。現行契約はdocs/統合仕様_v2.9.mdを正とする。

| モジュール | 責務 |
|---|---|
| contracts.py | 型、能力、モデル、実験定義、6メソッド契約 |
| frames.py | 日次入力、予測対象、POINT/QUANTILEの検証 |
| providers/builtin_baseline.py | 4方式とTRAIN残差キャッシュ |
| features.py | 固定カレンダーとknown_at付き将来変数の版選択 |
| runner.py | 固定学習、起点更新、予測、失敗記録 |
| evaluation.py | 全予定照合、3集合比較、集合ID、通期・累計評価 |

Provider契約はmetadata / validate / fit_parameters / refresh_context / predict / cleanup。
Providerを追加する際は識別・型だけでなく、未来遮断、固定パラメータ、欠測、出力失敗、区間、再現性を検証する。

## runner

```python
run = run_fixed_baseline(
    data, dataset, config, context,
    availability_mode="ASSUMED",
    feature_versions=feature_versions,  # 変更される将来変数がある場合のみ必要
)
```

feature_versionsはunique_id, ds, feature, value, known_atを持つDataFrame。
known_atはtimezone付き。固定カレンダー列だけなら省略できる。
返却：predictions / ledger / errors / availability_mode / excluded_unique_ids / fit_calls /
unclassified_error_count / status。

## 比較

```python
report = compare_runs(
    {"run_a": dataset_a, "run_b": dataset_b},
    {"run_a": predictions_a, "run_b": predictions_b},
    truth, truth_version="truth_v1", mode="horizon", horizon=7,
)
```

own_metricsは各run単独の成功集合であり、そのまま同一条件ランキングに使わない。
official_common_metricsは完全runだけで再構築した同一集合。official_comparison_set_idと件数を併記する。
official_evaluation_readyは単独評価可、official_ranking_readyは2方式以上の比較可。
適合試験・業務採用の承認を代替するフラグではない。

保存前はreconcile_predictionsを必須とする。完全出力を要求する場合はvalidate_predict_frameのexpected_targetsを指定する。
本文のDB/API/Worker、永続モデルstate、月次再学習は後続実装である。

## 検証

全テストはpytest。今回の回帰テストはtests/test_v29_regressions.py。
実測結果はtest_results.txt。配布ハッシュは最終記録更新後に作成する。
