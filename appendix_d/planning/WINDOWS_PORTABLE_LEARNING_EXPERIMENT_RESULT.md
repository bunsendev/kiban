# Windows Portable 改善候補比較検証 実装結果

## 完成した流れ

手順12で承認した週次改善候補から、手順13で不変な比較計画を作成できる。候補の根拠case、比較対象、Baseline版、Challenger版、仮説、作成者、`known_at`を固定する。

テンプレートCSVへcase別のChallenger数量を入力すると、保存済みActualとの共通集合でBaselineとChallengerを比較する。比較runと判断履歴は上書きせず、内容アドレスとrevision付きeventで保存する。

## 表示する指標

- 計画case数、Challenger取得数、Actual取得数、共通比較数
- Baseline / ChallengerのMAE、RMSE、WAPE、Bias
- ChallengerからBaselineを引いた指標差
- 改善、同等、悪化したcase数
- 不足・過剰数量の代理指標と差
- 観測済みの欠品、期限切れ、倉庫間移動と取得件数
- Challenger未取得case、Actual未取得case

## モジュール境界

- `field_learning/experiment_domain.py`: 不変な計画・run・判断event
- `field_learning/experiment.py`: 共通case集合の決定的比較
- `field_learning/experiment_store.py`: SQLite/PostgreSQL追記台帳
- `portable/api/learning_experiments.py`: CSV検証、整合性検査、read model
- `portable/api/learning_experiment_routes.py`: HTTP境界
- `portable/api/static/learning-experiments.js`: 手順13の操作と表示

## 安全境界

APPROVED候補だけを計画化する。計画外case、重複case、不正数量、未来情報の混入、revision競合、保存内容の改変を拒否する。共通比較が0件なら変更推奨を拒否する。

業務Outcomeは観測事実だけを表示する。Challenger適用時の欠品・廃棄を推測しない。比較結果や人の判断からモデル・特徴量・policyを自動変更しない。

## 次工程

`RECOMMEND_FORMAL_CHANGE`となったrunから、変更対象、設定差分、rollback条件、適用対象、受入基準を持つ正式変更案を作る。変更案は別承認を必要とし、比較runの判断だけで現場設定を更新しない。
