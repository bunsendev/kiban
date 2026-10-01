# Windows Portable 到着時点在庫・推奨出荷Decision Engine 実装結果

## 目的

複数倉庫の日次業務サマリーへ、工場在庫、生産予定、工場から倉庫までの12〜36時間の
route別lead time、安全在庫policy、CASE出荷単位を接続する。現在庫ではなく到着予定時点の
倉庫在庫を基準に、商品・倉庫別の必要補充量、工場制約後の推奨出荷量、未充足数量、理由、
リスクをSHADOW modeで再現可能に試算する。

## 実装した構成

- `forecast_provider/shipment_decision/domain.py`
  - 版付き安全在庫policy、FACTORY在庫snapshot、生産予定、倉庫需要を定義した。
  - routeにはPhase 3Sの既存`RouteLeadTimePolicy`を再利用する。
- `forecast_provider/shipment_decision/service.py`
  - 外部状態を変更しない純粋計算として到着時点在庫と工場配分を実装した。
  - 同一factory・JANを複数倉庫が使用する場合は、不足予定日、lead time、倉庫IDの順で
    決定的に配分する。
- `portable/api/production_decision.py`
  - 日次サマリーと入力版をSHA-256で固定し、同一要求を同じ結果へ収束させる。
  - 保存結果を再読込するときに改変を検出する。
- 担当者画面の手順9
  - route共通条件、安全在庫日数、CASE出荷単位を入力する。
  - 工場在庫CSVを必須、生産予定CSVを任意で読み込む。
  - 到着時点在庫、必要補充、工場出荷可能量、推奨出荷、未充足、理由を表示する。

## 計算契約

倉庫ごとに採用lead timeを版付きroute policyから選択する。

```text
arrival_at = calculation_at + selected_lead_time_hours
arrival_time_inventory
  = current_warehouse_inventory
  - forecast_demand(calculation_at, arrival_at]

required_replenishment
  = ceil_to_shipment_unit(
      max(0, safety_stock_demand_after_arrival - arrival_time_inventory)
    )

factory_available
  = factory_inventory_snapshot
  + production_plans_completed_by_calculation_at

recommended_shipment = min(required_replenishment, remaining_factory_available)
unmet = required_replenishment - recommended_shipment
```

完成予定時刻が計算時刻より後の生産予定は、本日の出荷可能量へ加えない。存在しない生産予定、
工場在庫、route、安全在庫を0で補完しない。不足入力は理由コード付きblockerとして残す。

期限内消化困難数量が残る商品は、在庫切れリスクがあっても自動配分を0にして
`EXPIRY_SHIPMENT_HOLD`を付け、担当者確認へ送る。期限注意だけの場合はリスクを表示しつつ、
到着時点在庫に基づく試算を維持する。

## API

```text
POST /api/formal-forecast/{build_id}/daily-summary/{summary_key}/shipment-recommendation
```

入力には確認者・理由・確認フラグ、route policy、安全在庫policy、FACTORY在庫snapshot、
生産予定を含める。結果は`ProductionDecisions/{request_key}.json`へ内容アドレスで保存する。

## 検証

- 到着時刻までの需要控除
- JSTの日付境界
- 安全在庫日数とCASE出荷単位への切り上げ
- 計算時点までに完成した生産予定だけの加算
- 複数倉庫で共有するFACTORY在庫の決定的配分
- FACTORY供給不足と未充足数量
- 期限内消化困難商品の自動出荷保留
- policy・FACTORY在庫不足時のblocker
- API再起動後の冪等性と保存結果改変拒否

対象試験の結果と全体回帰は`test_results.txt`へ記録する。

## 現場で必要な確認

今回の画面はSHADOW modeであり、正式な出荷指示ではない。現場利用には次を確認する。

1. 正式なFACTORY location codeとlocation master version
2. 工場在庫CSVの基準日時とCASE数量
3. 生産予定ID、版、完成予定時刻、CASE数量
4. 倉庫ごとのminimum / standard / maximum lead timeと採用basis
5. 倉庫ごとの安全在庫日数とCASE出荷単位
6. `EXPIRY_SHIPMENT_HOLD`時の判断・解除手順

実データと資格情報はRepositoryへ保存していない。

## 次工程

現場で確認したFACTORY・route・安全在庫・生産予定の版付き入力を正式CSV取込へ接続する。
SHADOW結果と担当者判断、後日実績を比較し、欠品、廃棄、倉庫間移動の3指標でpolicyを調整する。
