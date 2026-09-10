# Phase 1O 比較レポートCSVと採用判断

Phase 1Oは、Phase 1Nで永続化した比較結果を配布可能なCSVへ変換し、正式比較と実データ受入に基づく採用判断を不変な監査記録として保存する。クライアントは予測値、指標、出力先を指定できない。

## モジュール境界

| モジュール | 責務 |
|---|---|
| `reporting/contracts.py` | export・採用記録とStore Protocol |
| `reporting/domain.py` | 入力検証、正規化、内容アドレスID |
| `reporting/export.py` | 決定的CSV、改善率、表計算の数式注入対策 |
| `reporting/service.py` | 比較、snapshot、受入case、業務判断の照合 |
| `reporting/store.py` | SQLiteの不変保存と検索 |
| `reporting/postgres_store.py` | PostgreSQL接続差分 |
| `api/reporting_schemas.py` | 外部入力の型と追加項目の拒否 |
| `api/reporting_routes.py` | Bearer認証付きHTTP操作 |

評価式とProviderはreportingへ依存しない。CSVは保存済み比較のrun評価だけから作り、採用可否の照合はserviceへ集約する。

## 比較CSV

`POST /api/comparisons/{comparison_id}/exports`は`export_version`、比較内の`baseline_run_id`、`requested_by`だけを受け付ける。サーバーはcatalogのtruth snapshotをchecksumで再検証し、比較台帳の全runをrun ID順に出力する。同じ定義は同じ`export_id`とbyte列になり、同じ比較で同じexport版の内容は変更できない。

CSVはUTF-8 BOM、LF、固定列順である。比較・集合・snapshot・selection・availability・scope・policyの識別子、runとProvider、適合記録、正式集合への掲載状態、run/own/common/officialの件数、own/common/official指標を含む。WAPEとBias rateは百分率、MAE・RMSE・Bias・under・overは数量であることを`metric_units`へ明記する。

baseline改善率は全run共通集合のWAPEで計算する。

```text
(baseline WAPE - 対象run WAPE) / baseline WAPE * 100
```

絶対差も百分率ポイントとして併記する。baseline WAPEが0または比較不能の場合、改善率は空欄にして0除算しない。文字列が`=`, `+`, `-`, `@`、タブ、復帰で始まる場合は先頭へ`'`を付け、表計算ソフトで式として実行されないようにする。

発行ファイルは`KIBAN_REPORT_ROOT/comparisons/{sha256}.csv`へ内容アドレス方式で保存する。`GET /api/exports/{export_id}`は保存済みSHA-256を再検証してから返し、改変やroot外参照を409で拒否する。metadataは`GET /api/exports/{export_id}/metadata`、履歴は`GET /api/exports?comparison_id={id}`で取得する。実ファイルをGitと配布ZIPへ含めない。

## 採用判断

`POST /api/adoptions`は採用版、比較ID、判断、対象、判断者、理由を保存する。`target`は`selection_version`、重複のない品目IDとcenter ID、30〜366日の試験期間である。`REJECTED`も参照可能な判断履歴として保存し、受入caseやrunは指定しない。

`ADOPTED`には異なる採用runとfallback run、受入caseが必須であり、次の条件をすべて満たす必要がある。

1. 比較の`official_ranking_ready`がtrueである。
2. 採用runとfallback runがともに`official_runs`へ含まれる。
3. 受入caseが`REAL`、`SUCCEEDED`、`PASSED`である。
4. 受入caseの最新業務判断が`APPROVED`である。
5. 比較snapshotのprovenanceにある日次build IDと受入caseの日次build IDが一致する。
6. selection版がsnapshotと一致し、対象品目・centerがchecksum検証済みsnapshotに存在する。
7. 採用品目が受入caseの対象3〜5品目に含まれる。

採用条件全体から内容アドレスIDを作り、同じ内容の再送は同じ記録を返す。同じ`adoption_version`の内容変更は409で拒否する。詳細は`GET /api/adoptions/{adoption_id}`、履歴は`GET /api/adoptions?comparison_id={id}`で取得する。

## 入力例

```json
{
  "adoption_version": "adoption-2026-09-v1",
  "comparison_id": "comparison-...",
  "acceptance_case_id": "acceptance-...",
  "decision": "ADOPTED",
  "selected_run_id": "RUN_AUTOETS",
  "fallback_run_id": "RUN_BASELINE",
  "target": {
    "selection_version": "selection-v1",
    "canonical_product_ids": ["P1", "P2", "P3"],
    "center_ids": ["C1"],
    "trial_period_days": 30
  },
  "decided_by": "owner@example.test",
  "reason": "正式比較と実データ受入を確認"
}
```

## 検証範囲

人工データで決定的CSV、BOM、列順、改善率、数式注入対策、同内容再送、出力改変、入力URI拒否、匿名・未承認受入、非official run、版の上書き拒否、SQLite/PostgreSQL保存を検証する。人工データの採用fixtureは契約試験用であり、実データ受入済みや本番採用済みを意味しない。管理画面、role別認可、電子署名、本番通知は対象外である。
