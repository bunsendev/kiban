# Field Pilot Release 検証・導入判定

日付: 2026-09-28 JST
対象: Windows 現場PC、SHADOW / READ ONLY

## 提供範囲

- 専用配布ZIP、SHA-256照合付きセットアップ、デスクトップ起動・終了・状態確認、専用Docker Compose。
- 既存のPilot scope、承認済み在庫snapshot、確定予測run、FEFO評価を現場向け画面に表示する。予測・出荷指示を現場PCで新規計算しない。
- アプリ本体、設定・入力・ログ、PostgreSQL volumeを分離する。更新・アプリ削除時にデータを消さない。
- Field Pilotモードではloopbackの表示用GET以外をHTTP境界で拒否する。画面は試験運用の注意を常時示す。

## 技術検証

| 項目 | 結果 | 根拠・残件 |
| --- | --- | --- |
| Python回帰 | 条件付きPASS | WindowsでLinux専用`resource`計測1件を除外し、全体実行で700件成功・20件skip。配布照合1件は実行中のソース更新で失敗したが、最終版の対象14件と配布照合の再検査で成功。 |
| 静的検査 | PASS | `ruff check .` |
| PowerShell構文 | PASS | Pilot各ps1・moduleをParserで検査 |
| 人工データ read model | PASS | 設定、10件表示、期限別、書込み拒否、データ欠落 |
| ZIPと全ファイル照合 | PASS | ZIPを展開し現場用`Field Pilotセットアップ.cmd`からWindows PowerShell 5.1で全ファイル照合・再導入に成功。`make_release.py --check`で770/770件一致。 |
| Windows初回導入・停止・再起動・二重起動 | PASS | このWindows PCで専用PostgreSQL/APIを起動。停止後の起動と二重起動で同じ2 containerを確認。 |
| Windowsアンインストール | PASS | Appだけを削除しData/Configと専用Docker volumeの保持を確認。 |
| PC自体の再起動後の復帰 | 未確認 | この試験中にPCは再起動していない。 |
| 商品・倉庫・在庫・予測・期限別照合 | 部分PASS | 人工10件をread modelで照合。現場PCのDBへ正式Pilotデータは投入していない。 |
| 現場利用条件と業務承認 | 未確認 | 現場担当者・管理担当者の確認が必要 |

## GO / NO-GO

**NO-GO（現場業務での利用）。** Windows上のインストーラと読み取り専用画面は動作したが、画面の現在状態は`SETUP_REQUIRED`である。正式Pilotデータ・業務条件・PC再起動後の復帰・現場承認が完了するまで使用しない。画面に表示する数値は参考情報であり、出荷判断を変更しない。

## 残る導入前条件

1. 管理担当者が対象PCのWSL 2、Docker Desktopの利用条件、ディスク容量を確認する。
2. 実データのJAN対応、Pilot scope、APPROVED在庫、確定予測run、賞味期限policyを照合して設定する。未確認値を仮定して入力しない。
3. 現場担当者と管理担当者が1ページ手順、異常時連絡、画面表示を確認し、業務開始を承認する。

実データ、raw行、資格情報はRepository・配布ZIPに含めない。
