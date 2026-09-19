# Phase 3M モデル条件間安定性

## 目的

複数条件のうち1回だけ1位になったモデルと、広い条件で公式比較へ掲載され続けたモデルを区別する。
Phase 3Lの完了済み比較結果から、モデルごとの掲載率、順位分布、精度の振れ幅を自動集計する。
新しい評価値を計算せず、保存済み比較結果の`official_common_metrics`だけを使用する。

## 画面

`/ui/analysis`の「モデルの条件間安定性」に次を表示する。

- 公式掲載: モデルが設定された完了条件のうち、正式比較対象になった条件数と割合
- 1位回数: 正式比較対象になった条件のうち、条件内順位が1位だった回数
- 平均順位: 正式比較対象条件の順位の算術平均
- 順位幅: 最良順位から最悪順位まで
- WAPE平均: 条件別WAPEの算術平均
- WAPE幅: 条件別WAPEの最大値と最小値の差
- 絶対Bias平均: 条件別Bias率の絶対値の算術平均
- 最低成功率: 条件別run成功率の最小値

正式比較条件が2件未満の場合は「条件不足」と表示する。2件以上で順位が変わった場合は
「順位変動あり」、同じ場合は「順位安定」と表示する。この表示は採用可否や精度合格を意味しない。

## API契約

`GET /api/comparison-campaign-results`の既存`tests`に、後方互換な
`model_stability`を追加する。

- `completed_test_count`: 取得範囲内の完了条件数
- `configured_test_count`: 対象モデルが設定された完了条件数
- `eligible_test_count`: 正式比較へ掲載された条件数
- `official_coverage_pct`: `eligible / configured`
- `overall_coverage_pct`: `eligible / completed`
- `win_count`、`win_rate_pct`
- `mean_rank`、`rank_min`、`rank_max`、`rank_range`、`rank_stddev`
- `wape_mean_pct`、`wape_min_pct`、`wape_max_pct`、`wape_range_pct`、`wape_stddev_pct`
- `mean_abs_bias_rate_pct`、`min_success_rate_pct`
- `varies_by_condition`

標準偏差は取得条件全体を母集団とする。正式比較対象外、WAPE欠落、順位欠落の結果は分布計算へ
含めないが、公式掲載率の分母には残す。異なるモデル集合を使ったテストもあるため、全完了条件に
対する掲載率と、そのモデルを設定した条件に対する掲載率を分ける。

## 実装境界

横断結果の結合、条件内順位、安定性集計は`api/campaign_results.py`、横断表と安定性表の描画は
`analysis_campaign_results.js`へ分離する。キャンペーン登録、Worker、比較結果の不変台帳、評価式は
変更しない。集計結果は参照時に生成し、新しい正解値、予測値、採用判断を保存しない。

## 判定方法

モデル選定では少なくとも次を分けて確認する。

1. 公式掲載率が100%か。低い場合は順位より未掲載理由を確認する。
2. 平均順位だけでなく順位幅を確認する。
3. WAPE平均だけでなくWAPE幅と最低成功率を確認する。
4. Bias方向が相殺されないよう絶対Bias平均と条件別詳細を併記する。
5. 資源・費用、実データ受入、業務判断は既存画面で別に確認する。
