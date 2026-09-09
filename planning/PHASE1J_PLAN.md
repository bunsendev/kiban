# Phase 1J 実装計画

## ゴール

予定ファイル完全性、採用済み正規化行、JAN有効期間、商品×center取扱期間、確認済み休業日から日次状態を再現可能に確定し、選定系列を含む不変dataset snapshotを独立Workerで自動発行する。

## 範囲

1. center・ファイル種別・有効期間・対象日範囲・論理path・欠行を0と解釈できるかを固定する内容アドレス方式の予定ファイル定義。
2. 必要論理ファイルの採用、正規化成功、隔離行、center・対象日範囲を検査する日別完全性。
3. mapping versionのJAN有効期間とperiod versionの取扱期間を使う`canonical_product_id×center_id×ds`集計。
4. `OBSERVED`、`CONFIRMED_ZERO`、`MISSING`、`NOT_HANDLED`、`CLOSED`、`PARTIAL_OR_INVALID`の決定と根拠保存。
5. center別の確認済み休業日を、承認者・理由・版付きの不変履歴として保存。
6. 選定系列、TRAIN/TEST範囲、availability mode、上流版を凍結した日次build job。
7. 日次CSVの決定的生成、SHA-256検証、catalogへのdataset snapshot自動登録。
8. SQLite/PostgreSQL、認証付きAPI、独立Worker、Compose、仕様・配布検証。

## モジュール境界

`daily/contracts.py`は永続型、`daily/domain.py`は予定・job・休業日の内容アドレス化、`daily/completeness.py`はファイル完全性、`daily/aggregation.py`はJAN解決と日次数量、`daily/states.py`は状態決定、`daily/export.py`は決定的CSV、`daily/store.py`と`daily/postgres_store.py`は台帳、`daily/processor.py`は処理順、`daily_worker.py`はprocess loopを担当する。HTTP schemaとrouteも専用moduleへ分ける。

## 完了条件

- 予定0件を完全取込済みと判断しない。
- 取扱期間内でも完全性が確定しない欠行を0にしない。
- `CONFIRMED_ZERO`は、必要ファイルが全部正常で、全ファイルが欠行を0と解釈可能な場合だけ生成する。
- 取扱期間外と不完全データを学習・評価用の実績にしない。
- 休業日に実出荷があれば実績を消さず、矛盾を記録する。
- 同じ入力ID・版・選定・期間から同じbuild ID、CSV checksum、snapshot IDを生成する。
- 全pytest、ruff、PostgreSQL実DB、別プロセスE2E、demo、scale、artifact復元、wheel、checksumを確認し、日本語のDraft PRを作る。

## 対象外

予定規則からの将来ファイル名自動展開、未解決JANの自動補正、休業日の自動推定、重要品目の自動選定UI、実データ3〜5品目の業務受入、2つ目のOSS、月次再学習。
