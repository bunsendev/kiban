# Phase 1K 少数実品目の受入

## 目的

実データ3〜5品目の日次buildを対象に、入力範囲、日次状態、dataset snapshot、artifact checksum、品質閾値を同じ条件で再検査し、技術判定と担当者の業務判断を分けて保存する。実データと品質レポートはGitや配布ZIPへ含めない。

この機能は受入手順と証跡を提供する。予測精度、在庫効果、実データの妥当性そのものを自動保証しない。

## 状態と判断

受入caseは`QUEUED`、`RUNNING`、`SUCCEEDED`、`FAILED`で処理状態を管理する。`SUCCEEDED`は技術判定処理が完了した意味であり、判定結果は別の`outcome`に保存する。

| outcome | 意味 |
|---|---|
| `PASSED` | `REAL`として登録したcaseが全技術条件を満たした |
| `FAILED` | 1件以上の技術条件を満たさない |
| `DRY_RUN` | 匿名データの手順確認。全技術条件を満たしても実データ受入ではない |

業務判断は`APPROVED`または`REJECTED`を、担当者、理由、decision version、判断時刻とともに不変保存する。`APPROVED`は`REAL`かつ`PASSED`のcaseだけに許可する。`REJECTED`はデータ差し戻しの証跡として保存できる。同じdecision versionは上書きせず、再判断は新しい版にする。

## 技術チェック

| check | 条件 |
|---|---|
| `BUILD_SUCCEEDED` | 参照した日次buildが存在し成功済み |
| `PRODUCT_SCOPE` | buildの品目集合が宣言した重複なし3〜5品目と完全一致 |
| `AVAILABILITY_MODE` | `ASSUMED`または`OBSERVED`が受入caseの宣言と一致 |
| `SNAPSHOT_LINKED` | snapshot provenance、build ID、checksumが接続している |
| `ARTIFACT_CHECKSUM` | 日次CSVの実byte列が保存済みSHA-256と一致 |
| `SERIES_CALENDAR` | 選定した各商品×centerにTRAIN開始からTEST終了まで全暦日行がある |
| `USABLE_DAYS` | `OBSERVED`と`CONFIRMED_ZERO`が系列別最小日数以上 |
| `MISSING_RATE` | 取扱対象日に対する`MISSING`率が系列別上限以下 |
| `PARTIAL_INVALID_RATE` | 取扱対象日に対する`PARTIAL_OR_INVALID`率が系列別上限以下 |
| `REAL_DATA_DECLARATION` | 実データcaseである。匿名caseでは`NOT_EVALUATED` |

欠測率と不完全率の分母には`OBSERVED`、`CONFIRMED_ZERO`、`MISSING`、`PARTIAL_OR_INVALID`を使い、`NOT_HANDLED`と`CLOSED`を含めない。欠測を0へ変換しない。

## APIとWorker

Bearer認証付きAPIは次を提供する。

- `POST /api/acceptance-cases`
- `GET /api/acceptance-cases/{case_id}`
- `GET /api/acceptance-cases/{case_id}/checks`
- `POST /api/acceptance-cases/{case_id}/decisions`
- `GET /api/acceptance-cases/{case_id}/decisions`

作成例は次のとおり。閾値は業務担当者と確認した値を版付きで登録する。

```json
{
  "acceptance_version": "initial-real-data-v1",
  "daily_build_id": "daily-...",
  "data_kind": "REAL",
  "expected_product_ids": ["product-a", "product-b", "product-c"],
  "required_availability_mode": "OBSERVED",
  "min_usable_days_per_series": 730,
  "max_missing_rate": 0.01,
  "max_partial_invalid_rate": 0.001,
  "requested_by": "operator@example.jp",
  "purpose": "安定品・間欠品・JAN変更品の初期受入"
}
```

技術判定はHTTP request内で行わず、独立Workerで実行する。

```powershell
kiban-acceptance-worker `
  --postgres-dsn postgresql://kiban:***@127.0.0.1:55432/kiban `
  --output-root C:\restricted\kiban-acceptance
```

Docker Composeでは次を使う。

```powershell
$env:KIBAN_SNAPSHOT_DIR = "C:\restricted\kiban-snapshots"
$env:KIBAN_ACCEPTANCE_DIR = "C:\restricted\kiban-acceptance"
docker compose --profile worker up -d --build acceptance-worker
```

Workerは日次CSV領域をread-onlyで参照し、品質レポート領域へJSONとMarkdownを内容アドレス方式で発行する。同じcaseと日次buildからは同じレポートchecksumになる。

## 実データ実行前の確認

1. 取込元を`KIBAN_IMPORT_DIR`、原本保管を`KIBAN_RAW_ARCHIVE_DIR`へ設定し、いずれもGit管理外のアクセス制限領域に置く。
2. 列mapping、訂正版採用、JAN mapping、取扱期間、予定ファイル、休業日を担当者と確認する。
3. 安定品、間欠品、JAN変更品を可能な範囲で含む3〜5品目の日次buildを発行する。
4. 閾値の根拠を`acceptance_version`と`purpose`へ結び付け、受入caseを作成する。
5. JSON/Markdownレポートと元数量照合を担当者が確認し、理由付きで判断を記録する。

## 現在の制約

リポジトリには実データが提供されていないため、Phase 1Kでは匿名3品目による手順確認とPostgreSQL適合試験までを実施した。後続の[Phase 1W専用画面](Phase1W_実データ受入画面.md)でcase登録、10項目の技術判定・レポート識別子確認、版付き業務判断を行える。実データcaseの作成、元帳との数量照合、業務承認は未実施である。`ASSUMED`を選ぶ場合、当時の実到着時刻を厳密に再現した結果ではない。
