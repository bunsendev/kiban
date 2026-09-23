# ブンセン 予測OSS比較基盤 — 修正完成パッケージ v2.9

v2.8レビューの指摘を反映した予測・比較コアです。
コード、全体仕様、統合仕様、開始ガイド、テスト、人工データデモ、検証記録を同梱しています。
予定完全性、日次状態、少数実品目の受入判定基盤、実データ受入プリフライト、クレンジング・列マッピングドライランとUI起点の検証job・検証済み証跡レビュー、PostgreSQL隔離リカバリ訓練、外部IdP接続プリフライト、StatsForecast AutoETS、MLForecast Ridge、TimesFM 2.5と専用Worker運用計測、比較CSV、採用判断台帳、比較・採用・Lifecycle・原本取込・正規化・JAN名寄せ・商品マスター・データ準備・重要品目選定・実データ受入管理画面、role別認可、OIDC、TLS・監視・DB backup、月次再学習と安全なモデル切替まで実装済みです。実データでの受入・trial・本番復旧訓練と環境固有IdPでのログイン受入は後続作業です。

## 最初に読む

1. CODEX_START_HERE.md
2. docs/統合仕様_v2.9.md（現行契約を一つに統合）
3. docs/実装仕様書_v2.2_完全版.md（基盤全体の要件とフェーズ図）

本文の版とコードの版は別管理です。旧差分文書を読み重ねる必要はありません。

## v2.9修正

- own_metricsを自run自身だけの評価へ修正。
- 正式比較集合を完全runだけから作成。不完全run追加による縮小を防止。
- official_comparison_set_idを追加。正式候補・キー集合を識別。
- 完全run1件は単独評価、2件以上で正式ランキング可能とする。
- カレンダー変数は内部生成、変更される将来変数はknown_at以前の最新版を選ぶ。
- 旧検証記録を更新し、重複コード・内包ZIPを含まない配布に整理。

## Windows PowerShell

Python 3.12で検証。ZIPを展開しappendix_dフォルダで実行します。

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\python.exe demo.py --output demo_output
.\.venv\Scripts\python.exe make_release.py --check
```

## macOS / Linux

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
.venv/bin/python demo.py --output demo_output
.venv/bin/python make_release.py --check
```

全テストの実行はpytest。従来の `python tests/test_builtin_baseline.py` は47件のみなので全件確認を代替しません。
ruffが利用できない場合のcheck_lint.pyは限定的な補助検査であり、正式出荷ではruffも必須です。
100系列規模確認は `python scale_check.py`。デモは人工データ3系列・3年を使用し、実データ精度ではありません。
初回依存インストール以外にAPIキー・ネットワーク接続は不要です。

## 出力

Phase 1BはModelRef/ContextRefをローカルへ保存し、別プロセスで復元するAPIを追加します。
`python artifact_demo.py verify --output artifact_output`で再fitなしの予測一致を確認できます。
形式・使い方・制約は[保存と復元](docs/Phase1B_保存と復元.md)を参照してください。
既定のartifact_outputはGit/配布ZIPから除外します。業務Workerの再開機能は未実装です。

デモは予測CSV、失敗照合台帳CSV、15日累計CSV、比較JSONを作成します。
比較JSONではown/common/officialを区別し、各件数と集合IDを確認してください。

## 配布・更新

test_results.txtはこの版の実測記録です。依存はrequirementsファイル、実行環境は記録を参照。
変更後はテスト・ruffを実行し、検証記録を更新してから `python make_release.py` で再配布します。
最後に `python make_release.py --check` で照合します。ZIPは親フォルダに生成されます。

## 保守・追加開発

APIはcomposition root、route、service、domain、storeの依存方向を固定し、UIはAPI・form・render・workflowを分離する。新機能を既存ファイルへ継ぎ足す前の判断基準と現在の分割方針は[保守開発のモジュール構成](docs/保守開発のモジュール構成.md)を参照する。

## Run API / Worker

APIと軽量な全Provider依存は`pip install -e ".[api,postgres,statsforecast,mlforecast,timesfm,auth]"`で追加する。developmentでは`KIBAN_POSTGRES_DSN`、`KIBAN_API_TOKEN`、`KIBAN_API_SUBJECT`、`KIBAN_SNAPSHOT_ROOT`、`KIBAN_REPORT_ROOT`を設定し、`uvicorn forecast_provider.api.factory:from_environment --factory`で起動する。productionでは外部IdPのJWTまたは更新可能なcredential file、Host allowlist、HTTPSを必須とする。snapshotと実験を登録後、保存済みexperiment IDからrunを作る。組込baseline Workerは`--builtin-baseline`、AutoETS Workerは`--statsforecast-ets`、MLForecast Ridge Workerは`--mlforecast-ridge`、TimesFM専用Workerは`--timesfm-2p5`を指定する。TimesFMのCPU PyTorchと検証済み重みは専用Workerだけに置く。共通実行は[実験SnapshotとBaseline統合](docs/Phase1F_実験SnapshotとBaseline統合.md)、各追加Providerは[StatsForecast AutoETS](docs/Phase1M_StatsForecast_AutoETS.md)、[MLForecast Ridge](docs/Phase1Z_MLForecast_Ridge.md)、[TimesFM 2.5](docs/Phase2A_TimesFM_2p5.md)、月次運用は[継続学習と安全なモデル切替](docs/Phase1S_継続学習とモデル切替.md)を参照する。

複数のProvider専用WorkerはProvider IDでrunキューを分離する。カスタムexecutorは`--executor module:function`と`--provider-id`を必ず同時に指定し、別Providerのrunを取得させない。詳細は[Provider別Worker実行分離](docs/Phase3D_Provider別Worker実行分離.md)を参照する。

作成APIを安全に再送する場合は`POST /api/*`へ`Idempotency-Key`を付ける。同じ認証token・API・要求は保存済み成功応答へ収束し、異なる要求で同じキーを使うと409になる。APIエラーは`code`、`message`、`details`、`request_id`を返す。詳細は[API共通契約](docs/Phase3A_API共通契約.md)を参照する。

予測Workerは全Provider共通で起点attemptごとの推論時間、CPU時間、取得可能なprocess peak memoryを資源台帳へ保存する。固定学習共通Executorは前処理、実fit、推論、model/context artifact容量も分離する。`GET /api/runs/{run_id}`または`GET /api/runs/{run_id}/resources`で確認できる。ADMINは`POST /api/resource-unit-prices`へmetric単位の単価、通貨、取得日、参照元を登録する。未登録単価は0円にせずNULLとなり、比較CSVにも時間・資源・費用列が追加される。詳細は[Provider共通の資源・費用台帳](docs/Phase3B_資源費用台帳.md)を参照する。

`/ui/resources`ではrun一覧、資源集計、origin・attempt明細、単価履歴を参照できる。ADMINは同じ画面でProvider共通または個別単価を登録でき、比較画面にもrun別の推論時間と総費用を表示する。操作と権限は[資源・費用管理画面](docs/Phase3C_資源費用管理画面.md)を参照する。

`/ui/analysis`では保存済みdataset snapshotとProvider・モデルを選び、メタデータ既定値による実験作成、run登録、進捗確認、比較作成までを順番に操作できる。`QUEUED`が続く場合は表示されたProviderの専用Workerを確認する。比較後は`/ui`で指標、系譜、CSV、採用条件を確認する。操作と安全条件は[分析実行ワークスペース](docs/Phase3E_分析実行ワークスペース.md)を参照する。

同じsnapshotで複数OSSモデルを検証するときは、`/ui/analysis`の「比較セットをまとめて開始する」で2〜12モデルと評価方式を選択する。実験、Provider適合試験、予測runが一括登録され、全モデル完了後は独立Workerが比較結果を自動生成する。モデル別進捗、失敗理由、自動比較の状態と結果導線をキャンペーンカードで追跡できる。同じ操作の再送は同一キャンペーン・runへ収束する。詳細は[OSS比較キャンペーン](docs/Phase3I_OSS比較キャンペーン.md)と[比較キャンペーン自動完了](docs/Phase3J_比較キャンペーン自動完了.md)を参照する。

指定実データZIPの全ファイル照合、在庫mapping診断、出荷snapshotの再集計照合、Baseline・MLForecast Ridge・StatsForecast AutoETS・TimesFM 2.5の比較は[実データによる予測OSS比較結果](docs/実データOSS比較結果_2026-09-19.md)を参照する。精度、資源負荷、費用情報の充足状況を踏まえた段階採用案は[予測OSSモデル採用提案](docs/OSSモデル採用提案_2026-09-20.md)、業務担当者向けの説明とクラウド月額試算は[非エンジニア向け予測OSSとクラウド導入提案](docs/非エンジニア向け_予測OSSとクラウド導入提案_2026-09-20.md)にまとめた。

Windows現場PCでは「予測OSS分析を起動」をダブルクリックすると、Docker Desktop、データ準備Worker、Baseline、StatsForecast AutoETS、MLForecast Ridge、Provider適合試験、自動比較Workerをまとめて起動し、全serviceとProvider heartbeatを確認してから`/ui/analysis`を開く。TimesFMは空きメモリを確認する「TimesFM分析を追加起動」から明示的に追加する。詳細は[Windows予測OSS分析ランチャー](docs/Phase3K_Windows予測OSS分析ランチャー.md)を参照する。

分析実行画面はProvider Workerの処理中、待機中、応答遅延、未起動、待機・実行中run数を表示する。Workerは起動中と長時間推論中にheartbeatを更新し、再起動時は旧processの更新を拒否する。運用判断とAPI契約は[Worker稼働状態とキュー診断](docs/Phase3F_Worker稼働状態とキュー診断.md)を参照する。

builtin baselineは実測`available_at`を持つOBSERVED snapshotでも区間予測を実行できる。TRAIN内の
各historical originで当時到着済みの履歴だけから残差を作るため、後日到着した値を過去へ混入
させない。契約と検証条件は[OBSERVED時点再現区間予測](docs/Phase3G_OBSERVED時点再現区間予測.md)を参照する。

TimesFM専用Workerを実業務runへ使う前に、`docker compose --profile timesfm-benchmark run --rm timesfm-benchmark`で固定checkpoint、cgroup隔離、モデル初期化、warm-up後の推論時間、CPU時間、peak RSSを確認する。既定はCPU 2、memory 4 GiB、人工3系列、context 512日、horizon 15である。JSONレポートは`timesfm_benchmark_output`へ内容アドレス方式で保存される。詳細は[TimesFM運用計測](docs/Phase2B_TimesFM運用計測.md)を参照する。

実業務原本を配置する前に、`docker compose --profile preflight run --rm --build real-data-preflight`を実行する。inputの実効read-only、archive・snapshot・受入・証跡rootのwrite、領域分離、PostgreSQL 17の必須23 relationとWorker権限を10項目で確認する。`READY_FOR_DATA`は投入準備完了だけを示し、実データ受入や業務判断ではない。詳細は[実データ受入プリフライト](docs/Phase2C_実データ受入プリフライト.md)を参照する。

PostgreSQLのbackupを隔離された一時DBへ復元して検査する場合は、`docker compose --profile operations run --rm --build db-operations drill --backup-dir /backups --report-dir /recovery-reports`を実行する。元DBの書換えは行わず、前後安定性、archive、復元指紋、一時DB削除を検査する。詳細は[PostgreSQL隔離リカバリ訓練](docs/Phase2D_PostgreSQL隔離リカバリ訓練.md)を参照する。

OIDC modeでは管理画面の「IdPでログイン」からAuthorization Code + PKCEを使用できる。IdPに`https://<domain>/ui/auth/callback`を登録し、authorization URL、token URL、public client IDを設定する。詳細は[OIDC PKCEログイン](docs/Phase2E_OIDC_PKCEログイン.md)を参照する。

環境固有IdPの設定後、ログインを試す前に`docker compose --profile preflight run --rm --build oidc-preflight`を実行する。Discovery、endpoint完全一致、Authorization Code、PKCE S256、署名方式、JWKS鍵を14項目で検査する。詳細は[外部IdP接続プリフライト](docs/Phase2F_外部IdP接続プリフライト.md)を参照する。

実業務原本を台帳へ登録する前に、`KIBAN_MAPPING_SOURCE`へ入力root内の相対pathを設定し、`docker compose --profile mapping-preflight run --rm --build mapping-dry-run`を実行する。既存のPhase 1H規則で文字コード、ヘッダー、列マッピング、先頭1,000行のクレンジング、数量照合を無更新で検査する。証跡には原値、path、列名、数量を保存しない。詳細は[クレンジング・列マッピングドライラン](docs/Phase2G_クレンジング列マッピングドライラン.md)を参照する。

APIは`KIBAN_MAPPING_DRY_RUN_DIR`をread-onlyで参照し、ファイル名と内容のSHA-256、重複JSON key、固定schema、ID、判定整合性を要求する。検証済み証跡と除外件数は`GET /api/mapping-dry-runs`、詳細は`GET /api/mapping-dry-runs/{report_sha256}`で参照できる。詳細は[マッピングドライラン証跡レビュー](docs/Phase2H_マッピングドライラン証跡レビュー.md)を参照する。

UIから検証を開始する場合は`docker compose --profile worker up -d --build api mapping-dry-run-worker`で専用Workerを起動する。`/ui/intake`で入力root内のCSV相対path、登録済みmapping、sample行上限を指定すると、APIがjobを登録し、WorkerがPhase 2G検査を実行する。詳細は[ローカルデータ検証UI](docs/Phase2I_ローカルデータ検証UI.md)を参照する。

初めて検証する利用者は`/ui/intake`の3手順ウィザードを使う。入力root内のCSV候補とヘッダーを安全に確認し、対応付けとの不足列を実行前に案内する。登録後は完了まで自動更新し、日本語の判定・修正方法へ移動する。詳細は[初回データ検証ウィザード](docs/Phase2J_初回データ検証ウィザード.md)を参照する。

ローカル開発環境では`/ui/intake`から100 MB以下のCSVを直接アップロードできる。アップロードしたCSVは自動選択され、列の対応付け、分析、合格または隔離理由の確認まで一続きで操作する。準備と操作は[クライアントCSVアップロード検証](docs/Phase2L_クライアントCSVアップロード検証.md)を参照する。

Windows現場PCへ導入する場合は、配布ZIPを展開して`現場PCセットアップ.cmd`を実行する。WSL 2とDocker Desktopの不足を検出し、環境生成、service構築、readiness確認、ショートカット作成まで進める。日常操作はデスクトップの起動・停止・状態確認を使用する。詳細は[Windows現場PC自動セットアップ](docs/Phase2M_Windows現場PC自動セットアップ.md)を参照する。

ローカル環境を一続きで確認する場合は、Docker ComposeでPostgreSQL、API、検証Workerを起動し、tokenを`KIBAN_API_TOKEN`へ設定して`kiban-local-validation-acceptance --source-path <相対CSV> --mapping-id <mapping ID>`を実行する。Docker Desktopのruntime socket障害を含む準備、復旧、UI受入は[ローカル検証環境と実動受入](docs/Phase2K_ローカル検証環境と実動受入.md)を参照する。

## 本番運用

`deploy/compose.production.yaml`はCaddy、API、PostgreSQL、全Workerとlifecycle schedulerを分離し、外部へは80/443だけを公開する。APIは`/health`、`/ready`、認証付き`/metrics`を提供し、変更操作をsubject付きJSON logへ出力する。DB操作は`kiban-db backup|verify|restore|drill`またはproduction Composeの`db-operations`を使用する。導入・rotation・復元停止手順は[本番運用基盤](docs/Phase1R_本番運用基盤.md)、訓練は[PostgreSQL隔離リカバリ訓練](docs/Phase2D_PostgreSQL隔離リカバリ訓練.md)を参照する。

Provider適合試験は`/ui/analysis`の保存済み実験から開始できる。APIは`POST /api/provider-conformance-jobs`でjobだけを登録し、Provider別Workerが人工データで固定7項目を実行して`POST /api/provider-conformance-tests`と同じ評価台帳へ自動保存する。画面は待機・実行中・失敗理由・正式比較可否を表示する。比較は保存済みrun、実験条件に一致する適合記録、truth snapshotからサーバーが再計算する。詳細は[Provider適合試験の自動実行](docs/Phase3H_Provider適合試験自動化.md)と[Provider適合試験と比較結果の永続化](docs/Phase1N_評価レジストリ.md)を参照する。

比較CSVは`POST /api/comparisons/{comparison_id}/exports`で発行する。baseline改善率、own/common/official指標、件数、集合・snapshot・Providerの識別子を含み、取得時にもchecksumを検証する。採用判断は`POST /api/adoptions`へ比較、実データ受入case、採用run、fallback、対象、担当者、理由を指定する。正式比較、PASSED、最新APPROVED、日次build一致をサーバーが照合する。詳細は[比較レポートCSVと採用判断](docs/Phase1O_比較レポートと採用判断.md)を参照する。

## 担当者向けかんたん予測画面

`http://127.0.0.1:58000/ui/easy`は、PC操作に不慣れな担当者向けの入口である。CSV・ZIPのアップロード、または管理対象フォルダー内のCSV選択から、互換性のある列mappingを自動選択し、検証結果を緑・黄・赤と件数で確認するところまでを1画面で行う。結果はデータ形式の確認であり、予測値や予測精度ではない。token、mapping ID、job IDなどの管理情報は通常操作から隠し、元ファイルを変更しないことを明示する。詳細は[担当者向けかんたん予測画面](docs/担当者向けかんたん予測画面.md)と[担当者向け操作マニュアル](docs/担当者向け操作マニュアル.md)を参照する。

`http://127.0.0.1:58000/ui/feedback`は管理者向けの操作改善レポートである。担当者画面の手順別到達数、所要時間、入力方法、失敗種別、最近の操作を表示し、分析用CSVを出力する。記録はPostgreSQLへ追記し、`KIBAN_OPERATION_EVENT_RETENTION_DAYS`で保持日数を設定する。初期値は180日である。ファイル名、path、ファイル内容、接続コード、自由入力は収集しない。詳細は[操作改善ログ運用](docs/操作改善ログ運用.md)を参照する。

## 比較・受入・採用管理画面

API起動後にdevelopmentでは`http://127.0.0.1:58000/ui`を開き、設定したtokenを入力する。接続すると認証subjectとroleが表示され、permissionのない操作は無効になる。比較選択、run別指標と系譜の確認、受入caseの業務判断、比較CSVの発行・取得、採用・却下の記録を同じ画面で行える。tokenは画面のメモリ内だけで保持し、更新時には再入力が必要。担当者項目は認証subjectから確定し、採用条件は保存時にサーバーが再検証する。詳細は[比較・受入・採用管理画面](docs/Phase1P_比較受入採用管理画面.md)を参照する。

## Lifecycle運用画面

`http://127.0.0.1:58000/ui/lifecycle`では、Lifecycle計画、現在championとrevision、月次cycle、切替履歴、trial予測・評価を参照できる。ANALYZE権限でscheduler、cycle処理、予測事前記録、APPROVE権限で計画作成、昇格、rollback、trial評価を操作する。操作後はサーバー台帳を再読込する。詳細は[Lifecycle運用画面](docs/Phase1T_Lifecycle運用画面.md)を参照する。

## 取扱期間・欠測判定画面

`http://127.0.0.1:58000/ui/readiness`では、商品×centerの取扱期間履歴と日次buildのファイル完全性、6種類の日次状態、欠測理由を確認できる。APPROVE権限で取扱期間を登録し、日次行は状態・商品・centerで絞り込む。欠測を0へ変換せず、操作後はサーバー台帳を再読込する。詳細は[取扱期間と欠測判定画面](docs/Phase1U_取扱期間と欠測判定画面.md)を参照する。

## 重要品目候補・選定画面

`http://127.0.0.1:58000/ui/selection`では、成功済み日次buildから候補算出jobを登録し、独立Workerが算出した数量・構成比・変動係数・出荷0率・欠損率・JAN変更・分類・対象centerを確認できる。ANALYZE権限でjobを登録し、APPROVE権限でINITIAL 3〜5品目またはFULL 20〜50品目の選定版をcenter・理由付きで確定する。詳細は[重要品目候補・選定画面](docs/Phase1V_重要品目選定画面.md)を参照する。

## 実データ受入画面

`http://127.0.0.1:58000/ui/acceptance`では、INITIAL 3〜5品目の選定版と成功済み日次buildから受入caseを登録し、独立Workerによる10項目の技術判定、JSON/MarkdownレポートのURI・checksum、業務判断履歴を確認できる。ANALYZE権限でcaseを登録し、APPROVE権限で技術判定完了後の判断を版・理由付きで記録する。詳細は[実データ受入画面](docs/Phase1W_実データ受入画面.md)を参照する。

## 原本取込・正規化画面

`http://127.0.0.1:58000/ui/intake`では、CSVアップロード、ローカルデータ検証jobの登録・状態、検証済みマッピングドライラン証跡、除外された証跡件数、取込job、原本checksum・encoding・重複/訂正系譜、版付き原本採用、列mapping、正規化job、隔離行、数量照合を確認・操作できる。各処理は独立Workerが実行し、正規化行は状態条件付きで100件ずつ表示する。詳細は[原本取込・正規化画面](docs/Phase1X_原本取込正規化画面.md)、[ローカルデータ検証UI](docs/Phase2I_ローカルデータ検証UI.md)、[クライアントCSVアップロード検証](docs/Phase2L_クライアントCSVアップロード検証.md)を参照する。

## JAN名寄せ・商品マスター画面

`http://127.0.0.1:58000/ui/matching`では、成功済み正規化jobから名寄せjobを登録し、独立Workerが生成した左右JAN、名称類似度、期間、center別数量、候補理由を確認できる。APPROVE権限でcanonical product、4種類の版付き判断、JAN有効期間を理由付きで追記する。名称一致だけでは商品を統合せず、操作後はサーバー台帳を再読込する。詳細は[JAN名寄せ・商品マスター画面](docs/Phase1Y_JAN名寄せ商品マスター画面.md)を参照する。

ソース編集後、ハッシュ再生成前の配布整合テスト失敗は想定内ですが、その状態で出荷しないでください。

## 原本取込

入力ファイル・フォルダ・ZIPを`KIBAN_IMPORT_DIR`へ置き、`POST /api/imports`へrootからの相対pathを指定する。`kiban-import-worker --postgres-dsn <DSN> --input-root <DIR> --archive-root <DIR>`がHTTP外で処理する。詳細は[原本取込台帳](docs/Phase1G_原本取込台帳.md)。

## 出荷行正規化

`POST /api/mappings`で明示的な列mappingを登録し、採用原本IDとmapping IDを`POST /api/normalizations`へ指定する。`kiban-normalization-worker --postgres-dsn <DSN>`が別プロセスで正規化し、結果は`GET /api/normalizations/{id}`、集計は`GET /api/quality`で確認する。訂正版候補は`POST /api/source-selections`による担当者・理由付きの採用が必要。詳細は[出荷行正規化と数量照合](docs/Phase1H_出荷行正規化と数量照合.md)。

## JAN名寄せと取扱期間

成功済みnormalization IDを`POST /api/matching/jobs`へ指定し、`kiban-matching-worker --postgres-dsn <DSN>`で候補を生成する。名称一致だけで自動統合せず、canonical productを作成して4種類の判断を承認者・理由・版付きで記録する。JAN有効期間と商品×center取扱期間は両端を含み、同じ版の重複を拒否する。詳細は[JAN名寄せと取扱期間](docs/Phase1I_JAN名寄せと取扱期間.md)。

## 日次状態とdataset snapshot

`POST /api/file-schedules`で予定された論理ファイルを固定し、必要に応じて`POST /api/closed-days`で時点付き休業日を登録する。採用済みnormalization、JAN版、取扱期間版、選定系列、TRAIN/TEST期間を`POST /api/daily-builds`へ指定すると、`kiban-daily-worker --postgres-dsn <DSN> --output-root <DIR>`が6種類の日次状態を決定し、checksum付きsnapshotをcatalogへ登録する。Dockerでは`docker compose --profile worker up -d --build daily-worker`で日次Workerだけを起動できる。詳細は[予定完全性と日次状態](docs/Phase1J_予定完全性と日次状態.md)。

## 少数実品目の受入判定

`POST /api/acceptance-cases`で成功済み日次build、3〜5品目、availability mode、品質閾値を凍結する。`kiban-acceptance-worker --postgres-dsn <DSN> --output-root <DIR>`はsnapshot接続、CSV checksum、全暦日行、系列別利用可能日数・欠測率・不完全率を検査し、JSON/Markdownレポートを発行する。匿名データは`DRY_RUN`となり、実データ受入として承認できない。詳細は[少数実品目の受入](docs/Phase1K_少数実品目受入.md)。

## 重要品目候補と選定版

全候補商品を含む成功済み日次buildを`POST /api/selection-candidate-jobs`へ指定する。`kiban-selection-worker --postgres-dsn <DSN>`は、欠損を0へ変換せずに数量・構成比・変動係数・出荷0率・欠損率を算出し、JAN変更、業務指定、対象centerとともに保存する。候補確認後、初期3〜5品目または拡大20〜50品目を対象center・理由・担当者付きで`POST /api/selections`へ登録する。同じ`selection_version`は上書きできない。詳細は[重要品目候補と選定版](docs/Phase1L_重要品目候補と選定版.md)。

旧版のModelRef/stateは再利用せずfitから実行します。v2.8の生データ将来列はknown_at付き版へ移行します。
元の提出ZIPは変更していません。既存プロジェクトへ導入する際は作業ブランチで差分を確認してください。
