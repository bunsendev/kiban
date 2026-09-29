# Field Pilot RC4 配布と自動更新の状態

更新日: 2026-09-29。対象配布版: `0.1.0-field-pilot.4`。

## 現場PC向けインストールファイル

`build_field_pilot_installer.py` は `bunsen_field_pilot_release.zip` のSHA-256を埋め込んだ自己展開EXEを作る。実行時にZIPを再照合してから、既存のField Pilotセットアップを呼ぶ。`--public-key-file` にEd25519公開鍵を指定した場合、その鍵をEXEに同梱し、初回導入時に現場Configへ配置する。既存の鍵と異なる場合は導入を停止し、黙って置換しない。秘密鍵、現場データ、Tokenはビルドに含めない。

配布先での必要条件はWindows 10以降の64-bit、WSL 2、Docker Desktopである。Docker Desktopの導入には社内の利用条件確認と、環境によって管理者操作・再起動が必要。初回導入とDocker内の起動を現場PCで受入確認するまで、現場配布の最終承認はしない。

## 自動更新

起動後に業務画面と独立したバックグラウンド処理で更新を確認し、終業時にも確認する。通信障害と公開鍵未設定は記録して業務を継続する。確認結果は既存の管理画面とSQLite台帳で見られる。公開鍵を後から設定した場合は、前回の「未設定」結果を6時間待たずに再確認する。

署名Manifestの検証、版比較、公開Releaseの参照、ダウンロードの再開とハッシュ照合まで実装済み。**自動適用、DB migration、更新版のsmoke test、自動rollback、翌日起動試験は未完了。** `AVAILABLE` は更新候補の検知を示し、適用済みを意味しない。現場PCでの無人適用は有効にしない。

公開Release用のソース非同梱パッケージは未生成。現行のField Pilot EXEはソースを含むZIPを内包するため、公開Releaseへアップロードしない。公開用Repositoryは作成済み。ローカルで生成した公開鍵を指定したEXEでは更新確認の信頼鍵を初回導入時に配置するが、Releaseと自動適用は未完了。鍵を指定せずに作ったEXEでは更新確認は `UNCONFIGURED` となる。

## 現場PCでEXEがすぐ閉じる場合

2026-09-29の現場報告では、EXEをクリックすると一瞬だけ開いて終了した。原因は現場PCのログなしに断定できない。従来の`cmd /c`起動はセットアップエラーを表示し続けなかったため、診断版では失敗時にコンソールを停止し、処理段階とエラーを表示する。`%LOCALAPPDATA%\Bunsen\FieldPilot\InstallerLogs\launcher-last.txt`はbootstrap開始、`setup-last-error.txt`はPowerShell内の失敗を示す。新しい診断版を実行した後、両ファイルの有無と画面のエラーを確認する。

両ログがない場合はIExpress起動前にブロックされた可能性がある。EXEは現時点でAuthenticode未署名なので、Windows Securityの保護の履歴や会社の端末保護製品を管理者と確認する。保護機能を無効化して回避しない。Docker/WSLの失敗はPowerShell内の診断ログに出る。ビルド時にPowerShell構文検査、自己展開、内包ZIPのSHA-256、公開鍵の一致を検査する。現場での正常導入はまだ未確認。

## 次の受入Gate

1. ソース非同梱の動作可能な配布物とビルド手順を確定し、公開前検査を通す。
2. 公開Repositoryと署名鍵を準備し、公開鍵を正規インストーラーへ固定する。
3. 更新前FULL backupを必須にした適用、migration、smoke test、失敗時のApp/Data復帰を故障注入で試す。
4. 別のWindows PCで新規導入・更新・通信断・翌日起動を確認する。

配布EXEのファイル名とSHA-256はビルド時の出力で記録する。検証記録は `test_results.txt` に残す。
