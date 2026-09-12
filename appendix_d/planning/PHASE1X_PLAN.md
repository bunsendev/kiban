# Phase 1X 実装計画

## ゴール

原本の取込job、ファイル判定、訂正版の採用、列mapping、正規化job、隔離行、数量照合を一つの専用画面で追跡・操作できるようにする。大量の正規化行はページ単位で取得し、HTTPとWorker、API、描画、画面状態の責務を分離する。

## 実装範囲

1. READ利用者向けに原本取込job、列mapping、原本採用履歴、正規化jobの一覧APIを追加する。
2. 正規化jobの数量照合summaryと、状態条件付き100件単位の行APIを追加する。
3. `/ui/intake`に取込job登録、列mapping登録、訂正版採用、正規化job登録をまとめる。
4. 原本のchecksum・encoding・重複/訂正系譜・隔離理由と、正規化行・数量照合を表示する。
5. HTML、API client、mapping入力変換、描画、画面制御、固有styleを別moduleに分割する。
6. SQLite/PostgreSQL、API認可、JavaScript、Docker配信、wheel、配布checksumを検証し、日本語PRを作成する。

## 完了条件

- READ利用者は取込・正規化台帳、原本系譜、採用履歴、数量照合、正規化行を参照できる。
- ANALYZE利用者は管理対象入力root内の取込job、列mapping、正規化jobを登録できる。
- APPROVE利用者だけが訂正版候補を版・理由付きで採用できる。
- 取込と正規化の実処理は独立Workerに残し、HTTPはjob登録と台帳参照だけを行う。
- 原本path、採用可能状態、mapping、権限をサーバーが最終検証する。
- 正規化行は最大100件ずつ表示し、全行を画面用APIへ一括返却しない。
- 実データ、原本、資格情報をGitと配布ZIPへ含めない。
- pytest、ruff、JavaScript検査、実画面、Docker API、配布checksumがすべて成功する。
