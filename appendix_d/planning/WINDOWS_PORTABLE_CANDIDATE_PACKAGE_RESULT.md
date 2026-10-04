# Windows Portable 候補版パッケージ 実装結果

## 完成した範囲

- 承認済みの予測モデル変更案から候補版パッケージを発行するAPIと画面を追加した。
- 組込Baseline 4方式を固定した設定契約で発行できる。
- 人工データで実際のProviderを起動し、発行前smoke testを行う。
- Provider版、設定hash、資源上限、rollback先、smoke結果をv2 manifestへ固定した。
- 内容アドレス方式の発行証跡を追記し、同名・異内容と改変を拒否する。
- Pilot開始Gateへ発行済みmanifest SHA-256を自動設定する。
- 候補版を既存Baseline Workerへ接続し、正式予測Runを完走できる。
- SnapshotとRunを作る前に候補版の資源上限を検査する。

## モジュール境界

- `portable/api/runtime_profiles.py`: 対応済み設定と資源profile
- `portable/api/candidate_packages.py`: 発行、smoke、証跡、改変検知
- `portable/api/candidate_package_routes.py`: HTTP境界
- `portable/api/static/candidate-packages.js`: 担当者画面
- `portable/api/runtime_assignments.py`: v1/v2 manifest検証とruntime選択
- `portable/api/production_handoff.py`: 実行前の資源境界

発行、HTTP、画面、実行時解決、Production受渡しを分け、モデル追加時に既存画面へ処理を継ぎ足さない構成にした。

## 互換性

- 既定Baseline設定は変更しない。
- 従来のv1候補manifestは読み取り互換を維持する。
- v2だけに発行証跡と厳密なpackage契約を要求する。
- DB migrationは不要で、候補版の追加情報は既存JSONと追記型ファイルへ保存する。
- SHADOWとPilot Scope制限を維持し、正式設定を自動昇格しない。
- 実データ、API key、署名秘密鍵をGitや配布ZIPへ含めない。

## 検証

- 4つの組込Baseline方式すべてで発行smokeとscope内runtime選択を確認する。
- `moving_average_28`候補版でPilot開始Gate、Production受渡し、既存Workerによる140点の予測完了を確認する。
- 冪等再発行、未知設定、資源超過、同名異内容、証跡改変、scope不一致を確認する。
- API、画面asset、従来v1 manifest、既存Baselineへの回帰を確認する。

## 次工程

Pilot中のruntime別予測結果と後日実績を、既存の週次評価・Feedback Ledgerへ接続する。新しいOSS Providerは、専用Workerと依存ライブラリを配布できる場合だけ、同じ候補版契約へ追加する。
