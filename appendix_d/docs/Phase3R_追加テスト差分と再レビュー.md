# Phase 3R 追加テスト差分と再レビュー

## 目的

Phase 3Qで完了した追加テストについて、元の公式比較と追加テストの公式比較をモデル単位で突き合わせる。結果は事実表示に限定し、モデル採否や本番昇格を自動決定しない。レビュー対象モデルの差分は、利用者が内容を確認して新しい判断版として記録できる。

## 比較契約

- 比較元は`source_campaign_id`、比較先は追加テストの`campaign_id`で固定する。
- それぞれの成功済みfinalizationが参照する保存済み`comparison_id`から`official_common_metrics`を取得する。
- モデルは`provider_id`と`model_id`の組で照合する。片側にしかないモデルも結果へ残す。
- WAPE、MAE、RMSE、絶対Bias、成功率、順位について「追加テスト値 - 元結果値」を返す。
- 片側の値が欠損なら差分も欠損とし、0へ変換しない。
- 事実判定は両側が正式評価対象でWAPEが存在する場合だけ行う。WAPE低下を`IMPROVED`、上昇を`WORSENED`、同値を`UNCHANGED`、それ以外を`NOT_COMPARABLE`とする。

この判定は公式共通WAPEの増減だけを示す。精度合格、業務適合、採用、昇格、rollbackの判断ではない。

## APIと画面

`GET /api/model-drift-review-retests`は成功済み追加テストへ`comparison_summary`を付加する。期間、snapshot、selection version、評価方式、モデル集合一致、モデル別の元値・追加値・差分、事実判定を含む。

`/ui/analysis`の対応履歴にはモデル別の差分表を表示する。元レビューの対象モデルが現在の精度変化系列に接続できる場合は「この結果を再レビューへ引き継ぐ」を表示し、比較対象、次の判断版、差分を含む根拠案、対応案をレビュー入力へ設定する。登録は行わず、利用者が判断区分と文章を確認して送信する。

## モジュール境界

- `api/campaign_results.py`: 指定キャンペーン1件の公式結果整形
- `model_review/retest_comparison.py`: 副作用のないモデル差分集計
- `model_review/retest_service.py`: 追加テスト、元レビュー、差分、再レビュー対象の結合
- `ui/static/analysis_retest_results.js`: 差分表と引継ぎ操作の描画

## 制約

- 保存済み公式結果を再計算・上書きしない。
- 200件を超えて古い系列が現在の精度変化一覧にない場合、差分は表示するが再レビュー引継ぎボタンは表示しない。
- モデル集合が異なる場合は`model_set_match=false`とし、片側だけのモデルを比較不能として残す。
