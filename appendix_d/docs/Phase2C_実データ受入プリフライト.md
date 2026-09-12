# Phase 2C 実データ受入プリフライト

Phase 2Cは、実業務原本をPhase 1Xへ投入する前に、保存領域とPostgreSQLがPhase 1X〜1Kの実行条件を満たすか検査する。原本の本文・ファイル名は読まず、環境だけを確認する。結果は`READY_FOR_DATA`または`BLOCKED`であり、実データの受入結果ではない。

## 検査境界

| check | 条件 |
|---|---|
| `ROOTS_PRESENT` | 5つのrootが存在するdirectory |
| `ROOTS_READABLE` | 実行userが全rootを参照可能 |
| `ROOTS_NO_SYMLINK` | root pathとその構成要素にsymlinkがない |
| `ROOTS_DISJOINT` | root同士が同一・親子関係でない |
| `ROOTS_OUTSIDE_APPLICATION` | 実行時application rootの外にある |
| `ROOT_ACCESS_BOUNDARY` | inputはread-only、残るrootはread-write |
| `POSTGRES_REACHABLE` | PostgreSQLへ5秒以内に接続できる |
| `POSTGRES_VERSION` | PostgreSQL major versionが17 |
| `POSTGRES_SCHEMA` | Phase 1X〜1Kの必須23 relationが存在する |
| `POSTGRES_PRIVILEGES` | 必須relationへのSELECT・INSERT・UPDATE権限がある |

read-write判定は`.kiban-preflight-<random>.tmp`という1 byteの一時probeを作成して直ちに削除する。input rootでは同じ操作が失敗することを確認する。probe名、directoryの内容、root pathは証跡へ保存しない。

## 開発環境での実行

PowerShellで`appendix_d`へ移動し、Git管理外のdirectoryを準備する。

```powershell
New-Item -ItemType Directory -Force import_input, raw_archive, snapshot_input, acceptance_output, preflight_output
docker compose up -d postgres
docker compose --profile preflight run --rm --build real-data-preflight
```

Composeはinputをread-only、archive・snapshot・acceptance・preflightをread-writeでmountする。CLIはコンテナ内の`/app`をapplication rootとして検査する。成功時の標準出力は次の識別情報だけを返す。

```json
{
  "outcome": "READY_FOR_DATA",
  "preflight_id": "<condition-sha256>",
  "report_sha256": "<report-sha256>",
  "report_uri": "file:///var/lib/kiban/preflight/real-data-preflight/<sha256>.json"
}
```

終了codeは`READY_FOR_DATA`が0、技術条件不足の`BLOCKED`が2、引数・secret file・保存エラーが1である。

## 本番候補環境

`deploy/.env.production.example`を参考に、次の5 directoryを互いに分離したアクセス制限領域へ作成する。

- `KIBAN_IMPORT_DIR`: 担当者が配置し、Workerからread-only。
- `KIBAN_RAW_ARCHIVE_DIR`: import Workerだけが原本を追記する。
- `KIBAN_SNAPSHOT_DIR`: daily Workerが発行し、API・受入Workerはread-onlyで参照する。
- `KIBAN_ACCEPTANCE_DIR`: acceptance Workerが品質reportを発行する。
- `KIBAN_PREFLIGHT_DIR`: プリフライト証跡だけを保存する。

PostgreSQL DSNは`KIBAN_POSTGRES_DSN_FILE`のsecret fileで渡し、コマンドラインやenv fileへ平文を書かない。

```bash
docker compose --env-file deploy/.env.production \
  -f deploy/compose.production.yaml \
  --profile preflight run --rm --build real-data-preflight
```

証跡はformat version、固定検査条件、pathを除いたroot別の真偽値、PostgreSQL major version・relation件数・不足relation、10判定、実行環境を持つ。内容のSHA-256をファイル名にし、既存内容を上書きしない。DSN、database/user名、local path、directory entry、原本名を含めない。

## `READY_FOR_DATA`後の順序

1. 取込対象をinput rootへ配置し、`/ui/intake`から相対pathだけを登録する。
2. import・normalization Workerを実行し、checksum、encoding、隔離、元数量照合を確認する。
3. `/ui/matching`でcanonical product、JAN判断、有効期間を版付きで確定する。
4. `/ui/readiness`で予定完全性、取扱期間、6種類の日次状態を確認する。
5. 3〜5品目のINITIAL selectionと受入caseを作り、技術判定と担当者判断を分けて記録する。

## 制約

プリフライトは原本を読まず、実データcaseも作成しない。`READY_FOR_DATA`は実データの数量一致、妥当性、予測精度、業務効果、担当者承認、本番SLA、backup・restore訓練を保証しない。実データと生成reportはGit、Docker build context、配布ZIPへ含めない。
