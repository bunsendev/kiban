# Portable pilot.15 署名配布

2026-10-05。利用者の許可に基づき、忘失した旧パスフレーズの鍵を温存し、新しい署名鍵を別ディレクトリへ作成する。
新しい鍵はEd25519。秘密鍵はランダムパスフレーズで暗号化、パスフレーズはCurrentUser DPAPIで暗号化保存。
秘密鍵・DPAPIファイルはLOCALAPPDATA/Bunsen/ReleaseSigning/portable-20261005に保持し、リポジトリ・ZIP・GitHubに含めない。
公開鍵のみをPortableへ組み込む。既存のpilot.14以前は旧公開鍵のため、新しい版へ最初だけ手動展開が必要。

## 次回の署名

`python -m portable.sign_release <新ZIP> --private-key <上記ディレクトリ>/release-update-private.pem --credential-file <上記ディレクトリ>/passphrase.dpapi --minimum-version 0.6.0-pilot.15 --output <新しい署名出力先>`

同じWindowsユーザーで実行する。パスフレーズをチャット・ログ・引数に出さない。
別PCへPEMとDPAPIファイルだけコピーしても復号できない。Windowsユーザープロファイルを失った場合は再度鍵切替と手動配布が必要。

## ログ受信との区別

この鍵は更新の署名用。ログの暗号化に使う受信RSA公開鍵とは別である。
ログ受信サーバーの登録済みToken・端末ID・RSA公開鍵はこのPCに存在しない。
既定送信先upload.phpはHTTPS GETに405を返すことを確認したが、これはToken認証・受信成功の確認ではない。
送信先の設定・同意まではログ送信を停止状態に保つ。

## 公開結果

- 公開先: https://github.com/bunsendev/kiban-releases/releases/tag/portable-v0.6.0-pilot.15
- 新鍵による署名と公開先からの再ダウンロード検証: PASS。
- 公開ZIP: 56,424,337 bytes、SHA-256 `c7762d919895b3631e22c0adae57831184e7bf65836a202c5821d0cbdb3fd1a1`。
- 新版の配布元確認は CURRENT。公開物を取得・検証できることを実通信で確認。
- 関連25件のpytest、ruff、ZIP CRC/2505 hash、新公開鍵一致、資格情報不在、凍結EXEの人工データE2Eと再起動復元: PASS。
- ログ送信はToken・登録端末ID・受信RSA公開鍵の入力待ち。現時点で未送信。
- pilot.14は署名鍵変更前の非公開draftのまま。現場へはpilot.15を渡す。
- このPCの旧確認用serverを終了し新版へ切り替える操作は自動承認審査で拒否された。旧serverは維持し、初回手動切替を案内する。
