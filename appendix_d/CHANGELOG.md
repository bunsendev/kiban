# v2.9 修正記録

## Phase 3S-8

- 全行が`確認済み`のJAN対応CSVだけを受け付けるInventory Foundation用adapterを追加。
- 商品コード→JANを内容hashで版管理する追記型台帳をSQLite/PostgreSQL共通schemaへ追加。
- canonical商品が未接続の場合はNULLのまま保持し、架空のcanonical商品IDを生成しない。
- Inventory Snapshot Workerが入力mappingのproduct mapping versionから正式対応表を自動読込。
- 対応表の登録CLIを追加し、CSVの行順や商品名変更に左右されない決定的versionを生成。

## Phase 3S-7

- 出荷の商品コード→JANを優先し、在庫の商品名variantと出荷JANも使って一意・複数候補・候補なしを分類する確認支援moduleを追加。
- 一意JANを確認用CSVへ事前記入し、複数候補は選択せず候補一覧を確認メモへ提示。
- 全商品で確認メモが`確認済み`になるまで、正式な商品コード→JAN対応表の保存を拒否。
- 固定byte境界でCP932文字が分断される文字コード判定を、完全なCSV行単位の共通処理へ変更。
- 実データを保存せず、147商品を一意130・複数候補15・候補なし2へ再現できることを確認。

## Phase 3R

- 追加テストの元キャンペーンと完了キャンペーンから、保存済み公式結果を1件ずつ取得する契約を追加。
- provider・model単位でWAPE、MAE、RMSE、絶対Bias、成功率、順位の元値・追加値・差分を表示。
- WAPE低下・上昇・同値・正式比較不能を事実判定として分離し、欠損値と0を維持。
- 分析画面にモデル別差分表と、対象モデルの差分を新しい判断版フォームへ引き継ぐ操作を追加。
- 採否・昇格は自動変更せず、利用者が判断内容を確認して版付きレビューへ記録する契約を維持。
- 指定キャンペーン結果、純粋差分集計、画面描画を独立moduleへ分割。

## Phase 3Q

- `RETEST`対応タスクから、元レビューと同じモデル集合・評価方法の比較キャンペーンを再登録できるようにした。
- 検証データセットを画面で選び、開始時に対応中の追記イベントとキャンペーンIDを記録。
- request keyと期待revisionにより、API再送、二重キャンペーン、古い画面からの競合更新を拒否。
- 比較成功時はキャンペーンID・比較ID付きで完了し、失敗時は安全な理由付きで保留へ自動反映。
- 比較キャンペーンWorkerの再pollと同一transactionにより、結果同期の取りこぼしと重複履歴を防止。
- link domain、SQLite/PostgreSQL store、service、認可API、画面描画を独立moduleへ分割。

## Phase 3P

- 精度変化レビューに紐づく対応タスクを、種類・件名・担当者・期限付きで登録できるようにした。
- 未着手・対応中・保留・完了・中止、担当者、期限、記録内容をrevision付きイベントとして追記保存。
- 完了根拠なしの完了、完了・中止後の変更、古いrevisionによる同時更新を拒否。
- 未完了の期限超過を現在状態から算出し、分析実行画面にタスクと全変更履歴を表示。
- SQLite/PostgreSQL store、domain、service、認可API、画面描画を独立moduleへ分割。

## Phase 3O

- 同一条件の精度変化に対する確認中・データ要因・業務要因・モデル要因・問題なしの版付きレビュー台帳を追加。
- 判断時点の直前・最新指標をcanonical JSONとSHA-256で固定し、判断版の上書きを拒否。
- REVIEW登録をAPPROVE、履歴参照をREAD権限へ分離し、認証subjectを記録者として固定。
- 分析実行画面へ調査・判断フォームと根拠・対応・記録者を含む履歴を追加。
- 台帳、照合service、API、画面描画を独立moduleへ分割。

## Phase 3K

- Windows現場PC向けにBaseline・AutoETS・Ridgeの予測OSS分析環境をワンクリック起動するランチャーを追加。
- CPU、RAM、diskの事前検査と、API readiness・必要service・Provider heartbeatの起動後検査を追加。
- データ準備、適合試験、Provider予測、自動比較Workerを標準構成として一括起動。
- TimesFMを標準構成から分離し、RAM総量と現在の空きを確認する明示的な追加ランチャーを追加。
- 停止対象を全管理serviceへ拡張し、状態確認へ不足service、Provider状態、キュー件数を追加。
- 分析専用PowerShell moduleへ処理を分離し、接続codeを状態表示・診断へ出さない契約を維持。
- Docker runtime socketの安全な自動復旧、Windows予約port回避、起動済み構成の再利用を追加。
- PostgreSQLの真偽値型差異と予測Worker volumeの所有者を修正し、非root Workerで実予測を実行可能にした。

## Phase 3J

- 比較キャンペーン登録時に主評価期間または指定horizonと評価policyを固定。
- 全モデル完了後に保存済みrun・適合記録・truth snapshotから比較結果を自動生成する独立Workerを追加。
- 自動比較の待機・実行・成功・失敗、比較ID、失敗理由をSQLite/PostgreSQLへ永続化。
- SQLite排他transactionとPostgreSQL `FOR UPDATE SKIP LOCKED`で並行Workerの二重作成を防止。
- 分析実行画面へ自動比較状態、結果画面への導線、失敗時の再実行を追加。
- 開発・本番Composeへ自動比較Workerを追加し、API・状態遷移・Worker要求の統合試験を追加。

## Phase 3I

- 同一snapshotの2〜12モデルについて、実験・適合試験・予測runを一括登録する比較キャンペーンAPIを追加。
- キャンペーンとモデル別識別子をSQLite/PostgreSQLへ保存し、既存job/run台帳から現在状態を合成。
- 認証subjectとrequest key、snapshot、目的、モデル構成を照合し、再送時の二重runを防止。
- `/ui/analysis`へモデル複数選択、進捗・失敗理由、完了runの比較対象一括設定を追加。
- API認可、入力制約、再送、PostgreSQL schema、管理画面の統合試験を追加。

## Phase 3G

- builtin baselineでOBSERVEDのhistorical originごとに`available_at`締切を再現する残差計算を追加。
- 最終TRAIN締切後の正解値と過去起点で未到着だった履歴を経験残差から除外。
- 4方式のPOINT・区間予測アルゴリズムを専用moduleへ分離し、Provider本体を縮小。
- 分析実行画面でOBSERVED snapshotの区間水準選択を有効化。
- 遅延到着の非遡及、ASSUMEDとの一致、run完走、artifact復元の回帰試験を追加。

## Phase 3F

- Provider WorkerのIDLE・WORKING・current run・開始時刻・heartbeatをSQLite/PostgreSQLへ追加。
- Worker再起動時にinstance IDで旧processの遅延heartbeatを拒否するfencingを追加。
- 長時間の起点処理中もorigin leaseと同じ周期でWorker heartbeatを更新。
- READ APIへProviderごとのWORKING・ONLINE・STALE・NOT_STARTEDと全件キュー集計を追加。
- 分析実行画面へWorker状態、待機・実行中run数、最終応答、状態別の対処案内を追加。

## Phase 3E

- `/ui/analysis`へsnapshot選択、実験作成、run登録・進捗確認、比較作成の案内式画面を追加。
- Provider metadataへ実験既定値を追加し、Provider IDごとの画面分岐を排除。
- snapshotと実験のREAD一覧APIをSQLite/PostgreSQL共通Catalog契約へ追加。
- 同一snapshotと実験条件に完全一致するProvider適合記録だけで比較要求を作成。
- 全管理画面から分析実行画面へ移動できる導線と、Provider Worker待機時の案内を追加。

## Phase 3D

- Provider専用Workerが対象Providerの`QUEUED`・`RUNNING` runだけを取得するよう修正。
- 組込executorのProvider IDをmetadataから固定し、運用引数による上書きを禁止。
- カスタムexecutorへ`--provider-id`を必須化し、全Provider runの誤取得を防止。
- SQLite/PostgreSQLへProvider別runnable run検索の複合索引を追加。
- 別Provider runが待機状態を維持する分離試験とCLI起動拒否試験を追加。

## Phase 3C

- `/ui/resources`へrun別の処理時間、資源、費用、origin・attempt明細を追加。
- ADMINによるProvider共通・個別単価の登録と、取得日・根拠・認証登録者の履歴表示を追加。
- READ権限のrun一覧APIへ状態絞り込み、Provider ID、モデル名を追加。
- 比較詳細へrun別資源集計を追加し、比較画面で推論時間と総費用を表示。
- 未登録単価を0円と区別し、全管理画面から資源・費用画面へ移動可能にした。

## Phase 3A

- 全`POST /api/*`へ任意の`Idempotency-Key`を共通適用し、成功応答の安全な再送を追加。
- 本番PostgreSQL、テスト用SQLite、単一process用メモリ台帳を共通契約で分離。
- HTTP例外、入力検証、内部例外、HTTPS・Host拒否を`code/message/details/request_id`へ統一。
- 入力値、token、Idempotency-Key、要求本文、未知の例外本文をエラー・冪等性台帳へ保存しない。

## Phase 2M

- Windows現場PC向けに、WSL 2とDocker Desktopの検出・導入、環境生成、Compose構築、readiness確認を行う自動セットアップを追加。
- PC固有の64文字接続codeを生成し、Git・配布対象外の`.env`と`.kiban`へ保存。
- 起動、停止、状態確認、診断情報取得を日本語のダブルクリック操作へ分割し、共通処理をPowerShell moduleへ集約。
- デスクトップへ起動・停止・状態確認ショートカットを作成し、通常停止ではPostgreSQL volumeを維持。
- 診断情報から接続code、CSV本文、行値、環境変数、container logを除外。

## Phase 2L

- `/ui/intake`へCSVアップロードを追加し、アップロード、列の対応付け、分析、結果確認を一続きで操作可能にした。
- 100 MB上限、`.csv`限定、安全なファイル名、専用directory、atomic確定、途中ファイル除去を実装した。
- APIとUIは本文や行値を応答・証跡へ含めず、開発Composeの検証Workerは入力rootをread-onlyで参照する。
- 実ブラウザーで合格と隔離の両結果を確認し、原因と修正案まで表示できることを確認した。
- ローカル検証の起動前確認、service起動、結果記録、通常停止・再開、障害確認を運用手順として整理した。

## Phase 2K

- Docker Desktopのstale runtime socketをデータ削除せず退避し、backend、PostgreSQL、API、検証Workerを復旧する手順を追加。
- liveness、readiness、安全なCSV候補、mapping、job、証跡9検査を一続きで確認する実動受入CLIを追加。
- Workerが初回画面更新より先に完了した場合も、ウィザードが判定と修正方法へ自動移動するよう修正。
- PostgreSQL 17実DBとブラウザー操作で、人工CSV 1行の採用、隔離0、`READY_FOR_NORMALIZATION`を確認。

## Phase 2J

- `/ui/intake`の初回データ検証を、CSV選択、列の対応付け、実行の3手順ウィザードへ変更。
- 管理対象入力root内のCSV候補、サイズ、文字コード、ヘッダーだけを返す認証付きAPIを追加。
- CSVヘッダーと対応付けの不足列を実行前に日本語で案内し、不整合な登録を抑止。
- 検証jobを2秒間隔で自動更新し、完了時に判定と検査項目別の修正方法へ自動移動。
- job時刻をUTCオフセット付きで返し、既存PostgreSQL列を`TIMESTAMPTZ`へ安全に移行。
- 履歴は各20件まで表示し、全件数と表示件数を分けて示す。

## Phase 2E

- 全7管理画面にOIDC Authorization Code + PKCE S256ログインを追加。
- state・5分期限・redirect URIを検証し、callback queryを即時消去。
- API側の固定HTTPS endpointでcodeを交換し、refresh token・ID tokenをブラウザーへ返さない境界を追加。
- access tokenは既存のmodule memoryだけで使用し、URL・cookie・local/session storageに保存しない。
- public client設定、code交換、共通PKCE UIを独立moduleに分割。

## Phase 2D

- PostgreSQL custom archiveを内部生成の一時DBへ復元する`kiban-db drill`を追加。
- backup前後の元DB安定性、archive検証、復元、schema・全table内のstreaming指紋一致、一時DB削除を6項目で判定。
- DSN、DB/user名、path、relation名、行値を含まない内容アドレス方式の訓練証跡を追加。
- DB archive、CLI、指紋、一時DB、訓練runner、証跡を独立moduleへ分割。
- 開発・本番Composeのoperations profileにbackup・証跡volumeとread-only実行境界を追加。

## Phase 1R

- 外部IdPのJWT access tokenをJWKS、非対称署名、issuer、audience、時刻claim、role mappingで検証するOIDC modeを追加。
- JWKSの`kid`更新とatomic置換されるcredential JSON fileによる無停止rotation・失効を追加。
- 認証、HTTP security、観測を独立moduleへ分割し、Phase 1Qのimport互換を維持。
- token・body・queryを含めないsubject付き構造化監査log、liveness、readiness、Prometheus形式metricsを追加。
- 全WorkerへPostgreSQL DSN secret file入力を追加し、passwordのcommand line展開を回避。
- Caddy automatic HTTPS、内部network、Docker secret、本番API・全Workerを定義するproduction Composeを追加。
- PostgreSQL 17 custom archive、SHA-256 manifest、検証、復元先DB確認、単一transaction restore CLIを追加。

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
