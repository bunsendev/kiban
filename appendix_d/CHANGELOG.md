# v2.9 修正記録

## Phase 1Q

- subjectとroleを持つ複数Bearer credential、READ・ANALYZE・APPROVE・EXPORTのpermission表を追加。
- 全API endpointを操作種別に応じたpermissionで保護し、権限不足を403で拒否。
- 担当者監査項目をrequest bodyではなく認証済みsubjectから確定し、主体の詐称を防止。
- `/api/session`と管理画面の接続主体・role表示、permissionに応じた操作無効化を追加。
- productionで複数credential、Host allowlist、HTTPSを必須とし、API documentを非公開化。
- request ID、no-store、HSTSなどの共通security headerとdevelopmentの単一token互換を追加。

## Phase 1P

- 比較、受入case、比較CSV、採用判断を同じ画面で扱うFastAPI同一originの`/ui`を追加。
- tokenをブラウザーのメモリ内だけで扱い、CSP、`no-store`、`nosniff`、`no-referrer`を設定。
- 受入case一覧と、正式run・snapshot対象・受入可否を返すadoption context APIを追加。
- 受入caseの業務判断、比較CSVの発行・取得、採用・却下を既存の不変台帳へ接続。
- API通信、表示形式、DOM描画、画面状態、style、静的配信を分割し、responsive layoutとwheel同梱を追加。

## Phase 1L

- 成功済み日次buildを入力とする内容アドレス方式の重要品目候補算出jobを追加。
- 欠損と0を分離した数量、構成比、変動係数、出荷0率、欠損率とJAN変更・業務指定を追加。
- 初期3〜5品目、拡大20〜50品目を対象center・理由・担当者付きの不変な`selection_version`として保存。
- 品質条件を満たさない候補、候補外品目、候補外center、同じ版の上書きを拒否。
- SQLite/PostgreSQL、認証付きAPI、独立選定Worker、Compose、別process適合試験を追加。

## Phase 1K

- 日次buildと3〜5品目、availability mode、品質閾値を凍結する受入caseを追加。
- snapshot接続、artifact checksum、全暦日行、利用可能日数、欠測率、不完全率の技術判定を追加。
- JSON/Markdownの決定的な品質レポートと、担当者・理由・版付きの業務判断履歴を追加。
- 匿名データを`DRY_RUN`に固定し、実データの技術判定`PASSED`だけを承認可能にした。
- SQLite/PostgreSQL、認証付きAPI、独立受入Worker、Compose、別process適合試験を追加。

## Phase 1J

- 内容アドレス方式の予定ファイル定義とcenter×日付の完全性台帳を追加。
- 取扱期間、休業日、JAN有効期間、採用済み正規化行から6種類の日次状態を決定。
- 利用可能時刻を検査し、締切後の原本・実績・休業情報を過去時点へ混入させない。
- 決定的CSVとSHA-256を発行し、全上流版をprovenanceへ持つdataset snapshotを自動登録。
- SQLite/PostgreSQL、認証付きAPI、独立日次Worker、Compose、別process適合試験を追加。

## Phase 1I

- 正規化済み行から決定論的なJAN名寄せ候補を生成する独立Workerを追加。
- 名称一致だけでは統合せず、4種類の承認判断と監査情報を追加。
- canonical product、両端包含のJAN有効期間、商品×center取扱期間を追加。
- SQLite/PostgreSQLで同じ版の期間競合を防止する台帳と認証付きAPIを追加。

## Phase 1H

- 内容アドレス方式の版付き列mappingと出荷行正規化jobを追加。
- 原JAN・原本行を維持し、不正日付・数量・単位・行区分を理由付きで隔離。
- 訂正版の担当者・理由・decision version付き採用履歴を追加。
- 数量照合、center×月と隔離理由の品質API、独立正規化Workerを追加。

## Phase 1G

- 原本取込job APIと独立取込Workerを追加。
- ZIP traversal・容量・同名衝突検査と文字コード隔離を追加。
- SHA-256原本保存、重複、訂正版候補をSQLite/PostgreSQL台帳へ記録。

## Phase 1F

- dataset snapshot・実験を版付き内容アドレス方式でSQLite/PostgreSQLへ保存。
- 保存済み実験だけからrun planを生成するAPIとresult APIを追加。
- builtin baseline WorkerがModelRef/ContextRefを別プロセスで復元するE2Eを追加。
- snapshot checksumとknown_at付き将来特徴量の入力契約を追加。

## Phase 1E

- Bearer認証付きrun作成・状態・キャンセル・再開APIを追加。
- HTTP外でOriginExecutorを実行する独立Worker CLIを追加。
- RunStoreへ状態snapshotと実行可能run列挙を追加。

- 単独精度を自runの予定とtruthから計算し、比較相手による変動を修正。
- 完全runの選定を自runだけで判定し、正式共通集合を選定後に再構築。
- official_comparison_set_idと正式評価件数を追加。
- 単独評価可と2方式以上のランキング可を分離。
- 固定カレンダー内部生成とknown_at付き版選択を追加し将来変数の漏洩を防止。
- 旧将来変数通過試験を版テーブル付き契約へ移行（テスト削除なし）。
- 統合仕様を一つの完全文書へ整理し、配布記録とハッシュを更新。
- make_releaseで固定のappendix_dルートを作成し、未登録ファイルも照合する。

以前の修正（全予定・失敗記録、欠損規則統一、POINT分離、固定学習、累計、入力検証）は維持。
最終検証はtest_results.txtを参照。実データ業務受入・外部IdP連携・本番運用監視は後続開発。

# Phase 1B（パッケージ版2.9.0維持）

- 版付きモデル/context保存契約、内容アドレス方式のローカル保存、checksum照合を追加。
- baseline固有のSeries・残差JSON変換を共通I/Oから分離。
- 期待する学習条件、run、保存モデル、origin、cutoffを復元時に照合。
- 別プロセスで再fitせずPOINT/QUANTILEの完全一致を検証するartifact_demoを追加。
- Workerジョブ再開・DB/API/UI・クラウド保存は未実装。
