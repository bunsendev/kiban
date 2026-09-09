# Phase 1G 実装計画

## ゴール

原本CSV処理の前段として、安全な取込要求、ファイル検査、内容アドレス方式の不変保存、重複・訂正版候補・隔離を監査可能な台帳へ記録する。

## 範囲

1. サーバー管理領域の単一ファイル・フォルダ・ZIPを対象にした取込job API。
2. HTTP外で処理する独立取込Worker。
3. ZIP展開先逸脱、同名衝突、ファイル数・単体容量・総容量の制限。
4. UTF-8 BOM、UTF-8、CP932の厳密判定と不正ファイル単位の隔離。
5. SHA-256原本保管、同一内容の重複判定、同一論理名の訂正版候補化。
6. SQLite/PostgreSQL schema、別プロセスE2E、Compose、文書・配布検証。

## モジュール境界

`ingestion/contracts.py`は永続契約、`store.py`は台帳、`processor.py`は安全な列挙・検査・保存、`ingestion_worker.py`はprocess loopだけを担当する。CSV業務列の正規化、JAN名寄せ、日次確定は原本台帳を入力にする後続moduleへ分ける。

## 完了条件

APIから作ったjobを別Workerプロセスが処理し、正常・隔離・重複・訂正版候補と原本hashを取得できる。全pytest、ruff、demo、scale、artifact復元、wheel、checksumを確認し、日本語のDraft PRを作る。
