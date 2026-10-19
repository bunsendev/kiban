# pilot.45 配布パッケージ（2026-10-20）

Windows x64 PyInstaller onedirを再ビルドし、DownloadsへBunsenPortable-0.6.0-pilot.45.zipを作成。アプリのSOURCE-COMMITはf7f05cb。履歴期間・方式比較の操作ガイドをビルド工程の同梱対象に追加した。

- 本体ZIP：69,161,436 bytes、SHA-256 `4f12d2f113accc5d1abaa7cd2fbd4a66d91045acf97b64e86c8554c722ebb6ea`
- レポート単体ZIP：ブンセン_最新版レポート_pilot45.zip、SHA-256 `ce1778a05aa45084c85a5ee4ba94a34008a60f7152ebdc94870e9d19aa11fcc6`
- 本体ZIPにもReports配下へ数量CASE確認済みの比較レポート、比較画面、今回の変更・更新手順を同梱。
- 既存の確認済み除外設定を同梱。実際の出荷CSV/PDF、履歴比較DB、APIキー、Token、端末設定ファイル、署名秘密鍵は同梱しない。
- 導入手順と今回の変更説明に、旧版終了・フォルダー全体のバックアップ・同一PCのData引継ぎ・同じWindowsユーザーでの起動確認を記載。

## 検証

梱包テスト2件成功（0.41秒）、対象Ruff成功。PEヘッダーでAMD64を確認。凍結PYZアーカイブを読取検査し、history_study、history_import、history_study_routes、history_algorithms、forecast_verificationの5モジュールを確認。新規HTML/JS同梱確認。manifestの2,555ファイル全てSHA-256一致、版番号pilot.45、Data空、資格情報・実績DB・ログ不在を確認。本体ZIPとレポートZIPのCRC検査成功。配布ZIPごとのSHA-256ファイルも生成。

CRTの正規DLL api-ms-win-crt-private-l1-1-0.dllに含まれるprivateという単語は秘密鍵ではない。秘密鍵ファイル、DPAPI資格情報、setup.jsonの不在を別に確認。PEMはcertifiのCA bundleと更新検証公開鍵のみ。CSVは人工サンプルのみ。

EXE実起動試験は以前の自動承認レビューによる実行拒否を維持して未実施。起動成功とは報告しない。現場PCでの起動・版表示・設定保持の受入確認が必要。自動更新用の署名付きGitHub Release公開は本作業に含まない。

比較内容の前提・精度・候補12系列についてはTHREE_YEAR_HISTORY_RESULT.mdを参照。全体回帰は同文書に記録した結果を引継ぎ、今回の変更はビルド時のガイド同梱追加のみ。実データや配布レポート本体はRepositoryにcommitしない。
