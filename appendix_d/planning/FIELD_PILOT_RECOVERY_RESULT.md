# Field Pilot 復旧基盤（2026-09-28）

## 今回の到達点

Field Pilot の `Data/Backup` に、1日最初の起動時の自動バックアップ、手動バックアップ、復元前バックアップを保存する。対象は PostgreSQL の全DB、`pilot-settings.json`、`inbox-policy.json`、バックアップ保持policy、現場設定 SQLite、Inbox/改善イベント SQLite である。PostgreSQL のバックアップには JAN/Location mapping、Pilot Scope、学習契約、変更履歴を含む。SQLite はオンラインバックアップAPIで WAL 上の確定済み変更も含める。

ZIP は許可されたファイルだけを収め、形式・アプリ版・配布物の指紋・各ファイルのサイズと SHA-256 を manifest に記録する。`pilot.env`、API token、原本 CSV/PDF、Input/Archive、ログは含めない。実データや資格情報を Repository へ置かない。

復元では ZIP の内容と版を検査し、SQLite 整合性、Shadow/read-only 設定、PostgreSQL dump の一覧を確認した後に復元前バックアップを取る。API を止め、DB とファイルを復元し、`/ready` と Field Pilot の Shadow/read-only 応答を確認する。失敗時は復元前バックアップから戻す。保持世代数は `Data/Config/recovery-policy.json` で設定する。

## 現場PCでの操作

配布版を更新するとデスクトップに「ブンセン バックアップ作成」と「ブンセン バックアップから復元」が作られる。バックアップ作成後、表示された ZIP を安全な外部保存先にコピーする。PC交換では新PCに同じアプリ版を導入し、旧PCのZIPを渡して「バックアップから復元」で選択する。復元前の現状態は自動保存される。バックアップZIPには業務DBが含まれるため、社内規定に従って保管・受け渡しする。

`Data/Backup` だけを同一PC内に置いてもPC故障からは復旧できない。外部媒体への定期コピーや暗号化・アクセス制御の運用は管理担当者が決める。業務原本は既存の Archive 管理を継続し、必要なら別途移行する。

## 境界と次工程

ZIP形式には部分的なローカル設定エクスポートのモードも定義したが、PostgreSQL 上の JAN/Location mapping・Pilot Scope を安全に選択移行する仕組みは未実装。PC交換には **FULL バックアップ**を使用する。別のアプリ版への復元も DB migration との順序が未確定のため禁止し、同一アプリ版のみ許可する。

1日初回起動、手動、復元前は実装した。設定変更前、Updater前、Migration前の各トリガーと、設定だけの選択的Import、管理画面UI、外部保存先への自動コピーは次工程で接続する。

Docker実行経路を含む現場PCの実データ復元訓練は未実施。現在稼働中の Field Pilot のDBを破壊しないため、独立した検証PCまたは隔離されたCompose projectでバックアップ作成→データ変更→復元→照合を行ってから現場運用へ進む。現行の正式取込・予測自動更新の未接続はこの変更では解消しない。
