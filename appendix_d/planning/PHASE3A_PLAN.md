# Phase 3A 計画

1. POST APIへ共通適用できるIdempotency route classを追加する。
2. 本番PostgreSQL、テスト用SQLite、単一process用メモリ台帳を同じ契約で分離する。
3. HTTP・入力検証・内部例外、HTTPS・Host拒否を共通エラー形式へ変換する。
4. UI clientを`message`へ移行し、入力値・token・要求本文を証跡へ保存しない。
5. 永続replay、競合、失敗後再送、エラー形式を自動試験する。
6. 全回帰、ruff、JavaScript、Compose、wheel、配布ZIPを検証する。

