# Phase 1O 実装計画

## ゴール

Phase 1Nで保存した比較結果を、監査可能な比較CSVと採用判断へ接続する。CSVはサーバー管理領域へ内容アドレス方式で保存し、採用は正式比較、実データ受入、業務承認、fallbackを照合した不変な版として保存する。

## モジュール境界

`reporting/contracts.py`はexport・採用記録とStore Protocol、`domain.py`は入力検証と内容アドレスID、`export.py`はCSV表現と安全な文字列処理、`service.py`は比較・snapshot・受入判断の結合、`store.py`と`postgres_store.py`はDB差分、`api/reporting_schemas.py`と`reporting_routes.py`はHTTP契約を担当する。評価式、Provider、run台帳へ出力・採用ロジックを混在させない。

## 実装範囲

1. 比較、baseline run、export版、依頼者を固定し、run別件数・own/common/official指標をUTF-8 BOM付きCSVへ出力する。
2. 同一common集合のWAPEでbaseline改善率と絶対差を算出し、baseline WAPE=0は改善率NULLとする。
3. CSVの文字列を表計算の数式として実行されないようエスケープし、指標単位、snapshot・selection・policy・集合IDを含める。
4. export ID、ファイルSHA-256、URI、行数をSQLite/PostgreSQLへ不変保存し、認証付きAPIからchecksum再検証後に取得する。
5. 採用版にcomparison、受入case、選択run、fallback run、対象品目・center、試験期間、判断者・理由を保存する。
6. 採用はofficial rankingが成立し、選択・fallbackがofficial runで異なり、対応snapshotの実データ受入がPASSEDかつAPPROVEDの場合だけ許可する。
7. REJECTED判断も履歴として保存し、同じadoption_versionの内容変更を拒否する。
8. SQLite/PostgreSQL、API、CSV安全性、同内容再送、改変ファイル、匿名・未承認受入、非official runを検証する。

## 完了条件

- クライアントが指標や出力URIを指定できず、保存済み比較からだけCSVを生成する。
- 同じexport条件は同じID・同じbytesとなり、取得時にchecksum不一致を検出する。
- 採用済みrunとfallbackを比較・適合・受入証跡まで追跡できる。
- 匿名データまたは未承認caseを採用済みにできない。
- PostgreSQL実DBを含むpytest、ruff、Docker、wheel、配布checksumが合格する。

## 対象外

React管理画面、role別認可、電子署名、月次再学習、実測資源・費用、実データでの採用実行、本番通知・監視。
