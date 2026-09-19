# Phase 3P レビュー対応タスク

Phase 3Oの精度変化レビューで決めた「次の対応」を、担当者・期限・状態・完了根拠付きで実行管理する。対応タスクと状態イベントは分離し、変更のたびにイベントを追記する。

## 操作

分析実行画面 `/ui/analysis` の「レビュー後の対応を管理する」で、対象レビュー、種類、件名、担当者、期限、対応内容を登録する。登録直後の状態は `OPEN` となる。状態・担当者・期限の変更は右側のフォームから履歴として追加する。

状態は `OPEN`、`IN_PROGRESS`、`BLOCKED`、`COMPLETED`、`CANCELLED` の5種類である。`COMPLETED` では結果URL、出力ファイル、確認内容などの完了根拠が必須となる。完了または中止したタスクは変更できない。期限を過ぎた未完了タスクは画面で期限超過として表示する。

## APIと認可

- `POST /api/model-drift-review-actions`: 対応タスク登録。`APPROVE` 権限。
- `POST /api/model-drift-review-actions/{action_id}/events`: 状態・担当・期限・根拠の追記。`APPROVE` 権限。
- `GET /api/model-drift-review-actions`: 現在状態の一覧。`READ` 権限。
- `GET /api/model-drift-review-action-events`: 追記履歴の一覧。`READ` 権限。

登録者と更新者は認証subjectから固定する。更新要求には画面で取得した `expected_revision` を含め、別の利用者が先に更新した場合は409を返す。

## 保存契約

`model_review_actions` は対象レビュー、種類、件名、作成者、作成日時を不変で保存する。`model_review_action_events` はrevision、状態、担当者、期限、記録内容、完了根拠、記録者、記録日時を追記する。SQLiteは即時transaction、PostgreSQLは行lockとrevision一意制約で競合を防ぐ。

この機能は対応の責任と履歴を管理する。再テスト、データ修正、Lifecycle操作、採用、昇格、rollbackそのものは自動実行しない。
