# Field Pilot ローカル自律運用: 現段階の結果

2026-09-28。基準 `main`。本書は指示書の完了報告ではなく、今回の変更で確認できた範囲と未完了の範囲を分ける。現場PilotのShadow境界を維持し、現場設定を記録しただけで正式取込・予測・出荷指示へ反映しない。

| 指示書の項目 | 現段階 | 確認事項・次の接続 |
| --- | --- | --- |
| 1. 現場設定UI | 一部実装 | 管理者画面 `/ui/pilot/settings` でJAN・時刻policyの確認、変更、履歴、旧版への復帰。担当者向けの候補確認・一括確認は未実装。 |
| 2. JAN変更 | 一部実装 | 商品コードを対象にcheck digit検査済みJANと商品名を版保存。正式canonical product/mappingには未接続。 |
| 3. Inventory Time Policy | 一部実装 | source・precision・Asia/Tokyo・適用開始日を版保存。日付しかない原本から正確な時刻を生成しない。正式snapshot取込には未接続。 |
| 4. Change Ledger | 一部実装 | 追記型SQLiteにchange ID、変更日時、担当者、対象、旧新版、理由、メモ、アプリ版、rollback先を保持。対象は上記2種。 |
| 5. Backup | 一部実装 | 上記変更直前に設定DBの一貫したSQLite copyとSHA-256 manifestを作成。失敗時は変更を止める。起動時・更新前・PostgreSQL・学習台帳の一括Backupと保持期間は未実装。 |
| 6. Restore | 一部実装 | 管理画面で旧版の内容を新しい版として戻せる。障害時のDB丸ごとRestoreは未実装。 |
| 7. Settings Export/Import | 未実装 | PC交換用の検証付き・秘匿情報を除いたbundleが必要。 |
| 8. Support Export | 未実装 | 原本・商品情報・資格情報を除外するformatと検査が必要。 |
| 9. Diagnostics | 未実装 | Backup、DB、API、データ鮮度、容量の状態表示が必要。 |
| 10. Online Update | 未実装 | 配布経路と署名検証の信頼根が必要。 |
| 11. Offline Update | 未実装 | Onlineと同じ検証engineへ接続する。 |
| 12. Migration | 未実装 | 非破壊migration、互換性・失敗時rollbackが必要。既存Dataは今回変更しない。 |
| 13. Rollback | 一部実装 | 設定版の復帰のみ。アプリ更新とDB復元のrollbackは未実装。 |
| 14. Data/Learning保持 | 一部実装 | 既存`Data`を残すインストーラへ`LocalSettings`/`Backup`を追加。実機更新・PC交換での検証は未実施。 |
| 15. Shadow Gate | 維持 | 既存の読み取り専用予測境界を維持。設定版からGate判定への接続は未実装。 |
| 16. Advisory Gate | 未実装 | 正式入力と業務承認条件の定義が必要。 |
| 17. Operational Gate | 未実装 | 自動出荷・正式意思決定には進めない。 |
| 18. Windows Test | 一部実施 | PowerShell構文、Compose構成、Python試験、JS構文を検証。現場PC実機導入・更新は未検証。 |
| 19. Security | 一部実装 | 管理者コード、loopback、Origin検査、設定値検証、設定変更前Backup。署名付き更新とサポート出力の機密検査は未実装。 |
| 20. 残課題 | 継続 | 復旧・診断・Updater、設定と正式取込の明示的な承認接続、現場担当者向けの簡単操作。 |

## 配置と互換性

既存`Data/Config`の`pilot-settings.json`と`inbox-policy.json`は読み取り専用mountのまま。新しい設定DBは`Data/LocalSettings`、変更前Backupは`Data/Backup`へ置く。従来の`pilot.env`には新mountの2変数を追記でき、新規導入にも同じ変数を作る。既存の正式在庫DB、学習契約、実データ、資格情報をRepositoryへ追加しない。

## 次の実装単位

1. 設定DB、学習台帳、必要なPostgreSQL状態を含む検証可能なBackup/RestoreとPC交換用Settings Export/Import。復元前Backupと失敗時の自動rollbackを必須とする。
2. 生データを含めないSupport ExportとDiagnostics。Backup失敗やData欠測を画面に明示する。
3. 署名済みmanifestと既知の信頼根を使う共通Updater。Offline/Onlineで同一検証を行い、別version展開、互換性確認、migration、readiness、原子切替、rollbackを実装する。信頼根と正式配布経路が未確定なら更新適用は閉じる。
4. 現場担当者の確認・一括操作と管理者承認を分け、正式mapping/時刻policyおよびShadow→Advisory Gateへ版ID付きで接続する。実データ受入と業務判断は別途記録する。
