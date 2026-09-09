# v2.9 修正記録

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
最終検証はtest_results.txtを参照。日次状態確定・UI・実OSS・本番は後続開発。

# Phase 1B（パッケージ版2.9.0維持）

- 版付きモデル/context保存契約、内容アドレス方式のローカル保存、checksum照合を追加。
- baseline固有のSeries・残差JSON変換を共通I/Oから分離。
- 期待する学習条件、run、保存モデル、origin、cutoffを復元時に照合。
- 別プロセスで再fitせずPOINT/QUANTILEの完全一致を検証するartifact_demoを追加。
- Workerジョブ再開・DB/API/UI・クラウド保存は未実装。
