# Phase 3N モデル精度の時系列変化

## 目的

完了済みの公式比較結果について、同一条件の直前テストからWAPE、Bias、成功率、順位が
どのように変化したかを分析実行画面で確認できるようにする。条件の異なる結果を混ぜず、
変化量は技術確認の材料として提示する。採用可否や精度合格は自動判定しない。

## 比較可能条件

次の全項目が一致する結果だけを同じ比較系列へ含める。

- Provider ID、モデルID、snapshot IDを除くモデル・前処理・学習設定
- 対象`unique_id`集合、既知将来変数集合
- 学習日数、テスト日数、`availability_mode`
- 評価方式とhorizon
- 起点間隔、最大horizon、主評価最大horizon

対象IDと既知将来変数は正規化後のSHA-256で照合する。APIは対象IDを返さない。
`selection_version`やsnapshot IDが異なっても上記条件が同じなら比較できる。同じテスト開始日・
終了日の再実行が複数ある場合は、作成日時とキャンペーンIDで決まる最新記録だけを使用する。

## API契約

`GET /api/comparison-campaign-results`へ後方互換な`model_drift`を追加する。

- `series_count`: 取得範囲内の公式結果から得られた比較系列数
- `comparable_series_count`: 異なるテスト期間を2件以上持つ系列数
- `series`: モデル・比較プロフィールごとの直近変化
- `history_count`: 重複期間を除く履歴数
- `previous`、`latest`: 直前と最新の期間、指標、選定版、キャンペーンID
- `wape_change_pct_points`、`wape_relative_change_pct`
- `abs_bias_change_pct_points`: Bias符号の相殺を避けた絶対値の変化
- `success_rate_change_pct_points`、`rank_change`
- `period_gap_days`: 直前テスト終了から最新テスト開始までの空き日数
- `direction`: `WAPE_UP`、`WAPE_DOWN`、`UNCHANGED`、`INSUFFICIENT_HISTORY`

変化量は`最新 - 直前`である。順位変化の正値は順位番号の増加、すなわち順位低下を示す。
直前WAPEが0の場合、ゼロ除算を避けて相対変化を`null`とする。

## 画面表示

分析実行画面の「同一条件の時系列変化」に、比較プロフィール、履歴数、直前・最新期間、
WAPE、絶対Bias、成功率、順位の差分を表示する。履歴が1期間だけの系列は「履歴不足」とする。
WAPEの上昇・低下・同値は事実表示であり、閾値や自動昇格・rollbackには接続しない。

## 実装境界

比較プロフィールと差分集計は`api/campaign_drift.py`、保存済み結果との結合は
`api/campaign_results.py`、画面描画は`analysis_campaign_results.js`に分離する。
snapshot、実験、run、公式比較結果、採用判断の台帳は変更しない。集計はread-only APIの
参照時に生成し、新しい予測値や判断履歴を保存しない。

## 運用手順

1. 同じ品目集合・モデル設定・評価条件で、異なるテスト期間の比較キャンペーンを完了する。
2. `/ui/analysis`で「同一条件の時系列変化」を開く。
3. 「比較可能」が増えたことを確認し、WAPE上昇行の絶対Bias、成功率、順位も確認する。
4. 期間に空きがある場合は、表示期間を確認して業務イベントやデータ品質と照合する。
5. 必要ならPhase 1Sのtrial・昇格判断へ進む。画面表示だけで採用・rollbackを決めない。
