# 現場担当者向け4ステップUI：現状調査・実装計画

作成日：2026-10-05。対象：bunsendev/kiban。
調査基準：ローカル `codex/portable-light-ui`、commit `8ede6e5`（pilot.7）。
PR153〜155の追加機能を含む作業ブランチの調査であり、mainへのマージ確認を意味しない。
根拠：今回の「現場担当者向け4ステップUI 実装指示書」と参考画像、以下に挙げるソース。

**今回は調査のみ。既存コード、起動画面、保存データ、配布ZIPは変更しない。確認後に実装する。**

## 1. 結論

`/field` に独立した現場UIを追加する方針を推奨する。現在の `/` は維持する。
画面は「データアップ → 分析 → 結果 → 判定 → 完了」に分け、既存サービスを接続する。
既存HTMLをCSSで隠して流用するだけでは、画面責務・権限・用語の分離が不十分。

取込、確認待ちの処理、正式在庫、予測、在庫見通し、期限評価、推奨出荷、判断台帳は再利用可能。
追加が必要なのは、表示用Read Model、処理状態の橋渡し、例外時の簡潔な確認画面、商品単位の確認完了管理、Portableへの操作イベント接続など。

特に、**需要予測量と推奨出荷量は同じではない**。参考画像の「予測180箱」をそのまま「180箱出荷する」という判断へ変換してはいけない。
既存の予測結果へのフィードバックと、推奨出荷への採用・増減・見送りは別契約である。

## 2. 現状構造と根拠

パスはすべて `appendix_d/` からの相対パス。

| 対象 | 現在の実装 | 調査結果 |
|---|---|---|
| アプリ組立・ルーティング | `portable/api/app.py:create_app` | FastAPI。`/` が `static/index.html` を返し、多数のroute登録関数を呼ぶ |
| 現在の画面 | `portable/api/static/index.html`, `style.css` | 取込から管理機能までDOMに含む。管理機能の一部はCSSで非表示。画面分離・権限制御ではない |
| 画面処理 | `app.js`, `review.js`, `inventory.js`, `daily-auto-run.js`, `operator-results.js` 等 | 機能別JSはあるが、既存DOMや独自イベントに依存。新画面へ全scriptをそのまま読み込まない |
| ZIP投入・分析 | `business_archive_intake.py:BusinessArchiveIntake.ingest`, `business_archive.py:analyze_archive` | 原本、分析結果、日次整形CSVを保存。既存確認ルールも適用 |
| 投入フォルダ | `drop_folder.py:DropFolderIntake`, `drop_folder_routes.py` | `Data/Incoming` のZIP監視、安定確認、処理済/拒否/受付票。アップロードと同じingestを使う |
| JAN等の確認 | `business_review.py`, `app.py` のissue API | 未確定の判断・履歴・再利用ルールを保存し、確認後データを別保存 |
| 正式在庫 | `inventory_handoff.py`, `formal_pipeline.py`, `formal_pipeline_contracts.py` | 拠点・基準時刻・CASE確認、既存Unified Inbox/Worker、数量照合、Snapshot承認 |
| 予測への接続 | `daily_auto_run.py:PortableDailyAutoRun`, `formal_forecast_pipeline.py` | 確認状態に応じて停止・再開。14日参考予測と正式予測への橋渡し |
| 正式予測 | `production_handoff.py`, `production_worker.py` | 既存Dataset/Run/Executorを再利用し非同期実行 |
| 在庫リスク | `production_projection.py` | 在庫見通し・期限シミュレーションを既存サービスで計算。日次サマリーに不足・期限リスクと対象外理由 |
| 推奨出荷 | `production_decision.py`, `decision_input_package.py`, `decision_input_guided.py` | 工場・配送・安全在庫等の確定入力から既存Decision Engineへ接続。需要予測だけでは代用不可 |
| 推奨出荷の判断 | `decision_review.py:PortableDecisionReviews` | 商品×倉庫、結果版、revision、担当者、理由を追記。採用・増減・見送り・出荷なしを区別 |
| 予測の修正・感想 | `result_feedback.py:ResultFeedback` | 日別予測を保持し、日別の修正量・評価・理由・コメントを追記。全件/選択CSVあり |
| 学習候補・管理機能 | `learning_reviews.py`, `learning_experiments.py`, `runtime_*`, `pilot_*` 等 | 既存経路を保持。現場判断から自動で正式設定を変更しない |
| 起動 | `portable/launcher/main.py` | 現在は `/` をブラウザーで開く。フォルダを開くのもランチャー側 |
| 端末設定 | `portable/runtime/installation.py` | FIELD/IT_TESTは利用目的と端末識別。管理者ログインや権限ではない |

## 3. 再利用するAPI

下記は現在のコードで確認した経路。長い経路は表内で定義したprefixを使用する。

| 用途 | API |
|---|---|
| ZIP分析 | `POST /api/business-archives`（ZIP本体） |
| 分析履歴・結果 | `GET /api/business-archives`, `GET /api/business-archives/{analysis_id}` |
| 未確定データの判断 | `POST /api/business-archives/{analysis_id}/issues/{issue_id}` |
| 判断履歴 | `GET /api/business-archives/{analysis_id}/decision-history` |
| 投入フォルダ | `GET /api/drop-folder`, `POST /api/drop-folder/scan` |
| 在庫候補 | `POST /api/business-archives/{analysis_id}/formal-inventory` |
| 在庫登録 | `GET/POST /api/formal-inventory/{handoff_id}/pipeline` |
| 在庫承認 | `POST /api/formal-inventory/pipeline/{registration_id}/jobs/{job_id}/approve` |
| 日次処理状態・実行 | `GET /api/daily-runs/{analysis_id}`, `POST /api/daily-runs/{analysis_id}/advance` |
| 期限条件・日次サマリー | `POST /api/daily-runs/{analysis_id}/daily-summary` |
| 推奨計算の追加条件 | `GET /api/daily-runs/{analysis_id}/decision-inputs/requirements`, `POST .../decision-inputs/guided` または `POST .../decision-inputs` |
| 正式予測 | `GET/POST /api/formal-forecast/{build_id}/production-run`、同prefixの `/resume` |
| 在庫見通し | `GET /api/formal-forecast/{build_id}/production-projection` |
| 保存済サマリー | `GET /api/formal-forecast/{build_id}/daily-summary/{summary_key}` |
| 推奨・判断 | prefix=`/api/formal-forecast/{build_id}/daily-summary/{summary_key}/shipment-recommendation/{request_key}`。`GET prefix`、`GET/POST prefix/review` |
| 日別結果・フィードバック | `GET /api/operator-results/{kind}/{reference}`, `POST .../feedback`, `POST .../download` |

新画面は既存HTTP境界または同じサービスインスタンスを呼ぶ。バックエンドが自分自身へHTTPリクエストを繰り返す構成や、別の予測・在庫計算を新設する構成は採らない。

## 4. 見本と現状の差分

### 4.1 入力形式とアップロード

主経路は在庫/出荷CSVを含むZIP。投入フォルダもZIPを対象とする。
別に `ds,unique_id,y` 形式の人工CSV入口があるが、業務CSV・Excelの汎用受付ではない。
参考画像のExcel `.xlsx/.xls`、任意CSV直接投入を「対応済み」と表示しない。PDF解析も今回のUI再構成に紛れ込ませない。
Phase 1はZIPを明示し、ドラッグ＆ドロップとファイル選択を同じ既存APIへつなぐ。
複数ZIPを勝手に1つのデータセットへ結合しない。フォルダに複数件あるときは受付一覧から処理対象を選ぶ。

### 4.2 自動進行に必要な事前条件

現在のadvanceは、未確定JAN・日付等、在庫候補未作成、拠点/基準時刻/数量単位未確認で停止する。
正常系を無操作で進めるには、初回に確認した拠点・単位・ゼロ扱い・期限policyを版付きで保存し、今回入力へ適用可能か確認する必要がある。
確認済設定の有効範囲・期限が合わない場合は一時停止し、日本語の確認カードを出す。
未確認の条件にプログラムが `confirm=true` を一律設定して先へ進めてはいけない。
「通常は4工程、初回・異常時は工程内の確認」を推奨する。

### 4.3 進捗

アップロード分析は現状1リクエスト内の同期処理で、細かい5段階の進捗イベントはない。
正式予測はRun状態を取得できる。日次advanceはスレッド処理だがHTTP応答まで待つ区間がある。
最小追加の非同期実行ラッパーと永続状態を用意し、同じ既存サービスの開始/完了から工程表示する。
途中の割合が不明な区間は不定進捗にする。「3/5」は完了工程数であり、処理量の60%とは表示しない。
再読み込み時の再接続、二重開始防止、異常終了検出が必要。

### 4.4 商品名・倉庫・数量

日別予測の主キーは商品・倉庫IDであり、全商品の商品名を返す表示契約は不足している。
分析コードは問題行のlabel等を持つが、全商品の正式な名称一覧にはなっていない。
商品名は既存マスター/確認済対応を優先し、原本名称を参照する場合は出典を保持。未取得は「商品名未登録」、異なる名前があれば確認対象にする。
商品×倉庫を1行とし、倉庫名を表示または倉庫ごとに切り替える。同一JANの別倉庫を合算しない。
「予測」は「今後14日の予測（箱）」、在庫は「在庫基準日時」を明記する。読込日時と基準日時を混同しない。
現行正式経路のCASE確認済データだけ箱と表記する。くくり・パレットを勝手に箱へ変換しない。

### 4.5 3区分表示と予測対象外

既存サマリーの `risk_flags`, `shortage_reference_cases`, `blockers`, `excluded_series` を元に、表示の区分を定義する。UIで不足量やFEFOを再計算しない。

- 要対応：有効な既存計算で不足リスクが出たもの。
- 要確認：期限リスク、未計算、未確定情報、履歴不足など。理由を併記。
- 問題なし：必要な評価が完了し、評価した範囲にリスクがないもの。「計算上、注意なし」と補足。
- 同時リスクは1商品・倉庫を重複計上せず、要対応を優先し両理由を保持。

全件＝入力から識別できる商品×倉庫の対象集合。予測できた行だけを分母にしない。
JAN未確定で商品数を確定できない原本行は、別に「商品未確定：○行」と表示し、合計商品数に無理に換算しない。
サマリー自体が作れないときは「データ確認が必要」と表示し、全件緑にしない。

### 4.6 判定保存の重要な差分

| 判断対象 | 現在の保存 | 新UIでの扱い |
|---|---|---|
| 日別予測の評価・修正 | `result-feedback.sqlite3`、商品・倉庫×予測日、rating/quantity/revision | そのまま再利用可能。元の予測は不変 |
| 推奨出荷の採用・増減・見送り | `shipment-decision-reviews.sqlite3`、推奨結果×商品・倉庫、operator_decision/revision | 推奨計算ができた場合にそのまま再利用 |
| 14日合計予測に対する1商品ずつの3択 | 同等の期間単位契約はない | 小さな期間確認契約が必要。日別数量へ勝手に按分しない |

既存の推奨出荷判断は `ACCEPTED / INCREASED / DECREASED / REJECTED / NO_ACTION`。
画面の「数量を変更」は増減へ変換し、既存の必須理由を簡潔な選択肢で入力する。任意メモだけで既存検証を回避しない。
「今回は対応しない」は推奨を見送る `REJECTED` と、実出荷0箱の `NO_ACTION` を区別する。既定は見送りであり、0箱の実績を生成しない。

**推奨するPhase 1仕様**：需要予測しかない場合も「予測量の確認」として進められるようにする。期間確認は結果版・商品・倉庫・期間を固定した追記台帳へ保存し、元の予測や出荷指示には反映しない。推奨出荷がある場合だけ既存の推奨判断台帳を使う。期間確認の最小契約は実装前レビューで確定する。
既存の日別修正・全件/選択ダウンロードは結果画面の補助操作として残す。

### 4.7 完了の意味

完了は「今回の要対応/要確認のうち、担当者が判断できる対象の保存が完了」。リスク解消や出荷完了ではない。
例：「要対応・要確認8件中8件を確認。計算上注意なし82件は個別確認の対象外」。自動で90件を確認済みにしない。
未計算の商品は「確認した/対応を依頼した」という確認記録を保存できるが、予測できたことにはしない。未解決件数を完了画面にも残す。
次へ移動しただけでは保存済みにしない。二重送信・競合時は既存revisionを使い、保存成功後だけ次へ進む。
「終了する」は安全に開始画面へ戻る。ブラウザーからランチャー用停止tokenを公開せず、アプリ終了は既存小画面から行う案とする。

## 5. ログ・フィードバックの接続

PortableにはAPIログ、フォルダ受付票、日次状態、各判断台帳、性能記録がある。一方、新4工程に必要な表示・開始・完了等の共通操作イベントはPortableへ未接続。
別アプリの `forecast_provider/api/operation_event_routes.py` は認可依存。PortableへURLを呼ぶだけでは使えない。
`forecast_provider/operation_events` の `make_operation_event` と `SqliteOperationEventStore` を再利用する薄いPortable境界を追加する。
既存イベント名/metadataは許可リストで検査される。操作を `SOURCE_SELECTED / ANALYSIS_REQUESTED / ANALYSIS_RESULT_READY / ANALYSIS_FAILED / STEP_VIEWED / STEP_COMPLETED` 等へ対応付ける。担当者判断の内容は既存台帳が正本で、UIイベントは保存済み参照を記録する。
許可リストにないイベントを無検証で追加しない。イベントIDで重複排除し、業務保存成功をクライアントの自己申告だけで記録しない。

最低限記録するもの：投入、分析開始/成功/失敗、結果表示、判定開始、採用/数量変更/見送り、完了、エラー。
ファイル本文・APIキー・自由入力メモを汎用操作イベントへ複製しない。診断情報の外部自動送信は追加しない。
結果の感想は既存ResultFeedbackへ接続可能だが、「困ったとき」の商品非依存メモは現契約と異なる。
`forecast_provider/field_pilot/operator_feedback.py` の記録サービスを調べ、Portableから再利用するadapterを追加する。Field PilotのHTTP経路や認可がPortableにもあると仮定しない。

## 6. 新規UI・モジュール案

```text
portable/api/
  field_routes.py             /fieldと必要な表示APIの登録
  field_workflow.py           既存サービスの工程接続・停止/再開
  field_read_model.py         結果/理由/件数/単位の表示契約
  field_run_store.py          画面工程・冪等キー・復旧状態（計算台帳を代替しない）
  field_review.py             期間確認が必要な範囲の追記契約
  field_event_routes.py       既存操作イベント台帳へのadapter
  static/field/
    index.html / style.css    独立した構造・配色
    app.js / api.js           状態遷移・HTTP・日本語エラー変換
    upload.js / progress.js   投入・進捗
    results.js / review.js    一覧・1商品判断
    feedback.js               改善要望入口
```

一覧はページ分割/検索を用意し、全商品数を上限で切らない。件数カードはページ内件数ではなく全体集合から生成する。
既存日別CSVはそのまま再利用し、要約表示と日別ファイルの粒度を説明する。大量データはRead Model側でページ取得を検討する。
新たに書くDBは追加ファイル/追加テーブルのみ。既存原本・予測・判断台帳を上書きしない。
各モジュールは1責務とし、`app.py` や既存巨大HTMLに処理を集中させない。

## 7. ルーティング・管理者境界

- Phase 1：`/field` を追加、`/` は維持。ランチャーの既定先はまだ変えない。
- `/admin` を設ける場合も、CSSの非表示解除だけでは管理者専用にならない。管理機能の既存表示を独立エントリーポイントへ分離する。
- 現在はlocalhost/Originの制限が中心で、FIELD/IT_TESTは権限ではない。管理者のみを保証するなら、管理セッションと管理API側の認可が必要。
- 認可導入まで「管理者だけが使える」と表現しない。Phase 1の新画面には管理API操作を載せず、旧画面へ戻る経路をIT向け手順に残す。
- 管理者認可の導入を4工程UI全体の置換と一括にせず、別の受入項目として明示する。

## 8. 画面仕様案

参考画像を優先し、紺ヘッダー・落ち着いた緑の主要ボタン・白〜薄灰背景へ変更する。直前の水色テーマは旧画面に残す。
本文18pxを目安、大きい操作対象、十分な行間、目立つキーボードフォーカス。赤黄緑だけでなく文字・記号を併記する。
上部の工程表示は現在位置だけ強調し、操作可能な戻り先以外はクリックさせない。
工程内に必要な例外確認を表示し、技術用語・traceback・hashを現場へ出さない。
状態不明は「確認しています」、エラーは原因区分と次の行動を示し、技術詳細はログへ残す。
1366×768、1920×1080、狭幅、拡大表示、キーボード操作で確認する。

## 9. 実装順序と受入

1. 本計画の確認：需要予測確認と出荷判断の区別、期間判断、初回設定の扱いを確定。
2. Phase 1A：独立 `/field`、アップロード/フォルダ連携、進捗、例外確認、旧画面への戻り方。既定画面は維持。
3. Phase 1B：既存リスクのRead Model、商品名・倉庫・単位、全件/選択出力、1商品判定、追記保存、再開、完了表示。新判断契約は既存契約で表現できない部分だけ。
4. Phase 1C：操作ログ・改善要望adapter、同時操作/再起動/競合/中断を検証。
5. Phase 2：Repository外の提供済実データをコピーして分離したIT用Dataで一連操作。業務条件を捏造しない。原本・判断値・個別結果をGitへ入れない。
6. Phase 3：現場担当者が説明なしで使うモニターテスト。迷い、時間、未保存、文言、誤クリックを収集。
7. Phase 4：受入後にランチャー既定を `/field` へ変更。旧画面へ戻せる設定を残して配布を再生成。

## 10. テスト計画

- 既存Portable回帰（`tests/portable`）と、影響した共有契約のpytest、全体ruff。
- 既存 `test_daily_run_connects_input_to_reviewed_shipment_recommendations`、日次サマリー、在庫基準日不一致、フィードバック競合、全商品テストを維持。
- 新UIの正常系とJAN不明/履歴不足/単位未確認/日付不一致/壊れたZIP/空フォルダ/重複投入。
- 画面を再読み込みしても同じ処理へ復帰し、分析や判断を二重登録しない。
- 予測不可・期限評価不可を「問題なし」へ分類しない。全体合計と対象集合を照合。
- 需要予測確認と推奨出荷判断の数量/期間/保存先を照合。0・未入力・見送りを区別。
- 保存失敗や409時に勝手に次へ進まない。完了後も元のリスクと未解決情報を保持。
- 1,000商品以上、複数倉庫、14日分で一覧・選択出力・件数・再開を確認。
- 操作イベントの11種類の業務行為が観測できること、重複排除、個人/業務情報の不要な複製なし。
- 旧URL・API・SQLite・起動/終了/更新機能の回帰、凍結EXEと配布manifest確認。

## 11. 調査段階の完了と残る確認

今回行ったのはソース・仕様・既存テスト定義の調査。本書以外の変更や新UIの実装、実データ再解析、テスト再実行は行っていない。
主要リスクは「予測を出荷提案に見せること」「未確認条件の自動承認」「予測不能を緑扱い」「確認完了と問題解消の混同」「管理画面の見た目だけの権限分離」。上記計画でそれぞれ分離する。
次工程は本書の確認後、Phase 1Aから開始する。
