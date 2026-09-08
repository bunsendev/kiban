# Phase 1E APIとWorker process

Phase 1Eはrun操作だけを行うFastAPIと、予測を別プロセスで実行するWorker CLIを追加する。HTTP requestの中ではProviderを呼び出さない。

## API

`POST /api/runs`はrun IDを発行し、全起点・全POINT予定をQUEUEDで保存して202を返す。`GET /api/runs/{id}`は状態、起点状態別件数、失敗attempt数を返す。`POST /cancel`はキャンセル要求を記録し、未開始runはCANCELLEDにする。`POST /resume`は保存済みcondition fingerprintと一致する未完了runだけをRUNNINGへ戻す。

run endpointはBearer tokenを要求する。tokenは`KIBAN_API_TOKEN`から読み、コード・ログ・DBへ保存しない。`/health`は認証なし。TLSとrole別権限は外側のgateway・後続Phaseで追加する。

入力は未知field、空ID、重複origin/予定、未定義origin、timezoneなしcutoff、origin翌日00:00 JST以外のcutoff、不正horizonを422で拒否する。未知runは404、状態・条件競合は409。

## Worker

`kiban-worker --postgres-dsn ... --executor package.module:execute --worker-id ...`で起動する。Workerは実行可能runをRunStoreから取得し、Phase 1Dのlease/heartbeat/timeoutを使ってOriginExecutorを呼ぶ。executorはデプロイ済みの信頼されたPython moduleだけを指定し、APIからコードやmodule名を受け取らない。

`--once`は1回走査して終了し、省略時はpoll間隔で継続する。SQLiteはプロセス境界試験とローカル診断、PostgreSQLは複数Worker運用に使う。

## Docker Compose

`docker compose up --build postgres api`でDBとAPIを起動する。Compose既定tokenはローカル開発専用なので、共有環境では`KIBAN_API_TOKEN`を必ず設定する。Workerは`worker` profileに置き、デプロイ側OriginExecutorをイメージへ組み込んで`KIBAN_EXECUTOR`を指定して起動する。

## 制限

本Phaseはrun実行制御の最小APIであり、データ取込・実験編集・評価取得・UIは含まない。Worker executorの業務構成はデプロイ側で固定し、任意コード実行を公開APIにしない。
