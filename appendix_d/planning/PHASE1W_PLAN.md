# Phase 1W 実装計画

## ゴール

実データ担当者が、INITIAL 3〜5品目の選定版から受入caseを作成し、独立Workerによる10項目の技術判定と品質レポート、版付き業務判断を専用画面で確認・記録できるようにする。

## 実装範囲

1. 比較・採用画面と同じ認証方式を使う専用実データ受入画面を追加する。
2. INITIAL選定版の商品と成功済み日次build、データ区分、availability mode、品質閾値を指定して受入caseを登録する。
3. 受入caseの処理状態と技術outcomeを分けて一覧・表示する。
4. 10項目の技術チェックについて、判定、実測値、期待値、詳細を表示する。
5. JSON/Markdown品質レポートのURIとSHA-256を表示する。
6. 技術判定完了後に、APPROVE利用者が理由・版付きの業務判断を追記する。
7. API、描画、画面制御、追加styleを別ファイルに分け、静的配信、JavaScript構文、DOM参照、権限制御、配布成果物を検証して日本語PRを作成する。

## 完了条件

- READ利用者はcase、10チェック、レポート識別子、業務判断履歴を参照できる。
- ANALYZE利用者は3〜5品目の受入caseを登録できる。
- APPROVE利用者だけが業務判断を記録できる。
- APPROVEDは技術判定PASSEDのREAL caseだけに制限し、匿名caseはDRY_RUNとして扱う。
- Worker処理はHTTPから分離し、画面は操作後にサーバー台帳を再読込する。
- 実データや品質レポート本体をGit・配布ZIPへ含めない。
- pytest、ruff、JavaScript検査、Docker API、配布checksumがすべて成功する。
