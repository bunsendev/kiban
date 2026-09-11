# Phase 1T 実装計画

## ゴール

実データの将来trialを開始する担当者が、管理画面からLifecycle計画、月次cycle、昇格、rollback、予測事前記録、30日評価を操作し、追記型の証跡を確認できるようにする。

## 実装範囲

1. 比較・採用画面と同じ認証方式を使う専用Lifecycle画面を追加する。
2. 計画一覧と現在champion、revision、trial期間、cycle、予測記録、評価履歴を表示する。
3. 計画作成、scheduler実行、cycle完了・失敗、昇格、rollback、trial予測記録、trial評価を権限別に操作できるようにする。
4. rollback候補を表示できるよう、状態APIへ追記済みchampion eventを追加する。
5. API、描画、画面制御、追加styleを別ファイルに分ける。tokenはメモリ外へ保存しない。
6. 静的配信、JavaScript構文、DOM参照、権限制御、既存画面との導線を自動試験する。
7. 仕様・運用資料・検証記録・配布成果物を更新し、日本語PRを作成する。

## 完了条件

- READ利用者は全証跡を参照できる。
- ANALYZE利用者はscheduler、cycle処理、trial予測記録を実行できる。
- APPROVE利用者だけが計画作成、昇格、rollback、trial評価を実行できる。
- 操作後はサーバーから状態を再読込し、画面内だけで状態を推測しない。
- pytest、ruff、JavaScript検査、Docker API、配布checksumがすべて成功する。
