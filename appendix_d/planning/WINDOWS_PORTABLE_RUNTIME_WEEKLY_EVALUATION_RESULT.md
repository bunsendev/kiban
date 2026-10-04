# Windows Portable Runtime版別週次評価 実装結果

## 完成した範囲

- 固定済み週次集計版のcaseを、正式予測RunのRuntime版・設定hash・Pilot Scopeへ帰属させる。
- Runtime版ごとに予測精度、担当者修正、3業務KPI、取得率を表示する。
- Baselineと候補版を同じ業務日・JAN・倉庫、同じ取込元のActualに限定して比較する。
- Runtime証跡のない旧case、欠測、重複、Actual不一致を自動補完せず停止理由にする。
- 内容アドレス方式で固定保存し、改変と元週次版の不整合を検出する。

## モジュール境界

- `runtime_weekly_evaluations.py`: 週次版・Runtime証跡の照合と評価証跡固定
- `runtime_weekly_metrics.py`: 精度・業務KPIと同一Actualの純粋比較
- `runtime_weekly_evaluation_routes.py`: HTTP入出力
- `runtime-weekly-evaluations.js`: 手順12-2の操作と表示
- 既存の週次集計、Production受渡し、Runtime選択、Feedback Ledgerは書き換えず読み取る。

## 互換性と制約

- DB migrationはない。評価証跡は独立JSONで追記する。
- 旧caseは未特定として参照可能なまま残す。
- SHADOW、Scope限定、正式設定への非自動反映を維持する。
- 実データと資格情報はRepositoryと配布ZIPへ含めない。

## 検証

- 同一Actual上でBaseline MAE 3箱、候補版MAE 1箱、差 -2箱となる固定fixtureを確認する。
- 担当者修正、欠品、期限切れ欠測、倉庫間移動を独立集計する。
- Runtime未特定、Actualの取込元不一致、評価証跡改変、再起動後の再表示を確認する。

## 次工程

現場Pilotの実際のBaseline・候補版caseが蓄積した後、必要な観測期間と最小件数を業務承認し、既存の正式変更案・別承認・rollback契約で採用可否を判断する。
