# Phase 3T Shadow参考補充量とreference case

この機能は、承認済みPilot倉庫在庫・確定POINT予測・FEFO試算を使い、**倉庫単独の参考不足量**を計算する。`SHADOW`の検証値であり、出荷指示や正式なShipment Recommendationではない。現場確認がない限り計算・保存しない。既存の`/ui/shadow`は引き続き読み取り専用で、この数量を表示・登録しない。

## 明示する業務条件

対象日数（1〜14日）、安全在庫数量（CASE）、出荷単位（正のCASE）、賞味期限の最小残存日数・注意日数を指定する。期限policyと参考数量policyの双方に確認者・理由・確認時刻が必要で、確認時刻が計算時点より後なら拒否する。値に暗黙の既定値はない。入力した確認情報は業務承認の**申告**であり、担当者の権限や承認手続そのものを代行しない。

版IDは条件・確認情報の内容ハッシュ。`field_reference_policies`へ計算のbasis・対象日数・安全在庫・単位・期限policy版・確認情報を保存し、caseから版で参照できる。同じ明示時点・入力版ならcase IDと数量が一致する。

## 計算式

対象期間の予測需要を合計し、FEFO試算で同期間中に利用期限を過ぎる未消化数量を現在庫から差し引く。

```text
期限内に使える現在庫 = max(0, 現在庫 - 対象期間内の期限内未消化見込み)
不足量 = max(0, 対象期間の予測需要 + 安全在庫 - 期限内に使える現在庫)
参考補充量 = 不足量を出荷単位へ切り上げ
```

これは`WAREHOUSE_NOW_NO_INBOUND_SHADOW`という限定したbasisである。工場在庫、生産予定、route別12〜36時間の配送、到着時点までの需要、倉庫間移動は反映しない。対象Pilot全体へ同じ安全在庫CASE数・出荷単位を適用する初期契約であり、商品・倉庫別条件が必要なら版付きpolicyを拡張する。実際の出荷可能数量や廃棄量を保証しない。

## 実行

管理者が業務で確認した値と既存のversion IDを用意する。まず`--apply`なしで試算し、件数・合計数量・policy版を確認する。個別JAN・倉庫・原本pathはCLIの集計結果へ出さない。登録するときだけ**同じ引数**に`--apply`を付ける。実データ、資格情報、実際の確認者名はRepositoryへ保存しない。

```text
python -m forecast_provider.field_reference.cli \
  --sqlite <DB> \
  --pilot-scope-version <正式版> --identity-bridge-version <正式版> \
  --forecast-run-id <成功したrun> \
  --calculation-at <時差付き日時> \
  --minimum-remaining-days <確認済み日数> --attention-days <確認済み日数> \
  --expiry-policy-confirmed-by <確認者> --expiry-policy-reason <理由> \
  --expiry-policy-confirmed-at <時差付き日時> \
  --target-days <確認済み日数> --safety-stock-cases <確認済みCASE> \
  --shipment-multiple-cases <確認済みCASE> \
  --reference-policy-confirmed-by <確認者> --reference-policy-reason <理由> \
  --reference-policy-confirmed-at <時差付き日時>
```

PowerShellでは1行に入力するか、各行末をPowerShellの継続記号に置き換える。PostgreSQLでは`--sqlite <DB>`の代わりに`--postgres-dsn <DSN>`を使う。`--apply`時はpolicyと全対象caseを単一transactionで追記する。未承認snapshot・欠けた予測・scope外・identity不一致・期限不明などは保存前に停止する。再実行で同じcaseを重複作成しない。
`recorded_at`は登録時のシステム時刻を記録し、利用者に過去時刻を指定させない。

## 次の接続

担当者の独立判断をシステム参考値の表示前に取得する運用と判断入力UI、後日実績と結ぶ週次reviewを追加する。実データでの業務受入とShadow開始Gateの承認は別途必要。工場・routeが揃ったら、この限定basisを到着時点在庫に基づくpolicyへ置き換え、旧版caseは保持する。
