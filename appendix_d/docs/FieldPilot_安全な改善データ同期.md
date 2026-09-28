# 現場PCの改善データ同期（管理担当者向け）

Pilotで使用する共有PHP Endpointと終業操作は[FieldPilot_終業時同期.md](FieldPilot_終業時同期.md)を参照してください。以下の中央FastAPI受信サービスは将来の移行先として残し、現在のPilotの接続先にはしません。

現場PCは初期状態で送信OFFです。予測・在庫画面は送信設定や回線状態と独立して動きます。共有レベルはクライアントと合意してから管理画面 `/ui/pilot/feedback` で設定してください。レベル2は候補であり、自動選択しません。

## 送信できる内容

| レベル | 通常送信する内容 |
| --- | --- |
| 0 | なし |
| 1 | 許可されたイベント種別・固定エラーコードの件数 |
| 2 | レベル1と、許可された処理時間等の数値集計 |
| 3 | レベル2と、許可された疑似商品・倉庫ID、詳細指標 |

原本CSV/PDF、商品名、取引先名、JANの原値、認証情報は通常送信しません。JAN・倉庫IDはクライアント別の秘密鍵によるHMACで疑似化します。現在の収集元は`improvement-events.sqlite3`のみです。担当者修正、業務KPI、賞味期限のスイッチは将来の契約用で、現時点で実データを収集・送信しません。画面のプレビューは「送信候補」であり、中央側で同じPolicy版と許可項目を登録しない限り受け付けません。

## 中央受信環境の準備

1. 中央管理者が`python -m forecast_provider.feedback_sync.server_admin keygen --private <安全な場所>/feedback-private.pem --public <配布場所>/feedback-public.pem`で鍵を作ります。秘密鍵は配布ZIP・Git・現場PCに含めません。中央DBと秘密鍵の保管場所・アクセス権・バックアップを決めます。
2. TLS終端のリバースプロキシを中央サーバ前に置きます。`compose.feedback-server.yaml`はloopbackだけを公開します。`KIBAN_FEEDBACK_SERVER_DATA`、`KIBAN_FEEDBACK_SERVER_PRIVATE_KEY`、`KIBAN_FEEDBACK_TRUSTED_PROXY_IPS`を明示し、信頼するプロキシだけから`X-Forwarded-Proto`を受けます。公開HTTPS URLは`/v1/feedback`に到達させます。インターネットへの直接HTTP公開はしません。
3. 現場PCの管理画面で合意した共有Policyを保存し、その版IDとPolicy JSONを中央管理者へ渡します。中央で`python -m forecast_provider.feedback_sync.server_admin enroll --db <中央DB> --client-id <Client ID> --policy-version <版ID> --policy-file <Policy JSON>`を実行し、32文字以上のランダムTokenを**標準入力**から渡します。引数・ログ・GitにTokenを残しません。変更時は中央Policyも更新します。
4. 現場PCで「ブンセン 改善データ接続設定」を開き、Client ID、HTTPS URL、中央公開鍵、Tokenを設定します。Tokenと疑似化鍵はWindows DPAPIで現在のWindowsユーザーに結び付けて保存します。PC交換後は再設定してください。バックアップにDPAPI秘密情報は含みません。

現場担当者は「ブンセン 本日の作業を完了」を実行します。終了処理はローカルバックアップを先に作り、許可された情報を公開鍵で暗号化してOutboxに保存し、送信します。通信失敗時はOutboxを保持して次回起動時に再送します。中央は復号後にPolicy・項目・疑似ID形式を再検査し、同じPackage IDの重複を一度だけ記録します。送信拒否は管理担当者がPolicy版・接続設定を確認してください。

## 原本が必要なサポート依頼

通常の同期と別経路です。現場の管理画面でファイル名、目的、正確な送信先、期限を入力し、一度限りの許可IDを発行します。中央管理者は対象ファイルのSHA-256と許可ID、期限、最大バイト数を照合し、`server_admin grant-support`で中央側の一度限りの許可を登録します。その後、現場PCの「ブンセン 個別サポート送信」で対象CSV/PDFを選び、送信内容を確認します。最大5MBです。中央は暗号化Envelopeのまま7日間保持し、通常の改善集計には混ぜません。中央側で原本を開く手順・アクセス権は個別のサポート業務として管理してください。

## 保持と更新

中央の既定保持日数は診断30日、改善90日、サポート7日で、日次削除と`server_admin prune`を用意しています。現場Outboxは送信済30日、拒否済90日で削除します。未送信は削除しません。更新確認はHTTPS上のEd25519署名済みManifestを検証する機能のみです。`feedback-client.json`に`update_manifest_url`と`update_signing_key_file`を両方設定した場合に終業時に候補を確認します。自動ダウンロード・自動適用・ロールバックはこの変更に含みません。

本番の中央URL、鍵、Token、Proxy設定、クライアントの共有同意、現場PCでの実送信、個別サポート運用は別途確認が必要です。未確認のままオンライン送信を有効にしないでください。
