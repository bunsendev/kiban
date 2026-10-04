# Phase 3T Runtime版別週次評価

## 目的

正式予測Runで実際に選択されたBaselineまたは候補版と、担当者判断、後日Actualを固定済みの週次集計版に結び付けます。結果はSHADOWの観測証跡です。因果効果の証明や正式設定への自動昇格は行いません。

## 操作

1. 手順12で後日実績を含む週次集計版を作成します。
2. 手順12-2で元の週次集計版を選びます。
3. Runtime評価版、確認者、SHADOW確認を入力し、［使用モデル版ごとの結果を固定］を押します。
4. Runtime版、設定hash、Pilot Scope、予測誤差、担当者修正、欠品、期限切れ、倉庫間移動を確認します。
5. Baselineと候補版の比較状態が`READY`であることを確認します。

## 比較条件

- 同じ業務日、JAN、倉庫のcaseだけを対応付けます。
- Actualは取込元の版、SHA-256、全数量が一致する場合だけ共通実績とします。
- Actual未取得は0にせず、欠測件数として残します。
- 同一Runtime内の自然key重複、Actual不一致、共通Actualなしは比較停止理由にします。
- 旧版caseにRuntime証跡がない場合は、推測せず未特定として表示します。

## 保存と改変検知

`Data/State/RuntimeWeeklyEvaluations/<evaluation_id>.json`へ内容アドレス方式で保存します。元の週次集計hash、case、Actual、Production受渡し記録、Runtime選択証跡を参照します。再表示時に自身と元週次版のhashを再検証します。

## 判断上の注意

精度差と業務KPIは同じActual上の観測値です。対象件数、欠測、期間、Pilot Scope、現場条件を人が確認し、既存の変更案・別承認・Pilot Gateで次の判断を行います。
