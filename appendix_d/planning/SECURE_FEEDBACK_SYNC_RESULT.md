# 安全な改善データ同期 実装・検証結果

日付: 2026-09-28 JST。対象: `codex/secure-feedback-sync`。この文書は添付指示書の要求を、実装事実と未確認事項に分けて記録する。

Windows全体回帰: 753 passed、19 skipped、Linux専用RSS計測1件deselected。対象試験12 passed。`ruff check .`、PowerShell構文・Windows PowerShell 5.1のmodule import、JavaScript構文、Docker Compose構成、配布ファイルSHA-256照合を確認。

| 項目 | 判定 | 根拠・制限 |
| --- | --- | --- |
| Privacy levelと項目別Policy | PASS | 初期OFF、管理者限定UI、版管理・理由記録、中央側同版許可。レベル2は合意前に有効化しない。 |
| 通常送信のデータ最小化 | PASS | 許可されたイベント列だけ取得。原本・JAN原値・商品名等を契約から排除。疑似IDはClient IDを含むHMAC。担当者修正・業務KPI・賞味期限は現在の収集元にないため送信しない。 |
| 暗号化Outboxと再送 | PASS | AES-256-GCM、RSA-OAEP公開鍵封入、SHA-256、状態管理、重複ACK、失敗後の再送を人工データで試験。送信先はHTTPSのみ。 |
| 中央受信境界 | PASS | Token照合、TLS、復号後のPolicy版・項目検査、原値・不正IDの拒否、Package IDの重複排除を人工データで試験。 |
| 原本の例外的サポート送信 | 条件付きPASS | ローカル期限付き一度限り許可、中央一度限り許可、別Package・暗号化保管を人工データで試験。現場と中央の実運用承認は未確認。 |
| Retention | PASS | 中央の種別別日次削除、Outbox送信済・拒否済の削除を実装。未送信は保持。 |
| 更新確認 | 条件付きPASS | 署名済みHTTPS Manifestの候補確認を実装。自動適用・ロールバックは未実装。 |
| 実サーバ・実データ送信 | 未実施 | 本番URL、中央公開鍵、Token、TLS/Proxy、共有範囲の合意が未提供。人工データのみで検証。 |

## 導入判定

**NO-GO（オンライン本番送信）**。中央サーバのTLS終端、鍵・Token管理、合意済みPolicy、現場PCからの接続、運用管理者による受信・保持・削除確認が必要。ローカル側は送信OFFのまま既存運用を続けられる。自動更新の導入判断も別途必要。

手順は`docs/FieldPilot_安全な改善データ同期.md`。実データ・秘密鍵・TokenをRepositoryへ追加していない。
