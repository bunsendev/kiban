# Field Pilot ローカル自律運用 実装計画

基準は `main`。現場PCの `App` と `Data` は既に分離されているが、設定・学習・変更履歴・復旧・更新は一連の運用として未完成。原本データと資格情報はRepositoryおよびサポート出力に含めない。Shadowは読み取り専用を維持し、設定を保存しただけで正式在庫・予測を自動承認しない。

## 分割と依存関係

| 工程 | 完了させる契約 | 依存 |
| --- | --- | --- |
| A: 設定と履歴 | JAN確認・時刻precision・Pilot scopeの版付き変更、追記型Change Ledger、過去版への復帰、現場設定UIと権限 | 既存のJAN候補、Field Pilot operator/admin境界 |
| B: 復旧 | 設定・学習・台帳・必要DBの一貫した自動Backup、保持Policy、管理者Restore、PC交換用Export/Import | Aの版と台帳、既存App/Data配置 |
| C: 診断とサポート | 原本・資格情報を除くSupport Export、DB/API/鮮度/容量/Backup診断、構造化観測 | A/Bの状態取得 |
| D: 更新 | 同一engineによるonline/offline更新、署名済みmanifest、互換性・migration検査、pre-update Backup、別version展開、readiness後のcurrent切替、自動rollback | B/C、配布署名の信頼根と配布経路 |
| E: Gate統合 | Shadow/Advisory/Operationalを分離し、未確認事項を画面に列挙。正式mapping・取込・予測更新へ版を接続 | A、JAN/時刻/単位等の現場業務確認 |

各工程は独立したmoduleと試験に分ける。`field_pilot`のAPI route、画面、Windows installerへ必要な入口だけを追加し、既存の取込・予測moduleへ設定DBを直接読み込ませない。

## 安全境界

- JAN候補の提示は正式承認ではない。商品コードとJANの照合根拠を保持し、曖昧候補は一括確定しない。重大mapping変更と単位変更は管理者確認へ回す。
- 在庫時刻は原本が日付のみなら `BUSINESS_DAY` 等のprecisionを保存し、存在しない時刻を作らない。版・適用開始日を持ち、過去snapshotを暗黙に再解釈しない。
- 変更前Backupが失敗した場合は変更を止める。Restoreは復元前Backupを作り、復元・検証に失敗したら元へ戻す。
- 署名検証の信頼根が未設定ならUpdaterは適用しない。SHA-256だけでは発行元を証明できない。現場PCへ長期GitHub tokenを保存しない。
- 現場担当者は通常のJAN確認・時刻・Pilot対象・軽微なSchema確認を行う。DB復旧・Updater・channel・重大mapping変更は管理者認証を必須とする。
- 既存 `pilot-settings.json`、`inbox.sqlite3` と正式Inventory mappingの移行は非破壊。新設定は旧設定を黙って置換せず、初回に明示確認を求める。

## 検証と受入

人工データで同一入力から同一版、二重実行の冪等性、変更履歴、設定復帰、Backup/Restore、Export/Import、機密除外、署名・互換性拒否、migration・smoke失敗時のrollback、旧版再起動、PC交換相当を確認する。Windowsでは初回導入・更新・再起動・既存Data/Learning保持を実機で確認する。pytest、Ruff、`make_release.py --check`をゲートとする。実データのJAN・時刻policy承認、正式取込、Forecast/Projection/FEFO更新と現場Pilot GO判定は別の業務受入とする。
