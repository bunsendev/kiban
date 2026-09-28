# Field Pilot RC1 Release Notes

配布版: `0.1.0-field-pilot.1`。基準はPR #109が統合されたmain。アプリ内部のPython package版は `2.9.0` であり、RC番号はWindows配布物の識別子である。

- Windows向け単一自己展開Installerを追加。内包した配布ZIPのSHA-256を検査してから従来のセットアップを実行する。Installer自体のSHA-256はAcceptance結果に記載する。
- 現場担当者の主導線は「ブンセン データ投入」と「ブンセン 出荷予測」。終業時は画面の「本日の作業を完了」を使用する。
- 初回設定で管理者がFeedback Tokenを非表示入力しDPAPIへ保存する。Tokenと業務実データはInstallerに含めない。
- Unified Inbox、承認型形式学習、Shadow参照、バックアップ、改善データの暗号化Outboxと共有サーバー送信を収録する。

**現場配布判定はAcceptance結果を参照。** 単一フォルダから正式取込・予測更新への自動接続は未完了で、現場PCでのRC1フル受入も未実施である。Installerが生成されたことは業務利用のGOを意味しない。
