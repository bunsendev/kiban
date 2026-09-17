# Phase 3D Provider別Worker実行分離

## 目的

Baseline、StatsForecast、MLForecast、TimesFMの専用Workerを同時起動したとき、各Workerが
自分のProvider用runだけを取得する。別Provider用executorによる誤実行、誤った失敗確定、
資源計測の混在をキュー取得前に防ぐ。

## 実行契約

run作成時に`forecast_runs.provider_id`へ不変なProvider IDを保存する。Workerは起動時に一つの
Provider IDへ固定され、`QUEUED`または`RUNNING`かつ取消要求のないrunを、そのProvider IDで
絞り込んで取得する。

- `--builtin-baseline`: `builtin-baseline`へ自動固定する。
- `--statsforecast-ets`: `statsforecast-ets`へ自動固定する。
- `--mlforecast-ridge`: `mlforecast-ridge`へ自動固定する。
- `--timesfm-2p5`: `timesfm-2p5`へ自動固定する。
- `--executor module:function`: `--provider-id`を必須とする。

組込executorへ`--provider-id`を重ねて指定することはできない。組込executorのProvider IDは
executorがProvider metadataから確定し、運用コマンドで上書きさせない。

```powershell
kiban-worker `
  --postgres-dsn-file C:\secrets\postgres-dsn.txt `
  --executor custom_provider.worker:execute `
  --provider-id custom-provider-v1 `
  --worker-id custom-provider-worker-1
```

## DBと競合制御

SQLiteとPostgreSQLの`RunStore.list_runnable_runs(provider_id)`は同じ絞り込み契約を持つ。
`provider_id`、`status`、`cancellation_requested`、`run_id`の複合索引でpollを支援する。

Provider affinityはProvider間の分離を担当する。同じProviderの複数Worker間では、従来どおり
PostgreSQLの`FOR UPDATE SKIP LOCKED`とorigin lease tokenが二重実行を防ぐ。完了済みoriginの
再利用、heartbeat、期限切れ回収、遅延結果の拒否は変更しない。

## 受入条件

- Baseline Workerを実行しても、別Providerの待機runは`QUEUED`のまま残る。
- 対象Providerのrunだけが実行され、対象外runのexecutorは呼ばれない。
- 存在しないProvider IDを指定したWorkerは0件処理し、他runを変更しない。
- カスタムexecutorはProvider IDなしでは起動しない。
- 組込executorはmetadata由来のProvider IDを公開する。
- SQLiteとPostgreSQL migrationがProvider別poll索引を持つ。

## 運用上の注意

Provider用Workerを停止すると、そのProviderのrunは待機したままとなる。別ProviderのWorkerが
代行して失敗させることはない。runが進まない場合は`/ui/resources`のProvider表示と、対応する
Worker serviceの起動状態を照合する。
