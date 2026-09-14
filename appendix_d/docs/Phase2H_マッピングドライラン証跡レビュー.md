# Phase 2H マッピングドライラン証跡レビュー

## 目的

Phase 2Gが出力した秘匿済みの内容アドレス方式JSONを、原本取込前に管理画面で確認できるようにする。画面は証跡ファイルを直接読まず、認証付きAPIがchecksum、schema、ID、判定整合性を再検証した応答だけを表示する。

`READY_FOR_NORMALIZATION`は検査したサンプルの技術判定であり、サンプル外の全行品質、実データ受入、業務承認、予測精度を表さない。

## API

READ権限を持つ利用者は次のendpointを使用する。

| endpoint | 内容 |
|---|---|
| `GET /api/mapping-dry-runs?limit=100` | 新しい順の検証済み証跡、検証済み総数、除外総数 |
| `GET /api/mapping-dry-runs/{report_sha256}` | 指定した検証済み証跡の詳細 |

`limit`は1〜200である。存在しないchecksumまたは不正な形式は404、存在する証跡のchecksum・形式が不正な場合は409を返す。エラー応答にファイルpath、内容、解析例外を含めない。

## 証跡検証

APIは応答を生成するたびに次を検証する。

- 証跡directoryと証跡がsymlinkでない通常のdirectory・fileである。
- ファイル名が64桁小文字SHA-256で、拡張子が`.json`である。
- 内容が空でなく256 KiB以下で、ファイル名と内容のSHA-256が一致する。
- UTF-8 JSONとして読め、重複keyと未知のtop-level項目がない。
- format version、実行条件、上限、check ID、状態、隔離理由codeが固定契約に一致する。
- `dry_run_id`が実行条件から再計算した値と一致する。
- `READY_FOR_NORMALIZATION`、`REVIEW_REQUIRED`、`BLOCKED`が検査状態と観測件数に一致する。
- 制約一覧が発行時の固定契約に一致する。

一覧では検証できない証跡を返さず、除外件数だけを表示する。これにより改変された証跡を担当者が正常な結果として参照することを防ぐ。

## 公開項目

APIは次の固定項目だけを返す。

- report SHA-256、dry run ID、mapping ID、原本SHA-256、実行時刻。
- サンプル行数とファイルサイズの上限。
- 総合判定、check IDと`PASSED`・`FAILED`。
- 検査行、採用行、隔離行、打切り状態、固定code別の隔離理由件数。
- 判定の固定制約。

証跡に含まれるcheckの実測値・期待値はAPIで破棄する。原本path、ファイル名、列名、JAN、商品名、center、日付、数量、行値、例外本文は返さない。

## 管理画面

`http://127.0.0.1:58000/ui/intake`の「ドライラン」欄で、判定・checksumによる絞込みと証跡選択ができる。概要は検証済み件数と除外件数を分けて表示し、詳細は識別子、上限、件数、検査状態、隔離理由、制約を表示する。除外された証跡の内容は表示しない。

## 配置

developmentでは既定の`./mapping_dry_run_output`、本番では必須の`KIBAN_MAPPING_DRY_RUN_DIR`をAPIの`/var/lib/kiban/mapping-dry-run`へread-only mountする。Phase 2Gの一回実行serviceだけが同じrootへ証跡を書き込む。

## モジュール境界

| module | 責務 |
|---|---|
| `mapping_dry_run/evidence_schema.py` | JSON構造、ID、上限、check、観測値の固定schema検証 |
| `mapping_dry_run/evidence.py` | 判定整合性の検証と公開可能な固定項目への縮約 |
| `mapping_dry_run/catalog.py` | read-only列挙、size・checksum検証、並び替え、除外件数 |
| `api/mapping_dry_run_routes.py` | READ認可付き一覧・詳細endpoint |
| `ui/static/intake_api.js` | 証跡API取得 |
| `ui/static/intake_render.js` | 原値を扱わない一覧・詳細描画 |

実業務原本へPhase 2Gを実行して結果を確認した後も、Phase 1G〜1Hで原本保存、版採用、全行正規化、隔離、全件数量照合を実施する。
