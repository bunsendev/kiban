# Windows Portable版 実現可能性調査

調査日: 2026-09-29。対象: `bunsendev/kiban` の `main`、commit `e934fe65f4672b0edfe2fa7d9132b1b9f2fa27b6`。本書はコード・設定・既存の検証記録に基づく設計調査であり、Windows Portable版の実機動作、全モデルのWindows互換性、現場導入の成功を宣言しない。業務データ、資格情報、端末固有IDは収録しない。

調査時の検証: Windowsで `ruff check .` は成功。`pytest -q` は820件成功、20件skip、2件失敗。1件は既存のLinux `resource` 専用TimesFM計測テスト、もう1件は `make_release.py --check` が既存5ファイルの未登録/不一致に加え本報告書の未登録を検出したもの。調査結果だけをコミットするため、今回は配布SHA一覧やLinux専用テストを変更しない。従って全テスト合格や配布可能とは判定しない。

## 1. Executive Summary

**条件付きで実現可能。** DockerとWSLは予測アルゴリズムの必須条件ではない。現行配布・起動・隔離の仕組みとして使っている。一方、PostgreSQLは単なる容器ではなく、APIの全Store配線、複数Workerのclaim・lease、DBバックアップと復元に組み込まれている。初手でDBをSQLiteへ置換すると検証範囲が広がる。推奨案は、Windows x64のPC内に版固定のPython実行環境を含む`onedir`アプリとPostgreSQL 17の専用バイナリを同梱し、署名付きLauncherが全プロセスを管理する**PCへコピーする方式**である。TimesFMは別パックとする。

これは配布形態の変更案であり、業務機能の完成を意味しない。現在のField Pilotセットアップは `postgres`、`api`、`pilot-inventory-worker` を起動するが、Baseline/AutoETS/Ridgeを起動しない。正式な投入→日次build→予測更新の接続にも未完了範囲がある。Portable化と同時に予測完走を名乗るには、別の機能受入が必要である（`compose.field-pilot.yaml`、`installer/windows/field-pilot-setup.ps1`、`planning/FIELD_PILOT_GUIDED_FORECAST_FLOW.md`）。

## 2. 現行アーキテクチャと調査範囲

```text
担当者 → Windowsショートカット / PowerShell
       → Docker Desktop / WSL 2 → Compose
       → PostgreSQL 17 + FastAPI/uvicorn + 必要な独立Worker
       → 127.0.0.1 のブラウザーUI
       → Docker volume のDB + %LOCALAPPDATA%\Bunsen\FieldPilot\Data の原本・設定等
```

開発用 `compose.yaml` はPostgreSQL、API、取込・正規化・名寄せ・日次・受入・選定・比較・LifecycleなどのWorkerを定義する。ProviderはBaseline、StatsForecast AutoETS、MLForecast Ridge、TimesFM。`deploy/compose.production.yaml` は別の本番構成、`compose.field-pilot.yaml` は現場PC用の上書き設定である。Field Pilot UIは `/ui/pilot` を起動し、`/ui/easy` も既存Web UIとして存在する。現場配布は初期状態でSHADOW/READ ONLYであり、正式出荷指示を生成しない（`forecast_provider/ui/routes.py`、`docs/FieldPilot_管理者導入運用.md`）。

調査対象は現行ファイルと既存試験記録。実端末でのPortable起動、Windows用wheel一式のインストール、ネイティブPostgreSQL、USB抜去、更新・復元の実測は未実施。以下の「可能」は設計上の見込みで、PoC合格と区別する。

## 3. 現場インストール失敗の候補

現在のIExpress配布物は自己展開後に `powershell.exe -File install.ps1` を起動する（`build_field_pilot_installer.py`）。共有された現場診断では内包スクリプトのSHA-256が一致し、短いPowerShellの `-Command` と `-File` 試験は通り、11:43頃のPowerShell起動イベントは確認された。一方、`install.ps1` の先頭到達マーカーがなく、同スクリプトは早期終了した。AppLockerの「MSI and Script」とCodeIntegrityに該当ブロック記録は見つからず、原因は未確定である。**Docker/WSL以前のbootstrap失敗**と、Docker Desktopのruntime socket起動失敗は別の故障として扱う。前者をPortable化だけで必ず解消できるとは主張しない。

候補はコマンドライン・展開ディレクトリ・PowerShellの起動条件、端末保護製品、IExpress/一時領域、実行ポリシー、実行ファイルの評判など。署名・ハッシュ・Windowsイベント・同一PCでの通常フォルダーからのPoC実行により切り分ける。保護機能の無効化を導入手順としない。Microsoftは署名済みの新規EXEにもSmartScreen警告が出得ると説明している（[SmartScreenの配布ガイド](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation)）。

## 4. Docker依存一覧

| 現行要素 | コード上の使用箇所 | Docker自体の要否 / Windows案 |
| --- | --- | --- |
| PostgreSQL 17 | `compose.yaml`、`compose.field-pilot.yaml` | Compose volumeとhealthcheckは置換可。DBエンジンは当面保持し、Windowsバイナリ、専用data directory、`pg_ctl`へ移す。 |
| API / UI | `Dockerfile.field-pilot`、`forecast_provider/api/factory.py`、`forecast_provider/ui/routes.py` | uvicornはWindowsプロセス化可能。ただし現在のfactoryはPostgreSQL DSNを必須とする。 |
| 原本取込、列mapping、正規化、JAN名寄せ、日次build、受入、選定 | `compose.yaml` と各 `*_worker.py` | Pythonの独立プロセスとして起動可能性あり。起動順、path、read-only境界、失敗時再開を移植する。 |
| Baseline / AutoETS / Ridge、適合試験、比較 | `compose.yaml`、`forecast_provider/worker_process.py` ほか | Docker必須ではない。Windows依存wheel、CPU・メモリ、共有artifact、Provider別workerの動作検証が必要。 |
| TimesFM worker / benchmark | `compose.yaml`、`forecast_provider/timesfm_benchmark` | 実行自体は候補。ただしPyTorch、重み、Linux `resource`・cgroup計測、read-only mount、資源上限を置換する必要がある。 |
| Lifecycle scheduler、在庫Snapshot worker、Field Pilot補助 | `compose.yaml`、`compose.field-pilot.yaml` | Windowsプロセスとして管理可能性あり。所有権・多重起動・時刻再現の試験が必要。 |
| DB運用・preflight・復旧 | `deploy/Dockerfile.operations`、`forecast_provider/operations`、`installer/windows/Kiban.FieldPilot.Recovery.psm1` | `pg_dump`/`pg_restore`/`psql`のWindows同梱と一貫性検査に置換。Linux前提の隔離試験は再設計。 |
| AI補助 | `compose.field-pilot.yaml` の任意 `pilot-ollama`、`forecast_provider/field_pilot/ai_cloud.py` | ローカルAIを標準同梱する必要はない。外部API方式はオフライン・外部送信なし条件では無効化する。 |

つまりコンテナ化されたPython処理の多くは移植候補だが、**Composeの起動管理・volume・権限・resource制限を削除するだけでは同等にならない**。

## 5. WSL依存一覧

| 区分 | 現行箇所 | 対応 |
| --- | --- | --- |
| Windows配布の必須検査 | `installer/windows/field-pilot-setup.ps1` の `wsl.exe --status`、`installer/windows/setup.ps1` の導入 | ネイティブ版Launcherで廃止可能。既存配布は維持。 |
| Docker復旧 | `installer/windows/Kiban.Local.psm1` の `wsl.exe --list/--terminate` | Docker固有。ネイティブ版ではDB/Workerの停止・再起動監督へ置換。 |
| Linux固有の計測・隔離 | `forecast_provider/timesfm_benchmark/measurement.py` の `resource`、benchmarkのcgroup評価 | 条件付き置換。Windows Job Object等で制限し、Windows APIで計測する別契約・証跡版が必要。 |
| Linux filesystem/path/mount | Dockerfile、Composeの `/var/lib/kiban`、`/tmp`、read-only volume | Windows path、ACL、temp領域、atomic file操作を検証する。 |
| 予測ロジック本体 | `forecast_provider/providers`、`forecast_provider/runner.py` | WSL固有呼出しは見当たらない。ただし全依存がWindowsで動くという実証は未了。 |

`resource`を使う汎用Workerの資源計測にはWindows API分岐がある（`forecast_provider/jobs/worker.py`）。TimesFM benchmarkはLinux専用のままである。

## 6. Python依存と配布方法

`Dockerfile` / `Dockerfile.field-pilot` はPython 3.12を使用し、`pyproject.toml` の下限は3.11。固定依存は `requirements*.txt` に分離されている。主要な固定版は pandas 2.2.3、NumPy 2.3.5、StatsForecast 2.1.1、MLForecast 1.1.0、scikit-learn 1.9.1、TimesFM 3.0.2、CPU PyTorch 2.14.0+cpu。TimesFM Providerはライブラリ名と異なり、固定の**2.5 200M重み**を使用する。Python package版と現場配布版は別管理。

| 方法 | 利点 | 注意点・評価 |
| --- | --- | --- |
| Python 3.12 embeddable + app専用wheel群 | Pythonを端末に別途インストールせず、複数Workerが同じ固定環境を使える。中身を追跡しやすい。**最小PoCの候補**。 | `pip`は同梱されず、端末上でpip更新しない。ビルド側でwheelを解決・検証して同梱する。`._pth`、DLL、VC runtime、ネイティブ拡張をWindowsで試験。`.py`ソースをそのまま含む場合、現行の公開Release preflightには通らない。Python公式は第三者packageのアプリ側同梱を想定する（[Python 3.12 Windows利用](https://docs.python.org/3.12/using/windows.html#the-embeddable-package)）。 |
| PyInstaller `onedir` | Launcher/APIを一体化しやすく、利用者にPython不要。公開Releaseのソース非同梱方針に沿う**最終配布の第一候補**。 | 動的import、各Worker entry point、データファイル、DLLを収集するspecが必要。Windows上でビルドし、`onefile`より先に `onedir` を検証する（[PyInstaller manual](https://pyinstaller.org/en/stable/operating-mode.html)）。生成物内のソース・秘密情報の監査と署名も必要。 |
| PyInstaller `onefile` | 見た目は単一EXE。 | 大きな依存を毎回一時展開し、現在の一時展開トラブルと相性が悪い。DB・業務データを単一EXE内に置けない。初期候補にしない。 |
| Nuitka standalone | 実行物と依存を固められる候補。 | compiler・ビルド時間・再現性・ネイティブDLL・複数WorkerをPoCで比較する。[Nuitka manual](https://nuitka.net/doc/user-manual)。 |

PyPIにはStatsForecast 2.1.1のCPython 3.12 Windows x64 wheelがある（[配布ファイル](https://pypi.org/project/statsforecast/2.1.1/)）。ただしこれだけで固定依存全体や本コードのWindows動作は保証されない。P1で全pinのWindows x64 wheel lock、オフライン導入、Baseline→AutoETS→Ridgeのsmokeを実測する。現場PCに `pip` を実行させない。

## 7. PostgreSQL依存分析

ソース上のSQLは31ファイルに91個の一意な `CREATE TABLE IF NOT EXISTS` 名がある。これはSQLite/PostgreSQLの重複定義と機能別schemaを含む**静的棚卸し**であり、現場DBに91表すべてが存在するという意味ではない。主要群は `jobs`（run/origin/expectation/value/failure）、`catalog`（snapshot/experiment）、`ingestion`・`normalization`・`master`・`daily`、`inventory_foundation`、`provider_conformance`・`comparison_campaign`・`evaluation_registry`・`reporting`、`lifecycle`、`operation_events`。Field PilotのInbox/設定/改善/Feedback等には既に別のローカルSQLiteが併存する。

| 性質 | 根拠と移行上の論点 |
| --- | --- |
| relation / constraint / index | `jobs/migrations/001_run_ledger.sql`、`inventory_foundation/schema.sql` 等に外部キー、CHECK、複合PK、索引がある。単純CSVへの退避では関係を失う。 |
| transaction・locking・lease | `jobs/postgres_store.py` の `FOR UPDATE SKIP LOCKED`、worker ID・lease token・期限、`comparison_campaign/store.py` と `inventory_normalization/store.py` の advisory lock。複数Workerの競合と異常終了回収を支える。 |
| JSON・型・時刻 | JSONを列内テキスト/JSONとして扱うStore、`TIMESTAMPTZ`、`UUID`、日付と時刻の契約がある。別DBでは型・比較・時差を検証し直す。 |
| migration・復旧 | Store初期化時のschema適用、`jobs/migrations`、`daily/postgres_upgrade.sql` 等の個別アップグレード。`operations/db_archive.py` と `operations/recovery/fingerprint.py` は `pg_dump`/`pg_restore`/`psql` とPG catalogに依存。 |
| run / artifact / operation log | runと採用履歴はDB、重み以外のartifact・snapshotはファイルにも置く。DBだけのコピーでも、ファイルだけのコピーでも一貫した復旧にならない。 |

**A: PostgreSQL 17同梱** — 現行意味論を最も保ちやすい。Windows版バイナリは提供され、`pg_ctl`でdata directoryを指定して起動・停止できる（[PostgreSQL Windows配布](https://www.postgresql.org/download/windows/)、[pg_ctl 17](https://www.postgresql.org/docs/17/app-pg-ctl.html)）。ただしユーザー権限、ポート占有、AV、サービス登録なしでの再起動、Windows上のDB backup/restoreを実機検証する。DockerのLinux volumeをWindowsの物理DBとして直接コピーしない。互換の`pg_dump` custom archive→検証済み新DBへ`pg_restore`、row/schema照合で移す。

**B: SQLite** — 既存 `SqliteRunStore` などの参照実装とField Pilotの小規模台帳を再利用できる。ただしAPIの `from_environment()` は多数のPostgres Storeを直接組み立て、全体をSQLiteで起動できない。SQLite WALは複数readerと単一writerで、複数Workerのclaim・fairness・長い書込み・バックアップ時のWALを再設計する必要がある（[SQLite WAL](https://www.sqlite.org/wal.html)）。

**C: DuckDB** — 分析結果の読み取り・比較には候補だが、通常の組込モードでは複数プロセスから同じDBへ書く構成に合わない。現在のジョブ台帳の直接代替にしない（[DuckDB concurrency](https://duckdb.org/docs/stable/connect/concurrency.html)）。

**D: SQLite + DuckDB** — SQLiteを制御台帳、DuckDBを分析専用read modelとする余地はあるが、二重DB・整合性・復旧を増やす。現時点のPortable化に必要ない。**E: その他**は専用単一Writer broker等だが、新規実装量が増える。よって現時点ではAを推奨し、Bは別の性能/故障注入PoCに留める。

## 8. Worker構成

推奨は**Launcher配下の独立subprocess**。API、PostgreSQL、必要なWorkerをLauncherが起動し、ready/heartbeatを確認してブラウザーを開く。Providerごとにworker IDとキューを分ける既存設計を保持する。担当者が個別Workerを操作しない。Windows serviceは日常利用に必須としない。常駐が必要になった時だけ管理者導入案として別評価する。`multiprocessing`への一括変更は、Windowsのspawn方式と共有状態を再検証するため避ける。

同じDataRootに対する二重起動を単一インスタンスlockで拒否し、起動失敗時は部分起動プロセスを停止する。異常終了後は残存PIDだけを信用せず実行ファイル・起動識別子・接続先を照合し、DBのlease期限回収後に再開する。停止は新規受付停止→Worker drain/cancel→API停止→`pg_ctl stop`→backup可能な整合状態の順。Windows Job Object等の子プロセス管理、強制終了、電源断、再起動をPoCで検証する。現行のスレッドtimeoutは遅延結果を台帳へ渡さないが計算スレッド自体を必ず停止する設計ではない（`jobs/worker.py`）。

## 9. 予測モデルとUIの互換性

| 機能 | Portable判定 | 必要な確認 |
| --- | --- | --- |
| Baseline | 高い | app専用Python、Windows path、同一snapshotから同一POINT。 |
| AutoETS | 条件付き | StatsForecast/coreforecast等の固定wheel、BLAS/数値差、固定fit/forward、時間。 |
| Ridge | 条件付き | MLForecast/scikit-learn、数値差、JSON artifact復元、時間。 |
| TimesFM 2.5 | 別パックで条件付き | PyTorch CPU、固定925,181,104 byteのcheckpoint、メモリ・起動時間、Windows用計測。重みをrun中にダウンロードしない。 |
| `/ui/easy` / `/ui/pilot` | HTML/JS再利用可 | 現行起動先は`/ui/pilot`。APIのPostgres固定配線、Field Pilotのread-only境界と予測操作の差分を解消する。Web UIをWindows GUIへ全面書換えしない。 |

同じ入力でもOS・BLAS・ライブラリwheelが違えば浮動小数点の完全一致は事前に保証できない。版・入力・出力・許容差を固定した比較試験を行う。正式採用には既存のProvider適合試験と実データ受入を別途通す。

## 10. Windowsセキュリティと権限

署名なしIExpressを署名なしPortable EXEに置換するだけではSmartScreen、Smart App Control、AppLocker、WDAC、端末保護製品による実行制限は残り得る。配布Launcherと同梱EXE/DLLの発行元・ハッシュを監査可能にし、組織の許可ポリシーを管理者と事前確認する。PowerShellを日常操作経路から外すことは有効だが、実行ポリシーを迂回することを導入条件にしない。USB起動制限もPCローカルコピーなら影響を減らせるが、PCへのコピー自体が許可されるかは別問題。

日常のApp・Dataを同一利用者の `%LOCALAPPDATA%` に置き、localhostだけにbindすれば管理者権限なしを目指せる。ただし初回の会社ポリシー許可、署名/配布、VC runtime、PostgreSQLバイナリ、ACL、Firewall例外が必要な場合は管理者作業が残る。APIは `127.0.0.1` 固定、外部listen禁止、既存Host/認証設定を維持する。localhost通信でWindows Firewallの例外が不要かは現場端末で確認する。クラウドAI APIと外部Feedback送信は本条件では既定無効にし、業務データが外部送信されないことを通信試験で確認する。

## 11. USB直接実行とPCへコピー

| 評価 | A: USB直接実行 | B: USB配布→PCへコピー |
| --- | --- | --- |
| 速度・USB抜去 | USB速度・接点に依存。実行中抜去でDB/WAL/artifact/更新が中断 | PC内部ストレージで安定。USB抜去の影響を受けない |
| データ安全性 | USB上にDBを置けば破損・紛失リスクが高い。USB上Appだけでも実行中抜去に弱い | App/Dataを別領域に置き、バックアップを外部媒体へ退避できる |
| 端末保護・権限 | USB実行禁止、署名検査、Defender、企業ポリシーを受けやすい | コピー先も審査対象だが、固定pathと署名で許可・更新を管理しやすい |
| 更新・復旧 | USBごとの版混在と抜去中の更新が問題 | 版付きApp staging→検証→切替、旧版保持が可能 |

**Bを推奨**。USBは配布と暗号化バックアップの媒体に限定する。業務DBを直接USBから起動しない。USBバックアップ中の抜去は検知し、未完成bundleを有効世代に数えない。

## 12. 構成比較

| 観点 | 1 現行Docker/WSL改善 | 2 Native + PostgreSQL | 3 Native + SQLite/DuckDB | 4 ネイティブ単一プロセス等 |
| --- | --- | --- | --- | --- |
| 初回導入 / 日常操作 | WSL・Docker導入が重い / 起動は簡単 | 同梱物・署名が必要 / Launcher一操作 | DB移行が重い / Launcher一操作 | 新規設計が最も大きい |
| 管理者権限 | WSL/Dockerで必要になりやすい | 初回ポリシー次第、日常は不要を目標 | 同左 | 同左 |
| 安定性・データ安全性 | 現行意味論を維持。ただしDocker障害が顕在化 | 現行DB契約を維持。Windows版DB管理が新規 | 単一Writerと全Store再検証が必要 | プロセス再設計が必要 |
| 予測互換性 | 既存Linux wheelのまま | Windows wheelと数値差を試験 | Windows wheelに加えDB差分を試験 | 同左 |
| 更新 / backup / 障害復旧 | 既存部分実装、適用未完成 | App/Data分離とPG dumpを移植 | DB変換・復元を全面変更 | 大規模再設計 |
| 開発工数 / 保守 | 小 / Docker運用負担が継続 | 中 / PG同梱保守が必要 | 大 / SQL・ロック二重保守 | 最大 |
| 配布容量 / PC負荷 | Docker image・WSLの固定負荷 | Python+PG+モデルを同梱。TimesFMは別 | PG分だけ小さくし得るが未計測 | 未計測 |

総合評価は**構成2**。構成1は短期の暫定策として残し、構成3はDB移行の別PoCで比較する。工数は1名の経験者を仮定した粗い設計値で、調達・署名審査・現場承認・実データ整備を含めない。最小PoCは約5～10人日、構成2の受入まで約45～80人日。構成3の全面移行はさらに約30～60人日の追加検証を見込むが、実測・詳細設計前の確定見積ではない。

## 13. 推奨Architecture

```text
担当者 ─ダブルクリック→ 署名付き Bunsen Launcher（単一インスタンス）
                              ├─ app専用 Python 3.12 / FastAPI (127.0.0.1)
                              ├─ 必要なProvider別・取込別Worker（自動監督）
                              ├─ 同梱 PostgreSQL 17 / 専用data directory
                              └─ 既定ブラウザー → /ui/easy または /ui/pilot
PC内  App/<version>  ── 署名・checksum検証、読取専用を目標
      Data/Config, Inbox, Database, Snapshot, Artifact, Result, Log
      Backup/       ── ローカル世代と外部媒体への検証済み複製
USB   署名付きオフライン更新・暗号化バックアップの持ち運び
```

Launcherは端末利用者が直接コマンドを触らないWindows GUIにし、起動・進捗・エラー・終了・診断情報保存を扱う。最終配布はソース非同梱の`onedir`を第一候補とする。PoCではLauncherの最小機能とBaselineだけを検証し、全機能を最初から同梱しない。公開Releaseへ出す前に既存の`release_preflight.py`と生成物内容監査を通す。

## 14. データ保存設計

既存の `%LOCALAPPDATA%\Bunsen\FieldPilot\App\<版>` と `Data` の分離を維持する。推奨: `Data/Inbox/Drop` は投入、`Archive` は原本、`Database` は専用PostgreSQL cluster、`Input`/`Snapshot` は凍結入力、`Artifact` はモデル/文脈、`Reports` は予測・比較、`LocalSettings` はSQLite設定・改善台帳、`Config` はpolicyと公開鍵、`Logs` は診断、`Backup` はローカル世代。実際の現行folderと名称の差は移行manifestで対応し、既存Dataを移動・上書きしない。OneDrive同期フォルダー、USB、ネットワークドライブを稼働DBの保存先にしない。Data容量・ACL・暗号化・保持期間を現場PCで受け入れる。

## 15. 更新設計

現行のGitHub Releases機能は版確認、Ed25519署名Manifest検証、ダウンロード再開、サイズ/SHA-256照合までで、**自動適用、DB migration、更新後smoke、atomic rollbackは未完成**（`planning/GITHUB_RELEASE_AUTO_UPDATE_RESULT.md`）。Portableでも同じ信頼根を使い、オンラインは公開Release、オフラインはUSB上の同一署名Manifest＋packageを入力とする。USBから得た新しい公開鍵だけを無条件採用しない。

更新順は停止予約→FULL backup検証→新Appを別folderへ展開→署名/manifest/checksum・Windowsでの起動前検査→DB migration→新App/API/Worker smoke→切替→旧App保持。失敗時は旧Appへ戻し、DB migration後は事前backupからの復元が必要か判定する。不可逆migrationは自動適用しない。通信断・USB抜去時は既存App/Dataを維持する。

## 16. バックアップ・復元設計

現行の `Kiban.FieldPilot.Recovery.psm1` はDocker内 `pg_dump` と複数SQLiteの一貫したcopy、manifest照合、復元前backupを使用する。Portableでは同梱 `pg_dump`/`pg_restore` を使い、API/Workerを止める境界とPostgreSQL dump・SQLite online backup・原本・snapshot・artifact・設定・公開鍵を同じ世代IDに結ぶ。復元は空の隔離folder/DBへ先に検証してから本体を切り替える。更新前・日次・手動・復元前の世代を分ける。

PC内 `Data/Backup` だけではPC故障を救えない。管理担当者が暗号化USBを接続→画面の「バックアップ」→検証済み表示→安全な取り外し、を目標にする。鍵・資格情報を平文でUSBやRepositoryへ置かず、復元に必要な秘密と手順の保管責任者を決める。USB抜去、容量不足、破損、別PCへの復元、複数版のmigrationを故障注入で試す。

## 17. TimesFM方針

**案B: 追加パック**。標準版はBaseline/AutoETS/Ridge。TimesFMは固定2.5 200M重み約0.86 GiBに加えてPyTorch等が必要で、起動・RAM・配布容量は未計測。既存benchmarkはLinux `resource`/cgroupを前提とする。CPU 2、メモリ4 GiBという現行benchmarkの技術上限はWindows実機や本番SLAの保証ではない（`docs/Phase2B_TimesFM運用計測.md`）。

案Aの標準同梱は全担当PCの負担を上げる。案Cの完全除外は比較機会を失う。Windows専用の重み検証・read-only・測定・メモリ制御をP6で通し、基準未達なら追加パックを有効にしない。推論時は完全オフラインにできる設計だが、モデル取得・ライセンス・配布承認は別管理。

## 18. 現行機能への影響

| 機能 | 現状 | Portable化 | 変更必要 | 主なリスク |
| --- | --- | --- | --- | --- |
| CSV/ZIP投入・Inbox分類・確認待ち | Web/API + SQLite + Docker | 再利用可能性高 | path/監督/権限 | USB・文字コード・原本保存 |
| 正式取込・mapping・JAN・日次build | PG Store + 独立Worker | 機能コード再利用候補 | Windows path/起動/PG接続 | 未接続の正式フローを混同 |
| 在庫Snapshot/FEFO/Shadow | PG + 専用Worker/UI | 再利用候補 | DB・snapshotの移行 | read-only境界と時点 |
| Baseline / AutoETS / Ridge予測 | Provider別Worker | 段階的に移植 | Windows wheel、資源計測 | 数値差・依存DLL |
| TimesFM | Linux専用benchmark + optional worker | 追加パック | PyTorch、checkpoint、計測 | RAM/容量/起動時間 |
| 比較・採用・Lifecycle・run履歴 | PG台帳とWorker | PG維持なら再利用候補 | process監督・migration | lease/排他/再現性 |
| `/ui/easy`・`/ui/pilot` | localhost Web UI | 再利用可能 | Launcher起動先/操作権限 | 予測操作の接続未完了 |
| 操作log・feedback | PG/SQLite + 任意送信 | ローカル記録は再利用 | 外部送信を既定無効 | プライバシー/容量 |
| 更新・backup・rollback | 一部実装 | 再設計が必要 | PGとApp切替のatomicity | 復元失敗 |

## 19. 最小PoC

開発用Windows x64の**新しい空folder**で、配布をPCにコピーし、署名付き候補Launcherをダブルクリックする。`onedir`またはapp専用Python同梱が外部Python/pip/Docker/WSLなしで動くこと、loopback APIがreadyになること、既定ブラウザーが開くこと、人工CSVを読み込んでBaselineのPOINTを計算・ファイル/SQLite参照台帳へ保存すること、終了後に子プロセスが残らず再起動で同じ結果を復元することを検査する。PoCでembeddableを使った場合は、最終配布のソース非同梱`onedir`で同じ試験を再実行する。これは既存の全Field Pilot API・正式PG台帳を通す試験ではないと明記する。データを含むUSB直接実行や本番PCへの配布はまだ行わない。

PoCの合格条件: 操作が起動/投入/予測/結果/終了で完結、Windowsイベントと診断ログに失敗なし、入力SHAと出力が再起動後も一致、通信はloopbackのみ、業務データを外部送信しない、強制終了後に再開できる。失敗時は現行Docker版を維持し、Dataを変換しない。

## 20. 移行Phase、試験、rollback

| Phase | 目的・主変更 | 完了条件 / 試験 | rollback条件 |
| --- | --- | --- | --- |
| P0 調査 | 本書、依存・DB契約・現場端末条件の棚卸し | 現行機能と未検証点を固定 | 調査のみ、現行配布を維持 |
| P1 最小PoC | app専用Python、Launcher、loopback API、人工CSV、Baseline | 空Windowsでオフライン起動・再起動・結果保存 | 起動/終了/署名で失敗、元Dataに触れず撤退 |
| P2 DB・永続化 | Windows PG17、dump移行、DB/原本/snapshot/artifactの世代管理 | schema・行・checksum照合、lease回収、復元訓練 | 照合不一致や復元失敗なら旧Docker DBを保持 |
| P3 モデル/Worker | Baseline、AutoETS、Ridgeと適合/比較Worker | Windows wheel固定、同一snapshot比較、強制終了再開 | 欠損/0・時点・run履歴の不一致で旧版使用 |
| P4 UI統合 | `/ui/easy` と `/ui/pilot`、起動・終了・状態・エラー画面 | 担当者の一連操作と権限境界を受入 | 誤操作/誤表示なら正式導線を開かない |
| P5 更新/backup | オン/オフライン署名更新、FULL backup、migration、rollback | USB抜去・通信断・DB破損を含む故障注入 | backup/smoke/復元未達なら適用禁止 |
| P6 TimesFM | optional pack、Windows資源計測 | 現場相当CPU/RAMでcheckpoint・推論・資源上限合格 | OOM/長時間化ならpack無効 |
| P7 実PC受入 | 現場PCで署名・導入・再起動・電源断・復元・翌日起動 | 担当者操作、精度、ログ、更新、復旧の証跡と業務承認 | 1つでも重大Gate未達なら旧方式へ戻す |

全Phaseで実データをRepositoryへcommitしない。構造とバックアップの変更時はmigration前後のshadow照合を行い、旧DBを削除しない。

## 21. PC性能とリスク

共有された現場PC資料の**端末固有IDを除いた**構成はWindows 11 Pro 25H2 / x64、Intel Core i5-9400、RAM 16 GB、238 GB中114 GB使用（資料時点の概算空き124 GB）。この1台の情報はWindows 10/他PCの受入を代替しない。暫定PoC候補はx64・4コア・RAM 8 GB・空き20 GB、標準運用候補はRAM 16 GB・空き40 GB以上。ただし実際の最低/推奨要件はP1/P3/P6でピークRAM、DB/原本/backup容量、起動時間を測って確定する。TimesFMは16 GB機で同時実行を避けて計測し、余裕がない場合は追加パックを配布しない。空き容量は保持世代と実データ量で増える。

| リスク | 影響 | 先に行う検証 |
| --- | --- | --- |
| PostgreSQLのWindows移行と復旧 | 履歴喪失・二重実行 | logical dump、隔離restore、schema/行hash、電源断 |
| 起動器/端末ポリシー | アプリが開かない | 署名、空folderでの実行、イベント、企業許可条件 |
| Windows数値環境 | 予測の再現性・適合判定 | 固定wheel、同一snapshotの差分と許容差 |
| 子プロセス残留・lease | 二重処理とDBロック | 多重起動、強制終了、再起動、fencing |
| 外部通信・秘密情報 | 業務データ流出 | オフライン起動・通信捕捉・配布内容監査 |
| USB/backup/update | 途中状態と復元不能 | 抜去・容量不足・破損・鍵紛失の故障注入 |
| 現行業務フロー未接続 | 「起動するが予測できない」 | 正式取込→予測の別機能Gateを保持 |

## 22. Q1〜Q10への回答と最終推奨

| 質問 | 回答 |
| --- | --- |
| Q1 Dockerを完全に削除できるか | **設計上可能**。現行配布からは不可。Windows上のDB・API・Worker・バックアップ・隔離の代替を実装/受入後に削除できる。 |
| Q2 WSLを完全に削除できるか | **設計上可能**。現行のWSL検査とDocker復旧手順をネイティブ版から除外し、Linux専用TimesFM計測を置換する。 |
| Q3 Pythonの別途インストール不要か | **可能性高い**。Python 3.12のapp専用同梱またはonedirで提供し、現場PCでpipを使わない。固定wheelのWindows試験が条件。 |
| Q4 PostgreSQLを削除すべきか | **当面残す**。run/lease・全API Store・復旧契約を守る。SQLite全面移行は独立の調査/PoC後に判断する。 |
| Q5 USB直接実行かPCへコピーか | **PCへコピー**。USBは配布とバックアップに限定する。 |
| Q6 管理者権限なしの日常運用は可能か | **目標として可能**。初回の組織ポリシー、署名、VC runtime、ACL等は管理者作業になり得る。現場端末で確認する。 |
| Q7 予測機能はどこまで維持できるか | Baselineは高い見込み、AutoETS/RidgeはWindows依存と数値差の試験後、TimesFMは別パック/受入後。正式自動フローの未実装はPortable化で解消しない。 |
| Q8 TimesFMをどう扱うか | **追加パック**。Windows資源計測と固定重みのオフライン試験に通った端末だけで有効化する。 |
| Q9 完全オフライン運用は可能か | **業務コアは条件付きで可能**。全依存/重み/署名更新を事前配布する。外部AI API、Feedback送信、オンライン更新はオフライン時に使えない。 |
| Q10 最大の技術的リスク | **PostgreSQLの状態・run/lease・ファイルartifactをWindowsへ移し、異常終了と更新失敗後も同じ履歴を復元できること**。 |

最終推奨は**構成2をP1の最小PoCから段階導入**すること。P1合格前に現行Docker配布を撤去せず、現場PCへPortable版を正式配布しない。次の作業は、Windows x64でapp専用Python + Launcher + CSV + Baseline + 保存/再起動のPoCを別branchで作り、署名・端末ポリシーとオフライン動作を検証することである。
