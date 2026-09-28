# End-of-Day Secure Sync 実装結果

対象Branch: `codex/secure-feedback-sync`（未マージのPR #109を更新）。日付: 2026-09-28 JST。

| 指示書の項目 | 判定 | 実装と確認範囲 |
| --- | --- | --- |
| 1. End-of-Day UI | 条件付きPASS | 現場画面に「本日の作業を完了」を追加。Windowsの登録済みURIから既存の終業スクリプトを呼ぶ。デスクトップショートカットも維持。ブラウザ→URI起動の実機試験は未実施。 |
| 2. Privacy Policy | PASS | 初期送信OFF。管理者がレベル・項目を版と理由付きで保存。担当者は毎日の項目選択をしない。 |
| 3. Pseudonymization | PASS | Client固有DPAPI秘密情報を用いたHMAC-SHA256。商品・倉庫の原値を通常送信しない。 |
| 4. Encryption | PASS | AES-256-GCMとRSA-OAEP公開鍵封入。改ざん検知を人工データで確認。 |
| 5. Outbox | PASS | 暗号化Bodyを先にSQLiteへ記録。送信先・Transport種別も固定。状態・件数を管理者画面へ表示。 |
| 6. Retry | PASS | 起動後に非同期のWindows処理で再送。5分から最大24時間の指数Backoff。403等は拒否として自動再送しない。 |
| 7. Idempotency | PASS | Packageごとに固定Request IDを保持。再送時も同じID・Body。模擬DUPLICATE応答を検証。 |
| 8. SharedServer Transport | 条件付きPASS | `upload.php`向けoctet-stream、指定Header、`ok/status/request_id/sha256`の厳格なACK照合を人工応答で検証。実EndpointへのPOSTはToken未設定のため未実施。応答のRequest ID/SHAとPrivacy Headerの実際の仕様は未確認。 |
| 9. Connection Test | 条件付きPASS | 管理者画面ボタンとWindows接続テストを追加。人工暗号化Packageだけ送る契約とエラー分類を試験。実Endpoint確認は未実施。 |
| 10. Online Update | 条件付きPASS | Feedbackの成否から独立してEd25519署名Manifestを確認。失敗時も業務を停止しない。自動適用・Migration・Rollbackは未実装。 |
| 11. Backup / Rollback | 条件付きPASS | 終業時は送信前に既存の完全Backupを実行。更新適用自体が未実装のため更新Rollbackは対象外。 |
| 12. Windows Test | 条件付きPASS | PowerShell構文・モジュールを確認。新規配布版の導入、ブラウザURI起動、実PCでの終業操作は未実施。 |
| 13. Security | 条件付きPASS | TLS 1.2以上、Bearer TokenはDPAPI、通常Packageに原本・氏名等を含めない。実サーバーのPrivacy Headerと応答契約は未検証。 |
| 14. Regression | PASS | 人工データの対象試験・全体回帰・ruff・配布照合を実施。結果は`test_results.txt`。 |
| 15. 残課題 | 未完了 | Tokenの安全な現場設定、共有サーバー応答契約の実確認、現場PCでのブラウザURI動作確認、署名済みUpdate配布元と適用手順の確定。業務KPIとForecast Errorは元データが未接続であり架空値を送らない。 |

**オンライン運用の判定はNO-GO。** 利用者から共有サーバーの疎通テスト完了の報告を受けている。一方、指示書に記された`ok=true/status=RECEIVED`をこの実装とこのPCのTokenで再現確認した結果ではない。このPCにTokenが保存されていないため、実サーバーへのPOSTや実データ送信は行っていない。導入時に管理担当者がTokenと公開鍵を入力し、DPAPI保存する案内を追加した。`X-Bunsen-Privacy`にはPolicy版を設定するが、PHP側が期待する具体形式は初回設定後に確認する。

## 指定形式での判定

```text
Branch: codex/secure-feedback-sync
Commit: PRの最終HEADを参照
PR: https://github.com/bunsendev/kiban/pull/109

End-of-Day Sync: FAIL（Windows実機の画面起動・実Endpoint確認が未完了）
Encrypted Package: PASS（人工データ）
Shared Server Upload: FAIL（Token未設定で実送信なし）
Outbox: PASS（人工データ）
Automatic Retry: PASS（人工データ・Windows非同期起動は実機未確認）
Connection Test: FAIL（実Endpointへの接続は未実施）
Online Update: CONDITIONAL（署名済み確認のみ。適用なし）
Windows Field Pilot: NO-GO

残課題: 実契約・現場PC動作・クライアントPolicy合意・Update適用設計。
```

原本CSV/PDF、実在庫、Token、秘密鍵はRepositoryと配布ZIPに含めない。
