# Phase 1H 実装計画

## ゴール

Phase 1Gの不変原本を、明示的な版付き列mappingで監査可能な出荷行へ正規化する。訂正版の明示採用、行単位隔離、数量照合、品質集計を提供し、JAN名寄せ・日次確定の信頼できる入力を作る。

## 範囲

1. 内容アドレス方式の列mapping作成・取得API。
2. 原本IDとmapping IDだけを受け付ける正規化job APIと独立Worker。
3. 日付、数量、単位、center、行区分、available_atの検証。
4. 原JAN・原商品名・原本ID・行番号を維持した採用行と隔離行の保存。
5. 訂正版候補の担当者・理由・decision version付き採用履歴。
6. parse可能数量、採用数量、隔離数量、未説明差分の照合。
7. ファイル・文字コード・job・行状態、center×月、隔離理由の品質API。
8. SQLite/PostgreSQL schema、別プロセスE2E、Compose、文書・配布検証。

## モジュール境界

`normalization/contracts.py`は永続型、`domain.py`はmapping検証・識別、`processor.py`はCSV変換、`store.py`はSQLite台帳、`postgres_store.py`はPostgreSQL claim、`normalization_worker.py`はprocess loopを担当する。API routeも専用moduleに分ける。

## 完了条件

原JANの先頭0と原本追跡を維持し、不正日付・数量・単位・返品を理由付きで隔離する。訂正版候補は明示採用前に処理できず、採用後は旧版が自動選択されない。別WorkerプロセスE2E、全pytest、ruff、demo、scale、artifact復元、wheel、checksumを確認し、日本語のDraft PRを作る。

## 対象外

列名の自動推測、JANの自動補正・名寄せ、返品・取消の相殺、日次0補完、取扱期間、予定ファイル完全性、dataset snapshot自動発行、実データ検証。
