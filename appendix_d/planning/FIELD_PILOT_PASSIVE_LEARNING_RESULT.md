# Field Pilot 低負担・受動学習 / 改善Observability 結果

基準: `main`、Field Pilot `SHADOW / READ ONLY`。指示書は業務要件として確認し、現行コード・[実データ検証](FIELD_PILOT_REAL_DATA_LEARNING_VALIDATION_2026-09-28.md)との整合を調べた。原本データ、設定値、認証情報はRepositoryに含めない。

## 今回実装した範囲

| 項目 | 状態 | 内容 |
| --- | --- | --- |
| 通常日の追加入力 | 0 | 担当者向けの新たな入力画面・質問を追加していない。投入分類と画面閲覧を自動記録する。 |
| 改善Event Ledger | 実装 | 既存の監査ログ・操作ログとは別のSQLite台帳。event ID、時刻、業務日、JAN/拠点/予測run/snapshot/版、数値metrics、結果、固定error codeを保存。raw行、ファイル名、自由記述、資格情報はスキーマに持たず、metric名と識別子を制限。 |
| 自動取得 | 一部 | Inbox分類・確認待ち・重複・正式取込成功と、Pilot画面の表示可否を記録。予測・Projection・FEFOの実行時間や画面詳細操作までは未接続。 |
| Data Freshness | 実装 | 必須入力ごとの確認状態と最終採用時刻をInbox集計に追加。管理者設定の版付き許容時間と在庫snapshotの日本時間業務日を照合。未設定、前日、未来、許容超過では表示を止める。予測runのorigin日がsnapshot日と一致する既存Projection Gateも維持。 |
| system/operator/actual比較 | 一部 | 既存Field Learning台帳のcase IDで同一JAN×倉庫×業務日を結合。system対operator、forecast対actual demand、operator対actual shipment、3つの業務KPIを週次集計。実績欠損は`null`。ending inventoryは既存actual契約に無いため未比較。 |
| 差異候補 | 一部 | 承認版付き最小差・反復日数で小差を抑制し、OBSERVED / REPEATED / QUESTION_READYを管理者レポートに表示。原因推定や自動改善は行わない。CONFIRMED以降の専用永続stateは未実装。 |
| 週次レポート | 一部 | 管理者CLIでイベント件数と現場検証台帳の比較・KPI取得率をJSON出力。週次対象caseは業務日・case ID順のページ取得で全件集計する。後日実績のending inventory比較は未対応。 |
| 保持期限 | 実装 | 管理者指定のタイムゾーン付きcutoffより古い改善イベントだけを削除するCLI。既存監査・操作ログを削除しない。自動実行スケジュールは未設定。 |

## 現場運用のGateと未接続部分

**現在はNO-GO。** Unified Inboxの認識・分類は正式取込ではない。現行`inbox_cli`は`validated_import` callbackを渡しておらず、確認済みCSVも`RECEIVED`のまま。したがって、ファイル投入だけで承認済みSnapshot→Forecast→Projection→FEFOを日次更新する流れは未成立である。今回、成功したように見えるダミー取込や自動forecast runは追加していない。

実データの倉庫在庫にはJAN列と正式snapshot日時列がない。商品コード→JAN対応表、ファイル名日付の締め時刻policy、賞味期限欠損・重複の業務判断が必要。これらを推測で埋めない。工場在庫・生産予定・PDFも今回の原本では確認できない。既存のField Learning台帳に実績がない場合、3業務KPIは未計測であり、`0`と解釈しない。

鮮度policyは`Data\Config\pilot-settings.json`の`freshness_policy`に、承認済み`version`と`max_snapshot_age_hours`を設定する。既存設定にこれが無い場合は`SETUP_REQUIRED`となり、旧結果を表示しない。現場担当者には設定操作を求めず、管理担当者が版と閾値を確定する。画面への適用はPilotのInbox Gateが構成されている場合に限る。

## 次の実装順

1. 実データのJAN対応とsnapshot日時policyを承認し、CSV正式取込callbackをUnified Inboxへ接続する。RECEIVEDとPROCESSEDを区別し、異常値を隔離する。
2. 正式取込完了からSnapshot・Forecast・Projection・FEFOを安全に更新し、各段階の業務日・版・成否・所要時間を台帳へ記録する。失敗時は前日結果を当日結果として表示しない。
3. 後日実績のending inventory等を契約に追加し、業務KPIの欠損率と観測対象範囲を明示する。週500 case超のページング集計は追加済み。
4. 繰り返し差異の原因確認を既存の承認画面へ接続し、候補stateを永続化する。質問は例外時のみ、原則一日0〜1件とする。
5. 観測の保存期間を業務承認し、定期retentionと週次レポートをスケジュール化する。画面操作の詳細イベントはプライバシー上の目的・最小化条件を定めてから追加する。

## 検証と操作

単体・Field Pilot回帰テストとRuffを実行。対象21件成功、Windows全体回帰718件成功・20件skip・Linux専用計測と変更中の配布照合の2件を除外。新しいテストは生行の拒否、KPI未計測、鮮度異常、InboxがREADYでも古いsnapshotを遮断すること、差異抑制と同一caseの実績照合を確認する。実データの新たな正式取込テストは、上記未承認条件により行っていない。

管理者週次集計例（値は承認済みのものに置換）:

```powershell
python -m forecast_provider.field_pilot.improvement_cli --events-db 'Data\Inbox\improvement-events.sqlite3' --end-date YYYY-MM-DD
```

Field Learning台帳の集計には`--field-learning-db`と`--minimum-gap-cases`、`--repeat-days`、`--threshold-version`を追加する。`--purge-before`は管理者による明示的な保持期限処理にのみ用いる。詳細は[管理者導入運用](../docs/FieldPilot_管理者導入運用.md)。

## 判定

| 指標 | 判定 |
| --- | --- |
| 受動学習 | INCOMPLETE |
| Unified Inbox→正式取込 | FAIL |
| Forecast / Projection / FEFO日次更新 | FAIL |
| 改善Observability | CONDITIONAL（Inbox・画面のみ） |
| Data Freshness | CONDITIONAL（承認済みpolicy設定時） |
| Learning Candidate | CONDITIONAL（読取専用の差異候補） |
| 担当者の通常日追加操作 | 0 |
| 現場Pilot | **NO-GO** |

最大の残課題は、実データから正式在庫Snapshotへ入れるための承認済みJAN mappingと日時policy、およびUnified Inbox→正式取込→予測更新の接続である。
