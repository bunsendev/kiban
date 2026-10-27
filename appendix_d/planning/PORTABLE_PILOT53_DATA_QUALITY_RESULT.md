# pilot.53：欠損検知と予測方式選択 Phase 1

2026年10月27日。ユーザーが承認したPhase 1設計に基づく実装。版は0.6.0-pilot.53。

## 実装した機能

取込・フォルダー投入の共通経路で、日付・倉庫・JANごとに品質検証を保存する。現場画面に正常／警告／重大エラー、対象期間、最終データ基準日、受信時刻、正常取込時刻、欠損日数・件数、出荷履歴充足率、在庫確認件数を表示。日付・倉庫・商品・異常区分で絞り込み、日付集約と50件ページ分割、不足項目ごとの予測への影響を表示する。

FILE_MISSING、DATE_MISSING、WAREHOUSE_MISSING、PRODUCT_MISSING、QUANTITY_MISSING、DUPLICATE_RECORD、INVALID_VALUE、DATA_DELAYED、ABNORMAL_CHANGEを区別。受信予定未設定を予定ファイルの未着と断定せず、未来日・登録済み休業日・非取扱期間・除外商品を不要な欠損として数えない。商品マスターの照合条件はIT担当者が設定できる。

A「補充して通常予測」が初期選択。既存の直近28日条件を基本とし、登録した休業日・取扱期間を考慮する。B「推定補完」は今後対応と表示し、APIでも拒否する。C「欠損を残した暫定予測」は既定の前週同曜日モデルに限定。最低7観測だけでなく、将来14日すべてについて計算可能な同曜日の実績を確認する。担当者同意・最新検証ID・実行要求IDが必要。候補モデル割当がある場合は既定へ勝手に切り替えず停止する。

出荷だけの需要予測にもCを追加したが、在庫・補充・欠品リスクは評価しない。暫定表示を結果画面、保存済み一覧、CSV、実績比較の元予測情報へ保持する。在庫評価には追加の担当者承認を求め、出荷を自動確定しない。通常予測へ不要な暫定承認は追加しない。

不足データを追加取込した後の検証で補充を確認する。原本ハッシュの包含関係と日付・JAN・状態を照合し、確認できたものだけ補充済みとする。後続範囲外は再確認として扱う。旧検証・予測・修正履歴は保持し、欠損を0として実績へ登録しない。通常の35日参考バックテストでも未観測の正解値を0に変えず、評価対象外として数える。

## 操作手順

1. 現場画面で原本ファイルを登録し、従来どおりPDF読取・必要な確認・分析への受渡しを行う。
2. 「データの充足状況・不足一覧」で不足日・倉庫・商品を確認する。原本を読み取っただけでは正式採用しない。
3. 原則はA。不足データを追加し、新しい取込候補の画面で再検証する。同じファイルを重ねても数量は増やさない。異なる訂正版は衝突を確認して処理する。
4. Cを使う場合は明示的に選び、欠損と影響を確認して同意する。選択不可なら、モデル・観測不足・原本確認などの理由を確認する。
5. 結果の「暫定予測」表示を確認する。通常どおり結果の確認・修正・CSV保存を行える。正式データを後から追加しても、以前の予測は消えない。
6. 暫定結果で在庫・賞味期限の評価を進める場合も、担当者が影響を確認して承認する。

## 判定の範囲と注意点

現在の正式経路は日次出荷履歴と基準日の在庫を使う。充足率は出荷の必要期間に対する値であり、PDF全項目の読取正解率や、過去28日すべての在庫が正しいことを示さない。過去3年の全日付を一律必須にしない。PDF「現在欄の空欄0」は承認済み帳票の範囲だけに適用し、ファイルや商品行の未受信を在庫0にしない。

Production Runは共通の予測基準日を持つため、同時予測で倉庫の基準日が異なる場合は古い倉庫を対象外理由付きで残す。新たに同時予測するには基準日を揃える。不足のある新しい倉庫に正常な倉庫の基準日を引きずらせない。保存済み結果は倉庫・保存日時を選んで引き続き見られる。

営業カレンダー・受信予定・取扱期間・商品マスター・異常変動閾値は、現場画面では参照のみ。変更は既存のWindows管理者設定画面のJSONで行い、設定者・理由付きの新しい版として保存する。各PCの設定は独立している。設定例・APIは同梱の「Portable_欠損検知と予測方式選択.md」を参照。

## データベースと保護

新規DBは `Data/State/data-quality.sqlite3`、スキーマ1。quality_meta、quality_records、quality_sourcesの3テーブルを追加する。受信、設定、検証、予測実行参照を追記保存し、レコード内容のSHA-256で読み戻しを検証する。設定はknown_atで時点選択し、古い記録を上書きしない。既存業務DBを再作成しない。元ZIP・確認済み集計のハッシュをキャッシュ再利用時にも検査する。

新DBは学習バックアップの対象。暫定結果・修正・品質履歴を含むDataを新しい保存先へ復元するテストで、Windowsの長い復旧パスによりWinError 3になる既存不具合を検出。復旧側のパスもDataPathsのWindows拡張パスに統一し、実際の全Data復元が成功することを確認した。元Dataを削除して回避しない。APIキー・送信用Tokenは従来どおりバックアップ対象外。

## 検証結果

- 全体回帰：1229件成功、20件スキップ、3件除外、1291.72秒。正常予測、PDF、過去履歴、移動、更新、ログ、セキュリティ、結果修正を含む。
- 最終コードの関連検証：65件成功、224.46秒。うち新しい品質検証モジュールは19ケース。全体回帰との重複件数は加算しない。
- 全体回帰の後に、原本ハッシュ再検査・基準日一致保護・一覧の影響表示を最終化し、上記の関連検証を再実施。倉庫一覧の破損検査は同一基準日の正常データをfixtureとし、基準日不一致は別ケースで検査する。テストの削除はない。
- Node画面テスト10本、JavaScript構文50ファイル、Ruff、git diff --check成功。
- 5日欠損をNaNで保持したCの14日予測、後日補充したA、旧結果・修正保持、在庫0と空欄、予定未設定、休業日・取扱期間、商品省略、未受信倉庫、モデル非対応、未来日、重複・改変、バックアップ・復元を確認。
- 20件のスキップはオプション依存・外部環境等。3件の除外は、以前の自動承認レビュー拒否に従い未起動とした2件と、リリースハッシュ更新後に別実行する検査1件。Starlette/httpxの非推奨警告1件が残る。

今回の検証は人工データによる技術検証。実PDF全行の正解率、実AI API、実受信サーバー、現場PCでの受入、凍結EXE・ブラウザーの実起動は今回未検証。以前の起動拒否を別手段で回避せず、プロセス内API・DOM・Windowsファイルシステムと凍結内容の静的照合で確認する。

## 指示書の受入項目への回答

| 項目 | Phase 1の対応 |
|---|---|
| 正常、1日・複数日、特定商品欠損 | 正常条件／全不足日／商品不足を区別する検証を実装 |
| 数量0と空欄 | 0は正常、空欄・不正値・未受信は別判定 |
| 再取込と追加補充 | 数量の二重加算なし、補充済みは後続の証拠で判定 |
| 欠損補完予測（No.9） | BはPhase 2。Phase 1では欠損を残すCを暫定表示して保存 |
| 非対応モデル | UIと実行時の両方で制限。勝手なモデル切替なし |
| 正式数量と推定誤差（No.11） | 正式データの後日追加・旧予測保持は対応。推定値と正式値の誤差はB実装後 |
| 再実行、移動、正常倉庫継続、未来日 | 回帰・追加テストで確認。移動を販売とみなす新しい逆算は行わない |

## 未実装とPhase 2以降

Bの推定補完、在庫からの出庫逆算、実入庫日・輸送リードタイム・返品・廃棄・調整の補正、3年履歴を利用した補完、推定数量と正式数量の誤差保存はPhase 2。Cの他モデル対応はモデルごとの必要期間・前処理を検証して追加する。営業カレンダー等は管理者JSON設定がPhase 1の操作範囲。ムロオ自動受信・未受信通知・自動再取込・自動予測はPhase 3。

## 配布と更新

Windows x64版pilot.53を別フォルダーへ展開する。旧版でバックアップを保存し、旧ランチャーを終了する。同じPCの旧Dataを新版Dataへコピーして引き継ぐか、バックアップを検証して復元予約し、ランチャー終了・再起動で復元する。空の新版Dataで旧Dataを上書きしない。版番号・履歴・API保存状態・品質検証を確認する。

配布ZIPの凍結ソース一致、画面資材、全ファイルSHA-256・CRC、Data空・秘密情報不在の最終結果は配布検証記録で確定する。署名済み更新サーバーへの新規公開やGitHub pushは今回行っていない。

## 変更ファイル一覧

- `"docs/Portable\345\260\216\345\205\245\346\211\213\351\240\206.txt"`
- `"docs/Portable_\346\254\240\346\220\215\346\244\234\347\237\245\343\201\250\344\272\210\346\270\254\346\226\271\345\274\217\351\201\270\346\212\236.md"`
- `"docs/\343\201\213\343\202\223\343\201\237\343\202\223\346\223\215\344\275\234\343\203\236\343\203\213\343\203\245\343\202\242\343\203\253.txt"`
- `CODEX_START_HERE.md`
- `SHA256SUMS.json`
- `planning/PORTABLE_PILOT53_DATA_QUALITY_RESULT.md`
- `portable/__init__.py`
- `portable/api/app.py`
- `portable/api/business_archive.py`
- `portable/api/business_archive_intake.py`
- `portable/api/daily_auto_run.py`
- `portable/api/data_quality.py`
- `portable/api/data_quality_routes.py`
- `portable/api/data_quality_rules.py`
- `portable/api/data_quality_store.py`
- `portable/api/field_read_model.py`
- `portable/api/field_routes.py`
- `portable/api/forecast_capabilities.py`
- `portable/api/formal_forecast_pipeline.py`
- `portable/api/formal_shipment_daily.py`
- `portable/api/product_exclusions.py`
- `portable/api/production_handoff.py`
- `portable/api/production_projection.py`
- `portable/api/reference_demand.py`
- `portable/api/result_feedback.py`
- `portable/api/result_feedback_routes.py`
- `portable/api/runtime_assignments.py`
- `portable/api/saved_forecasts.py`
- `portable/api/static/daily-auto-run.js`
- `portable/api/static/field/accuracy.js`
- `portable/api/static/field/data-quality.css`
- `portable/api/static/field/data-quality.js`
- `portable/api/static/field/feedback-admin.js`
- `portable/api/static/field/index.html`
- `portable/api/static/field/manual.html`
- `portable/api/static/field/progress.js`
- `portable/api/static/field/quality-settings.js`
- `portable/api/static/field/results.js`
- `portable/api/static/field/saved-forecasts.js`
- `portable/api/static/field/settings.js`
- `portable/api/static/operator-results.js`
- `portable/build_windows.py`
- `portable/runtime/learning_backup.py`
- `test_results.txt`
- `tests/portable/data_quality.mjs`
- `tests/portable/intake_progress.mjs`
- `tests/portable/test_data_quality.py`
- `tests/portable/test_saved_forecasts.py`

## 配布検証

Windows x64の凍結464モジュールと起動スクリプト、画面資材68ファイルが最終ソースと一致した。Dataは空。全体実行から除外したリリースハッシュ検査と梱包テストは別実行し3件成功（4.17秒）。make_release.py --checkは1241/1241一致。ZIP全ファイルとCRCの最終結果・ハッシュは配布時の検証記録に保存する。
