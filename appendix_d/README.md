# ブンセン 予測OSS比較基盤 — 修正完成パッケージ v2.9

v2.8レビューの指摘を反映した予測・比較コアです。
コード、全体仕様、統合仕様、開始ガイド、テスト、人工データデモ、検証記録を同梱しています。
予定完全性、日次状態、少数実品目の受入判定基盤、StatsForecast AutoETS、比較CSV、採用判断台帳、管理画面、role別認可と本番向けHTTP境界まで実装済みです。実データでの受入実行と外部認証基盤を含む本番運用は後続開発です。

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

## Run API / Worker

APIと全Provider依存は`pip install -e ".[api,postgres,statsforecast]"`で追加する。developmentでは`KIBAN_POSTGRES_DSN`、`KIBAN_API_TOKEN`、`KIBAN_API_SUBJECT`、`KIBAN_SNAPSHOT_ROOT`、`KIBAN_REPORT_ROOT`を設定し、`uvicorn forecast_provider.api.factory:from_environment --factory`で起動する。productionでは共有tokenを使わず、複数のsubjectとroleを持つ`KIBAN_API_CREDENTIALS`、`KIBAN_ALLOWED_HOSTS`、HTTPSを必須とする。認証・認可の詳細は[認証・認可とセキュリティ境界](docs/Phase1Q_認証認可とセキュリティ.md)を参照する。snapshotと実験を登録後、保存済みexperiment IDからrunを作る。組込baseline Workerは`kiban-worker --postgres-dsn <DSN> --builtin-baseline --artifact-root <DIR> --work-root <DIR> --worker-id <ID>`、AutoETS Workerは同じ引数に`--statsforecast-ets`を指定して起動する。Dockerでは`docker compose --profile statsforecast-worker up -d --build statsforecast-worker`を使用する。共通実行は[実験SnapshotとBaseline統合](docs/Phase1F_実験SnapshotとBaseline統合.md)、AutoETS固有条件は[StatsForecast AutoETS Provider](docs/Phase1M_StatsForecast_AutoETS.md)を参照する。

Provider適合試験は`POST /api/provider-conformance-tests`へ記録し、`GET /api/providers`でモデル別の固定ランキング掲載可否を確認する。比較は`POST /api/comparisons`へ保存済みrun ID、各runの適合記録ID、truth snapshot IDを指定する。予測値と指標はrun台帳とchecksum検証済みsnapshotからサーバーが再計算する。詳細は[Provider適合試験と比較結果の永続化](docs/Phase1N_評価レジストリ.md)を参照する。

比較CSVは`POST /api/comparisons/{comparison_id}/exports`で発行する。baseline改善率、own/common/official指標、件数、集合・snapshot・Providerの識別子を含み、取得時にもchecksumを検証する。採用判断は`POST /api/adoptions`へ比較、実データ受入case、採用run、fallback、対象、担当者、理由を指定する。正式比較、PASSED、最新APPROVED、日次build一致をサーバーが照合する。詳細は[比較レポートCSVと採用判断](docs/Phase1O_比較レポートと採用判断.md)を参照する。

## 比較・受入・採用管理画面

API起動後にdevelopmentでは`http://127.0.0.1:58000/ui`を開き、設定したtokenを入力する。接続すると認証subjectとroleが表示され、permissionのない操作は無効になる。比較選択、run別指標と系譜の確認、受入caseの業務判断、比較CSVの発行・取得、採用・却下の記録を同じ画面で行える。tokenは画面のメモリ内だけで保持し、更新時には再入力が必要。担当者項目は認証subjectから確定し、採用条件は保存時にサーバーが再検証する。詳細は[比較・受入・採用管理画面](docs/Phase1P_比較受入採用管理画面.md)を参照する。

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
