# Phase 1F 実験SnapshotとBaseline統合

Phase 1Fは、予測条件をAPI requestだけに置かず、dataset snapshotと実験定義をDBへ不変保存する。IDは正規化JSONのSHA-256から決まり、同じ入力は同じIDになる。形式版を持つため、将来のschema変更は既存レコードを書き換えず扱える。

`POST /api/snapshots`と`GET /api/snapshots/{id}`、`POST /api/experiments`と`GET /api/experiments/{id}`を追加した。`POST /api/runs`が受け取るのは保存済み`experiment_id`だけである。起点と予測予定はsnapshotの期間・間隔・horizonからサーバーが生成する。

snapshotはデータURIとSHA-256、選定版、対象系列、学習・評価期間、将来特徴量契約を含む。カレンダー以外の既知将来列には、版テーブルURIとSHA-256を必須とする。Workerはファイルが許可root内にあることとchecksumを検証し、known_at以前の版だけを各起点へ渡す。

組込`builtin-baseline` executorはcatalogとRunStoreを参照し、最初の起点でモデルartifactを保存する。後続の別Workerプロセスは成功済み起点のModelRefを取得し、同じartifactを復元する。起点別ContextRefも保存・復元してから予測し、予測値・失敗・artifact参照を一transactionで確定する。

APIはBearer tokenを必要とし、任意のplan、Python module、実行コードを受け付けない。HTTP processは予測を実行しない。ComposeではAPIとWorkerが読み取り専用snapshot volumeを共有し、Workerだけがartifact volumeへ書き込む。

データ登録前にsnapshot CSVを`KIBAN_SNAPSHOT_ROOT`配下へ配置する。APIは`KIBAN_POSTGRES_DSN`、`KIBAN_API_TOKEN`、`KIBAN_SNAPSHOT_ROOT`を使用する。Workerは`kiban-worker --postgres-dsn ... --builtin-baseline --artifact-root ... --work-root ... --worker-id ...`で起動する。
