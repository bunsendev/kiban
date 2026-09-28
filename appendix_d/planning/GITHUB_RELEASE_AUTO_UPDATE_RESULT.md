# GitHub Releases 更新基盤：実装結果と公開前Gate

更新日: 2026-09-29。対象: `bunsendev/kiban` Field Pilot。これは実装・検証の実測結果であり、現場更新完了の宣言ではない。

## 1. Architecture

開発Repositoryでテストとビルドを実行し、検査を通った配布専用パッケージだけを別のPublic Release Repositoryへ公開する。現場PCは公開Releaseを匿名で確認し、署名済みManifestとSHA-256で配布物を照合する。更新処理は業務処理・Feedback送信から分離する。

## 2. Development Repository

2026-09-28時点で `bunsendev/kiban` はPublicとして表示される。指示書のPrivate前提と相違する。可視性の変更は未実施。既存の外部利用・権限への影響を確認して変更する必要がある。

## 3. Release Repository

公開配布先 [bunsendev/kiban-releases](https://github.com/bunsendev/kiban-releases) を作成済み。Release immutabilityを有効化し、用途外のWiki・Issues・Projectsを無効化した。公開READMEにasset契約と禁止物を記載した。更新providerの`OWNER/REPOSITORY`はこの配布先に固定済み。Releaseは未発行。公開禁止物を除いた配布物がまだないため、既存ZIPを使って発行しない。

## 4. Version Policy

配布版は `0.1.0-field-pilot.N` と通常の `MAJOR.MINOR.PATCH` を解析・比較する。Python package版 `2.9.0` は配布版ではない。`pilot` と `stable` のchannelを区別し、Manifestの `minimum_version` より古ければ手動対応とする。RC4のインストーラー配布版は `0.1.0-field-pilot.4`。RC4の状態は `FIELD_PILOT_RC4_INSTALLER_AND_UPDATE_STATUS.md` に記録する。

## 5. Manifest

`kiban-field-pilot-update-v1` 形式で、版、channel、最低版、パッケージ名、SHA-256、サイズ、再起動、DB migration番号、公開日、critical、短い日本語更新内容を持つ。Ed25519署名を `manifest.sig` として分離し、固定した公開鍵で検証する。SHAだけでは発行元を認証できないため、署名を必須にする。秘密鍵はRepositoryに置かない。

## 6. GitHub Actions

未実装。Windowsのソース非同梱ビルドができるまで、公開Releaseを作成するworkflowを有効にしない。設計するtriggerは明示tagまたは `workflow_dispatch` のみとし、main mergeでは発行しない。別RepositoryへのContents write資格情報はActions Secretで管理し、現場PCに置かない。

## 7. Release Assets

予定: `BunsenFieldPilot-<version>.zip`、`manifest.json`、`manifest.sig`、`SHA256SUMS.txt`。現行 `make_release.py --field-pilot` のZIPはPython/PowerShellソースを含むため、Public Releaseには使用不可。`release_preflight.py` はソース・設定・実データの拡張子、危険なパス、既知Secret形式を拒否する。ただし、バイナリ内部の全秘密情報を検出できる保証はない。別途ビルド由来と内容の監査が必要。

## 8. Updater

Release一覧、署名Manifest、パッケージURLを匿名で取得するGitHub adapter、版比較、再開可能なRange download、サイズ/SHA-256照合、失敗ファイル隔離を実装した。更新確認結果をローカルSQLiteへ追記するserviceは6時間cacheし、明示的な手動確認では再取得できる。現場管理画面から認証付きで状態表示・手動再確認できる。署名公開鍵未設定時は外部通信せず未設定と表示し、GitHub通信失敗も業務処理を止めない。公開鍵は現場Configの`release-update-public.pem`に配置する契約としたが、鍵の発行・現場配備は未実施。RC4では起動/終業時の更新確認を接続済み。更新適用UIは未接続。

## 9. Backup

既存の `Kiban.FieldPilot.Recovery.psm1` がConfig、ローカル設定、学習、Inbox、PostgreSQL dumpを扱う。`field-pilot-update-backup.ps1`から`pre-update`のFULLバックアップを実行・検証できる。更新確認SQLiteと署名公開鍵も復旧対象に追加した。既存の復旧policyは`pre_update_keep`未指定でも既定5件として扱う。更新適用処理からこのバックアップを必須Gateとして呼ぶ接続は未完了。

## 10. Migration

適用対象のバイナリ形式が未確定のため、更新専用の版付きmigration runnerは未実装。Migration失敗時には切替を禁止し、旧版とDataの復旧を検証する必要がある。

## 11. Smoke Test

更新版起動、DB、Config、Learning、Unified Inbox、Shadow/Forecast/Projection/FEFO read、Feedback Configを検査する更新専用Gateは未実装。

## 12. Rollback

現行のApp/Data分離と既存バックアップは利用できるが、更新のatomic切替・自動rollback・rollback失敗の現場表示は未実装。新パッケージ形式確定後に実装し、故障注入で確認する。

## 13. Feedback連携

更新確認はFeedback Token・送信先に依存しない独立serviceとして実装した。既存のFeedback側の更新通知処理は別経路として残る。RC4では起動/終業時の更新確認をbest-effortで呼ぶ。更新適用は未実装。

## 14. Windows Test

人工データでManifest署名・版比較・GitHub Release解決・ダウンロード再開・ハッシュ照合・cache/offlineをpytestで確認。現場Windows PCでの更新検知から翌日起動までの受入は未実施。

## 15. Security

GitHub通信はHTTPSで、配布先URLとredirect先を制限する。署名公開鍵は現場設定側に置く設計。公開鍵の初回配布・交換手順は未完了。現場PC用GitHub Tokenは不要。公開パッケージには現場固有設定や実データを含めない。

## 16. Secret Scan

パッケージのZIP構造・拡張子・パス・既知Secret文字列をpreflightで検査する。これは必要条件であり、秘密情報が一切ないことの証明ではない。現行ソース同梱ZIPはGateで拒否される。

## 17. Known Issues

開発Repositoryの公開状態、ソース非同梱ビルド未整備、署名鍵とActions Secret未設定、更新適用・migration・smoke・rollback未実装。よって指示書の「完了条件」は未達。現行Installerを公開Repoへ再配布して回避しない。

## 18. Release Procedure

1. 開発Repositoryの可視性方針を確定する。
2. ソース・顧客設定・業務データを含まないWindows実行パッケージを構築し、内容を監査する。
3. Windowsでテスト、Ruff、integration、preflightを通す。
4. Actions専用の署名鍵とPublic Release Repositoryへの最小権限資格情報を設定する。
5. 明示的なtag/手動triggerからのみ署名・SHA生成・Release公開を行う。
6. 別環境で匿名ダウンロードを確認し、現場PCでBackup、Migration、Smoke、Rollbackと翌日起動を受け入れる。

上記の未完了項目が残る間は、公開Releaseと現場自動更新を有効化しない。

## 19. Ed25519署名鍵の生成と保管

公開鍵は秘密鍵から生成する。開発Repository直下や配布Repository内に秘密鍵を作らない。Windows PowerShellで`appendix_d`に移動し、次を実行する。

```powershell
python -m pip install cryptography
python -m forecast_provider.update_service.keygen_cli --output-dir "$env:LOCALAPPDATA\Bunsen\ReleaseSigning"
```

画面に表示される入力欄で16文字以上のパスフレーズを2回入力する。生成される`release-update-private.pem`はパスフレーズで暗号化され、公開しない。オフラインにバックアップし、パスフレーズは別経路で保管する。`release-update-public.pem`だけを`build_field_pilot_installer.py --public-key-file`に渡し、インストーラーを通じて現場PCへ固定する。公開鍵をGitHubから直接取得して信頼させる方式は採らない。

ソースを含まない正式パッケージが完成した後、`python -m forecast_provider.update_service.release_cli --package ... --output ... --version ... --channel pilot --minimum-version ... --database-migration ... --signing-key-file "$env:LOCALAPPDATA\Bunsen\ReleaseSigning\release-update-private.pem"`でManifestを署名する。パスフレーズは対話入力し、引数やRepositoryへ記録しない。署名済みの4 assetのみ配布RepositoryのReleaseへ添付する。鍵を紛失した場合、既存インストーラーの信頼を維持したまま鍵を自動交換することはできないため、現場更新の再設計と再配布が必要。
