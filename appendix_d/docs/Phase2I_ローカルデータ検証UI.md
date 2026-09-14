# Phase 2I ローカルデータ検証UI

## 目的

管理対象入力rootへ配置したCSVを、登録済みの不変な列mappingで検査する要求を`/ui/intake`から登録できるようにする。HTTP request内ではCSVを開かず、独立WorkerがPhase 2Gと同じクレンジング・数量照合規則を実行する。

この検査は原本取込、archive、正規化行、業務承認を作成しない。合格しても実データ受入や予測精度を保証しない。

## 構成

- `mapping_dry_run_jobs`: `QUEUED`、`RUNNING`、`SUCCEEDED`、`FAILED`を保持する追記型の実行台帳。相対path、mapping ID、登録者、行上限、時刻、証跡IDだけを保持する。
- `kiban-mapping-dry-run-worker`: PostgreSQLからjobをclaimし、入力rootをread-onlyで参照して証跡rootへ内容アドレス方式JSONを保存する。
- `POST /api/mapping-dry-run-jobs`: `ANALYZE`権限でjobを登録する。登録済みmapping以外は受け付けない。
- `GET /api/mapping-dry-run-jobs`、`GET /api/mapping-dry-run-jobs/{job_id}`: `READ`権限で状態と証跡参照を返す。
- `/ui/intake`: 相対path、登録済みmapping、1〜10,000のsample行上限を指定し、job状態と既存の検証済み証跡を分けて表示する。

入力不備はWorker異常にしない。安全でないpath、未存在file、size、文字コード、ヘッダー、必須列、CSV構造、数量照合の不備は`BLOCKED`証跡になる。予期しない実行障害だけを固定`error_code`で`FAILED`にし、例外本文をAPIへ返さない。

## ローカルテスト手順

以下はWindows PowerShell 7とDocker Desktopを使う手順である。コマンドはrepositoryの`appendix_d`ディレクトリで実行する。

### 1. 前提確認

```powershell
docker version
docker compose version
git status --short
```

`docker version`でClientとServerの両方が表示されることを確認する。既存の未commit変更がある場合は、テスト前後の差分と混同しないよう内容を確認する。

### 2. 正常系テストCSVの作成

```powershell
New-Item -ItemType Directory -Force -Path .\import_input | Out-Null
@'
出荷日,JANコード,商品名称,出荷数量,数量単位,物流拠点,明細種別
2026/09/01,0012345678901,テスト商品A,5,個,テスト拠点,SHIPMENT
'@ | Set-Content -LiteralPath .\import_input\phase2i_sample.csv -Encoding utf8
```

`import_input`は既定の管理対象入力rootである。UIにはPC上の絶対pathを入力せず、このrootからの相対pathだけを入力する。

### 3. PostgreSQL、API、Workerの起動

```powershell
docker compose --profile worker up -d --build postgres api mapping-dry-run-worker
docker compose ps postgres api mapping-dry-run-worker
```

`postgres`が`healthy`、`api`と`mapping-dry-run-worker`が`Up`になることを確認する。APIの起動確認は次のコマンドで行う。

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:58000/health
Invoke-RestMethod -Uri http://127.0.0.1:58000/ready
```

期待値は`health`の`status`が`ok`、`ready`の`status`が`ready`である。起動直後に接続できない場合は数秒待って再実行する。

### 4. UIへの接続

ブラウザーで`http://127.0.0.1:58000/ui/intake`を開く。API tokenへ開発環境の既定値`change-me-local`を入力し、「接続」を押す。このtokenはローカル開発専用であり、本番では使用しない。

### 5. 列mappingの登録

「02 列mappingを登録」を開く。既に同じmappingが選択肢にある場合は登録を省略できる。新規登録する場合は次の値を使用する。

| UI項目 | 入力値 |
|---|---|
| 日付列 | `出荷日` |
| JAN列 | `JANコード` |
| 商品名列 | `商品名称` |
| 数量列 | `出荷数量` |
| 単位列 | `数量単位` |
| center取得方法 | `原本列` |
| center列または固定値 | `物流拠点` |
| 行区分列 | `明細種別` |
| availability mode | `ASSUMED` |
| file mode | `FULL` |
| 日付形式 | `%Y/%m/%d` |
| 許可単位 | `個` |

「列mappingを登録」を押し、登録完了の通知とmapping選択肢への追加を確認する。

### 6. ローカルデータ検証jobの登録

「00 ローカルデータ検証jobを登録」を開き、次の値を指定する。

| UI項目 | 入力値 |
|---|---|
| CSV相対path | `phase2i_sample.csv` |
| 登録済み列mapping | 手順5のmapping |
| 検査する最大行数 | `100` |

「検証jobを登録」を押す。左側の「検証job」に対象が追加され、`待機中`、`実行中`、`完了`の順に進む。表示が変わらない場合は「更新」を押す。

### 7. 正常系の期待結果

「検証job」で`phase2i_sample.csv`を選択し、次を確認する。

- 実行状態が`完了`である。
- 判定が`正規化準備完了`である。
- report SHA-256が表示されている。
- エラーcodeが`—`である。

続いて「ドライラン」の最新項目を選択し、次を確認する。

- 判定が`READY_FOR_NORMALIZATION`（画面表示は`正規化準備完了`）である。
- 検査行1、採用1、隔離0である。
- `MAPPING_CONTRACT`から`QUANTITY_RECONCILIATION`まで9検査がすべて`PASSED`である。
- 制約欄に、サンプル外の品質・全件数量は未検査であることが表示される。

### 8. 入力境界の異常系テスト

同じ画面からCSV相対pathを`../phase2i_sample.csv`として検証jobを登録する。Workerは入力root外へ移動せず、jobは証跡作成済みの`完了`になり、ドライラン判定は`BLOCKED`、`SOURCE_PATH_SAFE`は`FAILED`になることを確認する。

`BLOCKED`は入力検査が安全に拒否された結果である。Worker自体の障害を示す`FAILED`とは区別する。

### 9. 自動回帰テスト

開発用virtual environmentをまだ作成していない場合は次を実行する。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev,api,postgres,test]"
```

Phase 2Iと管理画面の関連テストを実行する。

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_phase2i_local_validation_ui.py tests/test_management_ui.py
.\.venv\Scripts\python.exe -m ruff check forecast_provider tests/test_phase2i_local_validation_ui.py tests/test_management_ui.py
```

期待値はpytestが失敗0件、ruffが`All checks passed!`である。

### 10. ログ確認と停止

```powershell
docker compose logs --tail 100 api mapping-dry-run-worker
docker compose --profile worker stop api mapping-dry-run-worker
```

tracebackや繰り返す接続エラーがないことを確認する。PostgreSQLも停止する場合は`docker compose stop postgres`を実行する。検証履歴を保持するため、通常のテスト終了時はvolumeを削除しない。

Workerの入力mountはread-only、証跡mountだけがwrite可能である。APIは証跡mountをread-onlyで参照し、返却時にchecksumと固定schemaを再検証する。APIとWorkerが同時に初回起動しても、PostgreSQL schema初期化はadvisory lockで直列化する。

## 残る受入作業

実業務CSVによるmapping確認、サンプル外を含む全行正規化、全件数量照合、隔離理由の業務判断は未実施である。ドライラン確認後はPhase 1Xの取込・正規化へ進む。
