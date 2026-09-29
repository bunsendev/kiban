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

2026-09-29の現場報告では、EXEをクリックすると一瞬だけ開いて終了した。最初の診断版では`launcher-last.txt`の起動時刻しか残らず、原因を判定できなかった。更新した診断版は`%LOCALAPPDATA%\Bunsen\FieldPilot\InstallerLogs`へ次のログを残す。

- `launcher-last.txt`: 起動、PowerShell開始・終了、終了コード。PowerShell呼出しに到達したかを判定する。
- `powershell-stderr-last.txt`: PowerShell自体の起動・構文エラー等の標準エラー。
- `setup-progress-last.txt`: ZIP照合、展開、公開鍵配置、Field Pilotセットアップ、完了または失敗の時刻。
- `setup-last-error.txt`: 失敗段階、例外種別、エラーとスクリプト位置。成功時は削除する。
- `setup-transcript-last.txt`: インストール中に画面へ出た詳細。現場担当者の名前やPCパスが入り得るため、共有前に内容を確認し、公開IssueやPRへ添付しない。
- `field-pilot-setup-output-last.txt`: 既存Field Pilotセットアップの出力と終了コード。ZIP展開後に止まる場合はこれを最初に確認する。
- `setup-complete-last.txt`: 内部セットアップと後処理の完了記録。これがない場合はランチャーが終了コード0でも成功扱いにしない。
- `powershell-probe-last.txt`と`powershell-probe-marker-last.txt`: PowerShell起動前検査の出力と実行確認。起動自体が失敗した場合はセットアップを開始しない。
- `powershell-file-probe-last.txt`と`powershell-file-probe-marker-last.txt`: 短い無害な`.ps1`を`-File`で実行した結果。これが成功して本体だけ失敗する場合は、展開した`install.ps1`に対象を絞る。
- `powershell-sibling-probe-last.txt`と`powershell-sibling-probe-marker-last.txt`: 本体と同じ自己展開先に作った短いPS1の実行結果。
- `install-script-entry-last.txt`と`install-script-last.txt`: 本体PS1の一行目到達記録と、展開された本体の診断用コピー。後者は実行せず内容比較に使う。

失敗時は画面を閉じずに止める。新しい診断版を実行した後、まず`launcher-last.txt`の末尾と`setup-progress-last.txt`、`setup-last-error.txt`を確認する。PowerShell開始の記録の後に終了記録がなければ、処理が継続中か強制終了した可能性がある。

現場PCのログでZIP照合・展開・公開鍵配置まで成功し、`Field Pilot setup`の後で記録が止まった。従来は一時停止を含む`.cmd`を呼び、そこで起動する子PowerShellの出力が親Transcriptに残らなかった。診断版ではセットアップPS1を子PowerShellとして直接呼び、出力を画面と専用ログの両方へ流し、終了コードを記録する。現場での真の失敗原因は次回取得する子ログで判定する。

次の現場ログでは、ランチャーが約0.01秒で終了コード0を返した一方、同時刻のセットアップログは提出されていない。これを導入成功とは扱わない。ランチャーは毎回古い完了記録を消し、`install.ps1`の存在を確認し、子処理が`setup-complete-last.txt`を書いた場合だけ成功と判定する。開始元のPowerShellモジュール検索パスを継承せずWindows PowerShellの標準検索パスを使う。現場での原因判定には同時刻の`setup-progress-last.txt`、`field-pilot-setup-output-last.txt`、`powershell-stderr-last.txt`が必要。

完了記録確認付きEXEの現場ログでもPowerShell起動が約0.01秒で終了し、完了記録は作られなかった。`install.ps1`へ到達した証拠がないため、起動前にWindows PowerShellの短いprobeを実行して独立ログ`powershell-probe-last.txt`とmarkerを残す。probe自体が失敗した場合はセットアップへ進まない。`field-pilot-powershell-check.cmd`はIExpress外で同じprobeを実行する診断用ファイルであり、両者の差からIExpress内部の実行環境と現場PCのPowerShell制約を分けて調べる。probeは資格情報を読まない。現場側の真因はprobeログで判定する。

次の現場ログでは`-Command` probeのmarkerができた一方、`install.ps1`だけは実行記録がなく、約0.2秒で0を返した。さらに`-File`自体の可否を調べるため、ランチャー内で無害な一行PS1を`-File`で起動し、展開した`install.ps1`のバイト長を記録する。`field-pilot-file-execution-check.cmd`は同じ`-File`検査をIExpress外から実行する。両結果が異なる場合はIExpress展開環境を優先調査する。いずれも実インストールや資格情報読取をしない。

現場ではIExpress内の一行`-File`も成功し、`install.ps1`だけが開始記録なしで終了した。次の診断版では同じIExpress展開フォルダに一行のprobe PS1を作って実行し、場所による制限を検査する。`install.ps1`の先頭は最初の命令で`install-script-entry-last.txt`を作る。展開済みの本体PS1は診断用`install-script-last.txt`へコピーするが、実データ・資格情報は含まない。これで同一フォルダ内の別スクリプトとの差と、本体スクリプトが一行目へ到達したかを区別する。

両ログがない場合はIExpress起動前にブロックされた可能性がある。EXEは現時点でAuthenticode未署名なので、Windows Securityの保護の履歴や会社の端末保護製品を管理者と確認する。保護機能を無効化して回避しない。Docker/WSLの失敗はPowerShell内の診断ログに出る。ビルド時にPowerShell構文検査、自己展開、内包ZIPのSHA-256、公開鍵の一致を検査する。現場での正常導入はまだ未確認。

## 次の受入Gate

1. ソース非同梱の動作可能な配布物とビルド手順を確定し、公開前検査を通す。
2. 公開Repositoryと署名鍵を準備し、公開鍵を正規インストーラーへ固定する。
3. 更新前FULL backupを必須にした適用、migration、smoke test、失敗時のApp/Data復帰を故障注入で試す。
4. 別のWindows PCで新規導入・更新・通信断・翌日起動を確認する。

配布EXEのファイル名とSHA-256はビルド時の出力で記録する。検証記録は `test_results.txt` に残す。
