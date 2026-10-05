# Feedback device provisioning 実装結果

2026-10-06 / Windows Portable 0.6.0-pilot.16
Branch: codex/feedback-device-provisioning

## 判定

ローカル実装・自動検証を進めた。現場配備の総合判定は **NO-GO（実受信確認待ち）**。
実サーバーの RECEIVED / ALREADY_RECEIVED、実Windows管理者起動、現場PCの再起動後送信は未確認。
この判定は予測業務そのものの利用可否ではなく、Feedback接続の受入判定。

## 実装

- 通常画面から接続資格情報の入力を分離。管理者CMDからWindows昇格し15分の設定セッションを発行。
- 設定・公開鍵検証・合成データ接続テストAPIは管理者セッション必須。セッションはハッシュのみ保存。
- 各PC固有Device ID / Token、共通受信RSA公開鍵、Key ID、SHA-256指紋を設定。
- Tokenは既存WindowsユーザーDPAPI保存を再利用し、画面・設定JSON・変更台帳には平文を含めない。
- AES-256-GCM + RSA-OAEPを維持。Key IDと指紋を外側と暗号化された内容に記録し復号時に整合確認。
- 設定変更・鍵切替・接続テスト・終業の履歴をSQLite change_ledgerに保存。
- 既存HTTP契約のRECEIVED / DUPLICATEに加えALREADY_RECEIVEDを成功として扱う。
- AUTH_FAILED / CLIENT_NOT_ALLOWED / KEY_INVALID / KEY_NOT_FOUND / PRIVACY_REJECTEDを分類。
- 恒久エラーは隔離。ネットワーク失敗は安定したrequest ID・暗号文のままoutboxで再試行。
- 「本日の作業を完了」から送信。未設定・通信失敗でも業務完了を阻害しない。
- 鍵切替に新Key IDと承認が必要。既存outboxを再暗号化しない。旧鍵受付は受信側で保持する。
- keyフォルダーをGit・ソース配布から除外。秘密鍵や端末Tokenを配布しない。

## 互換性と運用境界

以前のKey IDなし暗号文は変更しないため、遡ってKey IDを埋め込むことはできない。
旧形式の受信対応と旧RSA秘密鍵は受信側で維持すること。新パッケージの追加フィールドの受信互換性は実疎通で確認する。
管理者セッションはローカルUIの操作制御であり、同一WindowsアカウントでアプリやDataを書き換えられる攻撃者に対するOS隔離ではない。
受信秘密鍵はサーバー管理者のみが保管。更新署名鍵とFeedback受信鍵は異なる。
設定後の送信同意は起動・終業・手動送信に適用される。接続テストは業務原本を送らない。

## 検証

- DPAPI再読込、Token漏洩防止、公開鍵不正、指紋、鍵切替承認、旧暗号文保持、認証分類、重複受付、オフライン終業を自動テスト。
- 初回回帰: 133 PASS / 1 FAIL。FAILは起動中アプリとのテスト固定ポート競合。
- テストをOS割当ポートで競合を再現する方式へ修正。起動中アプリは停止しない。
- 最終件数・パッケージ検証は test_results.txt を参照。

## 現場受入手順

1. 同梱マニュアルのIT担当者手順に従い各PC固有の資格情報を設定。
2. サーバー管理者のKey ID・指紋と照合し合成データ接続テストを実施。
3. サーバーで受領IDと復号・Key IDを照合。RECEIVED / ALREADY_RECEIVEDを確認。
4. 業務完了後の送信を確認。オフライン時は業務完了とoutbox保持、再接続・再起動時は重複なし再送を確認。
5. Token交換・受信鍵交換と旧鍵outboxの受付を確認。

実受信が確認されるまで総合GOに変更しない。
