# Phase 3F Worker稼働状態とキュー診断

## 目的

分析実行画面でrunが`QUEUED`のまま進まないとき、現場担当者がProvider専用Workerの未起動、
応答遅延、処理中を区別できるようにする。Providerごとの待機・実行中run数、Workerの最終
heartbeat、現在処理中のrunをREAD APIと`/ui/analysis`へ表示する。

## heartbeat契約

`worker_heartbeats`は次の可変な稼働状態だけを保持する。

- Worker IDとprocess起動ごとのinstance ID
- 対象Provider ID
- `IDLE`または`WORKING`
- `WORKING`時のcurrent run ID
- process開始時刻と最終heartbeat時刻

Worker起動時にUUIDのinstance IDを発行し、同じWorker IDで再起動すると現在instanceを置き換える。
旧processのheartbeatはWorker IDとinstance IDの不一致で拒否する。これにより再起動後の遅延更新で
新processの状態を上書きしない。

通常のpoll待機中は最大10秒間隔でheartbeatする。起点の推論中はorigin leaseを更新する周期で
Worker heartbeatも更新するため、長時間推論だけを理由に応答遅延と判定しない。processが異常終了
した場合は最終状態を削除せず、時刻経過により`STALE`として診断に残す。

## Provider状態

`GET /api/worker-status`はREAD権限で、Registryに登録された全Providerと、heartbeatまたはrunが
存在する追加Providerを返す。

| 状態 | 意味 |
|---|---|
| `WORKING` | heartbeat有効なWorkerがrunを処理中 |
| `ONLINE` | heartbeat有効なWorkerが待機中 |
| `STALE` | Worker記録はあるがheartbeatが期限超過 |
| `NOT_STARTED` | Worker heartbeatが一度も登録されていない |

既定の期限は45秒で、本番APIの`KIBAN_WORKER_STALE_SECONDS`で変更できる。待機・実行中run数は
run一覧APIの200件上限を使わず、DBのProvider・status別集計から取得する。

応答にはWorkerのホスト名、PID、command line、環境変数、DB接続情報を含めない。instance IDも
process fencing専用としてAPIへ公開しない。

## 画面の判断

分析実行画面はProviderごとに表示名、状態、待機run数、実行中run数、最終応答、Provider IDを
表示する。5秒のrun自動更新と同時にWorker状態も更新する。

- `NOT_STARTED`: 対象ProviderのWorker serviceを起動する。
- `STALE`: Worker serviceの状態と安全な診断情報を確認し、必要なら再起動する。
- `ONLINE`: WorkerはDBへ接続済みで、次のpollで待機runを取得する。
- `WORKING`: 現在のrun完了まで待つ。

`ONLINE`はprocessとDB heartbeatの確認であり、モデル精度、重み適合、Provider適合試験の合格を
意味しない。比較には従来どおり実験条件と一致するProvider適合記録が必要である。

## module境界

- `worker_status/contracts.py`: heartbeat、state、Store Protocol、旧instance拒否例外
- `worker_status/store.py`: SQLite/PostgreSQLの登録、fencing付き更新、一覧
- `worker_status/reporter.py`: Worker process内の状態遷移
- `worker_status/service.py`: Provider metadata、heartbeat、run queueの結合
- `api/worker_status_routes.py`: READ API
- `analysis_*`: 状態の取得、表示、run別の対処案内

## 受入条件

- Worker起動で`IDLE` heartbeatを登録し、run処理中は`WORKING`とcurrent runを保存する。
- 同じWorker IDで再起動した後、旧instanceのheartbeatを拒否する。
- 長時間の起点処理中もheartbeatを更新する。
- Provider別の待機・実行中run数を全件集計する。
- heartbeatなし、期限超過、待機中、処理中を別状態で返す。
- APIはREAD権限を要求し、instance IDや環境情報を公開しない。
- 分析画面はProvider ID固有の分岐を持たず、返されたProvider状態をすべて表示する。
