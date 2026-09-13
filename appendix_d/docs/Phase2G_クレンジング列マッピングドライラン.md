# Phase 2G クレンジング・列マッピングドライラン

## 目的

実業務原本を取込台帳へ登録する前に、CSVの文字コード、ヘッダー、列マッピング、クレンジング結果、数量照合を読取専用で試す。`READY_FOR_NORMALIZATION`は検査したサンプルが既存のPhase 1H正規化規則を通過したことだけを示し、全件品質、実データ受入、予測精度、業務承認を表さない。

## 実行

入力CSVは`KIBAN_IMPORT_DIR`内へ置き、rootからの相対pathを指定する。列マッピングJSONは[設定例](../deploy/mapping.example.json)を複製して、実際のヘッダー、日付形式、単位、行区分へ合わせる。

```powershell
$env:KIBAN_MAPPING_SOURCE = "sample.csv"
docker compose --profile mapping-preflight run --rm --build mapping-dry-run
```

本番Composeの構成を使う場合は、`KIBAN_IMPORT_DIR`、`KIBAN_MAPPING_FILE`、`KIBAN_MAPPING_SOURCE`、`KIBAN_MAPPING_DRY_RUN_DIR`を本番用`.env`へ設定する。

```powershell
docker compose --env-file deploy/.env.production `
  -f deploy/compose.production.yaml --profile mapping-preflight `
  run --rm --build mapping-dry-run
```

終了codeは`READY_FOR_NORMALIZATION`が0、`REVIEW_REQUIRED`または`BLOCKED`が2、入力・証跡保存などの実行失敗が1である。標準出力は`dry_run_id`、`outcome`、`report_uri`、`report_sha256`だけを返す。

## 判定

既定では先頭1,000行、最大10,000行を検査する。入力CSVは既定100 MB、マッピングJSONは64 KiBを上限とする。

| 判定 | 条件 |
|---|---|
| `MAPPING_CONTRACT` | Phase 1Hと同じ列マッピング契約を満たす |
| `SOURCE_PATH_SAFE` | 入力root内の通常ファイルであり、絶対path、親移動、symlinkを使わない |
| `SOURCE_SIZE_LIMIT` | 空でなく設定した上限以下である |
| `SOURCE_ENCODING` | BOM付きUTF-8、UTF-8、CP932のいずれかで厳密に読める |
| `HEADER_UNIQUE` | CSVヘッダーが重複しない |
| `REQUIRED_COLUMNS` | マッピングが参照する全列が存在する |
| `SAMPLE_ROWS` | データ行を1件以上検査できる |
| `SAMPLE_ACCEPTANCE` | サンプル内に隔離行がない |
| `QUANTITY_RECONCILIATION` | 解釈可能数量が採用行と隔離行へ漏れなく分かれる |

構造や契約に問題があれば`BLOCKED`、契約は読めるが隔離行があれば`REVIEW_REQUIRED`、全判定合格なら`READY_FOR_NORMALIZATION`とする。隔離理由は固定codeと件数だけを保存する。

## 証跡と秘匿

レポートは`mapping_dry_run_output/mapping-dry-run`へ内容アドレス方式で原子的に保存する。原本path、ファイル名、ヘッダー名、JAN、商品名、center、日付、数量、行値、例外本文は保存しない。入力とマッピングはSHA-256で識別し、判定、件数、上限、文字コード、実行時刻だけを保存する。

Compose serviceはnetworkを無効化し、入力rootとマッピングをread-only mountする。ドライランはPostgreSQLへ接続せず、原本archive、取込job、列マッピング台帳、正規化job、正規化行を作成しない。

## モジュール境界

| module | 責務 |
|---|---|
| `mapping_dry_run/contracts.py` | 上限、判定ID、入力失敗の固定契約 |
| `mapping_dry_run/loader.py` | path境界、サイズ、文字コード、マッピング読込 |
| `mapping_dry_run/inspector.py` | Phase 1H共通規則によるCSVサンプル検査 |
| `mapping_dry_run/report.py` | 内容アドレス方式の原子的な証跡保存 |
| `mapping_dry_run/runner.py` | 判定統合と秘匿済みレポート生成 |
| `mapping_dry_run/cli.py` | 引数、標準出力、終了code |

`READY_FOR_NORMALIZATION`の後も、実取込ではPhase 1Gの原本保存と採用、Phase 1Hの全行正規化・隔離・数量照合を実施する。サンプル外の不正行や全件合計の差異は実取込の結果で確認する。
