# Field Pilot RC1 Acceptance結果

判定日: 2026-09-28 JST。基準: PR #109統合後の`main`。RC branch: `codex/field-pilot-rc1`。判定対象は**このRC1配布物**であり、既存PCの旧版動作や利用者からの共有サーバー疎通報告をRC1の実機試験へ読み替えない。

| 項目 | 判定 | 根拠と残件 |
| --- | --- | --- |
| 1. Release Version | PASS | Windows配布版 `0.1.0-field-pilot.1`。Python package版 `2.9.0`とは別のRC識別子。 |
| 2. Commit | PASS | Installer内の配布ZIPに対応するsource commit: `fbe521b`。この結果文書は配布物から除外し、別commitで記録。 |
| 3. Installer | PASS（生成） | `dist/Bunsen-FieldPilot-0.1.0-field-pilot.1-Setup.exe`。Windows IExpress自己展開EXEを生成。`/C`でインストールを起動せずに展開し、内包ZIPのSHA-256と日本語ファイル名の展開を確認。Clean Installは未実施。 |
| 4. SHA-256 | PASS | `7b1f0018c80e24cf0d94181fb9b311eddfd81868886b402ca405daf7e6d5515d`。配布時は別経路で照合する。 |
| 5. Clean Install | NOT RUN | このPCには既存のPilot環境がある。空の現場PCでの導入、WSL/Docker初期設定は未実施。 |
| 6. Desktop Launch | NOT RUN | 旧版の専用API/PostgreSQLは稼働。RC1 Installerからの初回起動、ショートカット、二重起動は未実施。 |
| 7. Token | NOT RUN | DPAPI保存の実装と初回入力案内は確認したが、RC1でのToken入力・再起動・再表示防止の実機試験は未実施。 |
| 8. Feedback Connection | NOT RUN | 利用者は既存共有サーバーへの疎通成功を報告。RC1の暗号化Packageでの認証付きPOST/ACK照合はToken未設定で未実施。 |
| 9. Unified Inbox | PASS（人工データの回帰） | stable detection、分類、重複、UNKNOWN、確認待ち等の既存自動試験を全体回帰で実行。RC1 Installerからの現場一連操作は未実施。 |
| 10. Approved Learning | PASS（人工データの回帰） | 候補、承認、版保存と再認識の既存自動試験を実行。実ファイルの正式取込とは別。 |
| 11. Formal Pipeline | FAIL | Unified Inboxから正式取込、Snapshot、Forecast、14日Projection、FEFOへの自動接続は未実装。既存結果を自動更新した扱いにはしない。 |
| 12. Shadow UI | FAIL（このPCの現在状態） | 稼働中の旧版 `/api/field-pilot/view` は `DATA_NOT_READY`、`mode=SHADOW`、`read_only=true`。RC1の実データREADY表示は未確認。 |
| 13. End-of-Day | NOT RUN | 暗号化・Outbox・送信の人工データ試験は成功。RC1実機でBackupからサーバーRECEIVEDまでの操作は未実施。 |
| 14. Offline / Retry | NOT RUN | 再送・Backoff・冪等の人工データ試験は成功。実PCで回線OFF→再起動→SENTは未実施。 |
| 15. Restart | NOT RUN | 現場PCの再起動試験は未実施。 |
| 16. Backup / Restore | NOT RUN | 既存の復旧回帰は実行。RC1導入後の実データ・設定変更→復元は未実施。 |
| 17. Freshness | PASS（人工データの回帰） | stale時に表示を止める既存自動試験を実行。現場日時・実データでの照合は未実施。 |
| 18. Multiple Launch | NOT RUN | 旧配布版の過去試験はあるがRC1では未実施。 |
| 19. Japanese Encoding | PASS（静的・展開） | PowerShell構文検査、UTF-8 ZIPフラグ、Windows PowerShellのExpand-Archiveで日本語名のセットアップを確認。現場PC画面目視は未実施。 |
| 20. Online Update | CONDITIONAL | 署名Manifestの確認は既存試験で検証。更新適用と失敗からの復帰は未実装・未実施。無承認更新は行わない。 |
| 21. Update Failure | NOT RUN | 更新適用機能がないため、適用失敗時のRollbackは試験できない。 |
| 22. Uninstall / Reinstall | NOT RUN | 旧配布版の過去試験はあるがRC1では未実施。 |
| 23. Security | 条件付きPASS | 原本・Tokenを配布物へ含めない。TLS/AEAD/Privacy Manifestは自動試験で検証。RC1現場PCの資格情報・ログ/Support Exportを実機監査する必要がある。 |
| 24. Regression | PASS | 773 passed、19 skipped、Linux専用peak RSS1件deselected。Ruff、Windows PowerShell構文、配布SHA照合に成功。人工データの技術回帰であり実地受入の代替ではない。 |
| 25. SHADOW Gate | NO-GO | 現在の画面は`DATA_NOT_READY`。Pilot対象JAN、倉庫在庫、賞味期限、過去出荷、時刻Policyの承認済みセットをRC1で確認できていない。FACTORY・生産予定・RouteはSHADOW条件に含めない。 |
| 26. ADVISORY Gate | NO-GO | SHADOW未達。加えて工場在庫、生産予定、Route Lead Time、Recommendation validationの受入未了。 |
| 27. OPERATIONAL Gate | NO-GO | 正式業務利用の承認・実地検証は未了。 |
| 28. Known Issues | OPEN | 正式Pipeline未接続、RC1 Clean Install/認証付きPOST/再起動/オフライン再送の実地未確認、更新適用未実装。 |

## A〜P 実施順の記録

| 順 | 項目 | 判定 |
| --- | --- | --- |
| A | Clean Install | NOT RUN |
| B | Desktop / First Launch | NOT RUN |
| C | Feedback Token | NOT RUN |
| D | Feedback Connection | NOT RUN（旧疎通は利用者報告） |
| E | Unified Inbox | PASS（人工データ回帰のみ） |
| F | Approved Learning | PASS（人工データ回帰のみ） |
| G | Formal Pipeline | FAIL |
| H | Shadow UI | FAIL（旧版現状態はDATA_NOT_READY） |
| I | End-of-Day Sync | NOT RUN（人工データ回帰のみ） |
| J | Offline / Automatic Retry | NOT RUN（人工データ回帰のみ） |
| K | Restart Persistence | NOT RUN |
| L | Backup / Restore | NOT RUN（回帰のみ） |
| M | Data Freshness / Silent Failure | PASS（人工データ回帰のみ） |
| N | Japanese / Encoding | PASS（静的・展開のみ） |
| O | Online Update | CONDITIONAL（署名確認のみ） |
| P | Uninstall / Reinstall | NOT RUN |

## 判定

**明日のField Pilot配布: NO-GO。** Installerは生成できるが、現場PCのClean Installと認証付き同期を実行しておらず、正式Pipelineが未接続である。このPCの旧版Shadow画面も必要データ不足でREADYではない。特に「ファイルを入れれば予測結果まで更新される」運用として提供してはならない。

次の操作は、管理者がPilot対象JAN・在庫・賞味期限・過去出荷・在庫時刻Policy・Required File Policyを承認し、RC1の清浄なWindows環境でA〜Pを記録すること。その後、正式Pipelineの接続を別Phaseで実装・受入する。NO-GOをGOへ書き換えるには新しい証跡と承認が必要。

実データ、Token、秘密鍵はRepositoryとInstallerへ含めない。共有サーバーPHPは変更していない。

## 配布物の位置

- Installer: `C:\Users\zept0\OneDrive\ドキュメント\ChatGPT\New project\appendix_d\dist\Bunsen-FieldPilot-0.1.0-field-pilot.1-Setup.exe`
- SHA-256: `7b1f0018c80e24cf0d94181fb9b311eddfd81868886b402ca405daf7e6d5515d`
- 現場担当者向け1ページ手順: `docs/FieldPilot_現場担当者_1ページ.md`
- 管理者初回手順: `docs/FieldPilot_RC1_管理者初回設定.md`
- Release Notes: `docs/FieldPilot_RC1_Release_Notes.md`
