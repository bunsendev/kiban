# Phase 1E 実装結果

## ゴールと結果

Bearer認証付きrun APIと、HTTP外で予測起点を処理する独立WorkerプロセスをPhase 1DのRunStoreへ接続した。route、schema、application service、環境factory、Worker CLIを分割し、HTTPからProviderを呼ばない構成にした。

## API

- `POST /api/runs`: UUID発行、全起点・予定の事前登録、202。
- `GET /api/runs/{id}`: run状態、起点状態別件数、失敗attempt数。
- `POST /api/runs/{id}/cancel`: キャンセル要求。未開始runはCANCELLED。
- `POST /api/runs/{id}/resume`: condition fingerprint一致時だけ再開。
- Bearer token、401/404/409/422、公開health endpoint。

## Worker

- `kiban-worker` entry pointと`python -m forecast_provider.worker_process`。
- SQLite/PostgreSQL、固定された`module:function` OriginExecutor、継続poll/`--once`。
- 別PythonプロセスからQUEUED runを取得し、予測値とSUCCEEDED状態を保存。
- 別Workerが有効leaseを持つrunはRUNNINGのまま維持。

## モジュール

| モジュール | 責務 |
|---|---|
| `api/schemas.py` | 厳密HTTP schema |
| `api/service.py` | runユースケース |
| `api/app.py` | route、認証、HTTP error |
| `api/factory.py` | 環境変数からASGI app構築 |
| `worker_process.py` | 独立processとpoll loop |

## 検証

- pytest: 270 passed、PostgreSQL実DB試験1件skip。
- ruff、demo、scale_check、artifact_demo成功。
- wheelにAPI、Worker、console entry point、migrationが同梱。
- 配布checksum全件一致。
- Dockerは端末にないためCompose実起動は未検証。

## 未対応

実験・データ取込・評価API、role別認可、Web UI、TLS、本番secret manager、分散queue、業務OriginExecutorのデプロイ構成。

次は実験定義とdataset snapshotをAPI/DBへ固定し、業務用baseline OriginExecutorが保存済みartifactを復元してrunを最後まで実行できる統合を行うのが適切。
