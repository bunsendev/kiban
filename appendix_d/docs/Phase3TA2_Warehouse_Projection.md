# Phase 3T-A 倉庫在庫Projection（Shadow参考値）

この計算は、業務APPROVED済みの`PILOT_PARTIAL`在庫snapshotと、確定済み予測runの
`POINT`値を、JAN×倉庫ごとに結び付ける。snapshotの翌JST業務日から連続14日を対象とし、
日次需要、入庫なしのgross在庫残高、累積不足量と最初の不足日を返す。
7日・14日の需要合計は同じ14日系列から計算する。

賞味期限到来による消化・廃棄、補充、工場供給、輸送時間、安全在庫は計算しない。
したがって**出荷指示や正式な補充推奨ではない**。期限切れ在庫がsnapshot時点に存在すれば停止し、
将来の期限到来は次工程のFEFO Simulationで扱う。

## 前提と停止条件

- Pilot Scope、原本対応、予測identity bridgeを業務確認済みの版として登録する。
- 在庫snapshotの最新decisionが計算時点で`APPROVED`、かつscope照合が完了している。
- 対象JAN×倉庫の在庫bucketがすべて存在し、単位が`CASE`である。
- 予測runが`SUCCEEDED`で、その完了時刻と対象originのcutoffが計算時点以前である。
- snapshotのJST日付と同じoriginで、対象seriesの翌日から14日間の`POINT`が欠けずにある。
- bridgeの有効期間・known_at、在庫側canonical product IDとの整合、seriesの一意性を満たす。

予測値の欠落を0で埋めず、QUANTILEをPOINTの代わりに使わない。数量はDecimal CASEのまま扱う。
既存runに完了時刻がない場合は移行時刻を保守的な利用可能時刻として記録するため、それ以前の
as-of計算には使えない。現在の在庫・予測がそろっていない場合も計算を開始しない。

## 実行例

`kiban-warehouse-projection`が利用できなければ
`python -m forecast_provider.warehouse_projection.cli`を使う。PostgreSQLは
`--sqlite <DB>`を`--postgres-dsn <DSN>`に置き換える。出力はJSONで、在庫データを含むため
現場で管理する保存先へリダイレクトする。

```powershell
kiban-warehouse-projection --sqlite pilot.sqlite3 --pilot-scope-version <scope-version> --identity-bridge-version <bridge-version> --forecast-run-id <run-id> > warehouse_projection.json
```

JSONの`mode`は常に`SHADOW`。`gross_remaining_cases`は負値を取り得る仮想残高で、
`cumulative_shortfall_cases`はその時点までの不足累計を表す。run、origin、cutoff、完了時刻、
在庫snapshot時刻とknown_at、scope・bridge版、計算時刻を結果に含める。
同じ入力と計算時刻では同じ`projection_id`になる。

次工程の3T-Bで賞味期限bucketをFEFO順に消化し、期限内未消化量を算出する。
3T-C/Dの工場在庫・生産・輸送データがそろうまで、出荷可能数量と到着時点在庫は未算出とする。
