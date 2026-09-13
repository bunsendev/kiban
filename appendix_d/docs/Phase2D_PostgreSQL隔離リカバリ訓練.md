# Phase 2D PostgreSQL隔離リカバリ訓練

## 目的

`kiban-db drill`は、稼働DBを復元先にせず、内部生成した一時DBへ最新backupを復元して技術的な復旧可能性を確認する。一時DB名は`kiban_drill_<12桁hex>`だけを許可し、利用者が復元先を指定する入力は持たない。成否にかかわらず`dropdb --if-exists --force`を実行する。

この訓練は開発・検証環境で実行できる。実データ、本番障害、本番storage、本番networkを使わない結果は、本番RTO・RPO、災害復旧、実データ復旧の達成を意味しない。

## 判定順序

1. 元DBのpublic schema定義、sequence状態、table一覧と全行をSHA-256へstreaming変換する。
2. PostgreSQL custom archiveとmanifestを作成し、size、SHA-256、`pg_restore --list`を検証する。
3. 元DBの指紋を再取得する。前後が異なる場合は、backup中に更新された可能性があるため失敗とする。
4. 内部生成した一時DBを`template0`から作り、検証済みarchiveを単一transactionで復元する。
5. 一時DBの指紋を元DBの2回目の指紋と照合する。
6. 一時DBを削除し、削除成功を含む6判定を保存する。

指紋作成は行JSONをC照合順序で並べ、psql出力を1 MiBずつhashへ渡す。行値をPython memoryやレポートへ保持しない。一貫したbackup点を得るため、実運用では書込みを停止してから実行する。前後指紋は停止漏れを検知する補助であり、同じ値へ戻る並行更新まで証明するものではない。

## 実行

開発Composeでは次を実行する。

```powershell
docker compose --profile operations build db-operations
docker compose --profile operations run --rm db-operations drill --backup-dir /backups --report-dir /recovery-reports
```

本番候補構成では、APIと全Workerを停止し、接続roleに対象DBの読取、`CREATEDB`、作成した一時DBの削除権限があることを確認して実行する。

```powershell
docker compose --env-file .env.production -f compose.production.yaml stop api run-worker statsforecast-worker mlforecast-worker timesfm-worker import-worker normalization-worker matching-worker daily-worker acceptance-worker selection-worker lifecycle-scheduler
docker compose --env-file .env.production -f compose.production.yaml --profile operations build db-operations
docker compose --env-file .env.production -f compose.production.yaml --profile operations run --rm db-operations drill --backup-dir /backups --report-dir /recovery-reports
```

終了codeは`DRILL_PASSED`が0、検査不合格が2、設定・レポート保存などCLI自体の失敗が1である。元DBに対する`DROP`、`CREATE`、`RESTORE`は実行しない。

## 不変証跡

レポートは内容全体のSHA-256をファイル名にし、同じ内容を上書きしない。次を保存する。

- `archive_verified`、`source_stable`、`scratch_isolated`、`restore_completed`、`fingerprint_matched`、`scratch_removed`の状態
- archiveと元DB・復元DBのSHA-256、relation件数、PostgreSQL major version
- backup、各指紋、復元、削除、全体の観測時間
- 失敗stageと例外class、Python実行環境

DSN、host、database/user名、password、local path、一時DB名、relation名、行数、行値、例外messageは保存しない。archive manifestは従来どおりDB名を含む運用機密なので、backup領域を権限制御する。レポート領域とbackup領域はGit、Docker build context、配布ZIPから除外する。

## モジュール境界

| module | 責務 |
|---|---|
| `operations/db_archive.py` | DSN分解、custom archive、manifest、checksum、明示復元 |
| `operations/database.py` | 互換entry pointとCLI引数・終了code |
| `operations/recovery/contracts.py` | 判定名、指紋、結果契約 |
| `operations/recovery/fingerprint.py` | schema・table内容のstreaming指紋 |
| `operations/recovery/scratch.py` | 内部生成DBの作成・復元・強制削除 |
| `operations/recovery/runner.py` | 判定順序、失敗処理、必須cleanup |
| `operations/recovery/report.py` | sanitize済み内容アドレス方式JSON |

DB外のsnapshot、原本archive、受入report、model artifactは訓練対象外である。同じ復旧点として各領域のbackupとrestore訓練を別途行う。
