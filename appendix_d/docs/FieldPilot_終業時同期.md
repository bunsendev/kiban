# 現場PCの「本日の作業を完了」

現場担当者は出荷予測画面の「本日の作業を完了」を押します。ブラウザからWindowsの操作を許可する確認が出た場合は内容を確認してください。画面から起動できないPCでは、デスクトップの同名ショートカットを使用します。毎日送信項目を選ぶ必要はありません。

終業操作はデータ投入状況の確認、完全Backup、合意済みPolicyに従った改善情報の最小化・暗号化・Outbox保存、HTTPS送信、署名済み更新Manifestの確認、サービス停止の順です。回線障害では暗号化済みPackageをPCに保持し、次回起動後にバックグラウンドで再送します。担当者は手動再送を行いません。認証・共有Policyの拒否は管理担当者が確認します。

管理者は`/ui/pilot/feedback`でアプリ版、送信先、Client ID、Policy版、最終送信、未送信、拒否件数、更新確認日時を見ます。Tokenは表示しません。「Feedback Server 接続テスト」は業務値を入れない暗号化Packageだけを送り、結果を認証・Client ID・回線・Policy・Serverに分類します。画面から起動できないPCでは、デスクトップの「ブンセン Feedback Server 接続テスト」を使います。

導入時、管理担当者が「ブンセン 改善データ接続設定」で公開鍵PEMとTokenを設定します。Endpoint候補は`https://bun.stock-tools.tech/upload.php`、Client ID候補は`BUNSEN-PILOT-01`です。これらは添付指示書が示す値であり、Tokenは本PCに未設定です。共有Policyはクライアント合意後に管理画面で明示設定してください。更新確認を使う場合は署名ManifestのHTTPS URLとEd25519公開鍵を同時に設定します。更新Packageの適用は行いません。

共有サーバーの応答には`ok=true`、`status=RECEIVED`または`DUPLICATE`、送信時と同じ`request_id`が必要です。`sha256`が返る場合はBodyのハッシュと照合します。応答にIDがない場合は送信済みにせず再送待ちとします。Privacy Headerの具体形式と、共有サーバーがID/SHAを返すことはToken設定後に実確認してください。実確認前にオンライン運用を開始しないでください。
