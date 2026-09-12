# Phase 1Y JAN名寄せ・商品マスター画面

Phase 1Yは、Phase 1IのJAN名寄せ候補、canonical product、版付き判断、JAN有効期間をFastAPIと同一originの専用画面`/ui/matching`へ接続する。Phase 1Xで成功した正規化jobを入口にし、候補生成から人による判断、商品台帳への反映までを一つの作業順で扱う。

## 画面への接続

開発環境ではAPIを起動して`http://127.0.0.1:58000/ui/matching`を開く。原本取込・正規化、データ準備、重要品目選定、実データ受入、比較・採用、Lifecycleの各画面へ移動できる。

Bearer tokenは共通JavaScript moduleのメモリ内だけに保持し、URL、cookie、`localStorage`、`sessionStorage`へ保存しない。切断時にtokenと読込済み台帳を画面状態から破棄する。

## 名寄せjob

ANALYZE利用者は、1件以上の成功済み正規化job、policy version、通常類似度、切替候補類似度、最大切替空白日数を指定して名寄せjobを登録する。対象正規化jobは現在採用中の原本に属する必要がある。同じ条件からは同じ内容アドレスIDを生成する。

独立した`kiban-matching-worker`が正規化行から候補を生成する。HTTP request内では候補を計算しない。画面は更新操作でWorkerの処理状態と候補をサーバー台帳から再取得する。

## 候補根拠

候補一覧と詳細には、左右JAN、代表商品名、名称類似度、初回・最終出荷日、併存日数、切替空白日数、単位、center別数量、候補理由を表示する。名称一致は判断材料の一つであり、画面やWorkerが自動的に商品を統合することはない。

候補理由は通常名称類似、名称一致、JAN切替期間の近接を区別する。初回・最終出荷日は観測期間であり、発売日や終売日として扱わない。欠測数量を0へ変換しない。

## 商品と版付き判断

APPROVE利用者は、JANに依存しないcanonical productを作成者、理由とともに登録する。名寄せ候補には次の判断をmapping version、理由付きで追記する。判断者は認証済みsubjectからAPIが確定する。

- `SAME_PRODUCT`: 左右に同じcanonical productを指定する。
- `DIFFERENT_PRODUCT`: 左右に異なるcanonical productを指定する。
- `SUCCESSOR`: 左右に異なるcanonical productを指定し、後継関係として記録する。
- `UNRESOLVED`: productを指定せず、未解決として残す。

過去の判断は上書きしない。同じ候補とmapping versionの再利用、判断種別とproduct IDの不整合、存在しないproductはサーバーが拒否する。`SUCCESSOR`は関係の記録であり、数量系列の自動結合を意味しない。

## JAN有効期間

APPROVE利用者は、JAN、canonical product、開始日、任意の終了日、mapping version、理由を登録する。開始日と終了日は両端を含み、終了未定はNULLとする。同じJAN・mapping versionで重なる期間を拒否し、過去の対応を上書きしない。PostgreSQLでは既存のadvisory lockにより同じJAN・版の同時登録を直列化する。

商品×center取扱期間はPhase 1Uの`/ui/readiness`で扱う。JAN対応表と取扱期間は別の版付き台帳であり、名寄せ判断だけから自動生成しない。

## API

| Method | Path | permission | 用途 |
|---|---|---|---|
| GET | `/api/matching/jobs` | READ | 名寄せjob一覧と候補件数 |
| GET | `/api/matching/jobs/{id}` | READ | 条件、候補、判断材料 |
| POST | `/api/matching/jobs` | ANALYZE | 内容アドレス方式のjob登録 |
| GET/POST | `/api/products` | READ / APPROVE | canonical product台帳 |
| GET/POST | `/api/matching/decisions` | READ / APPROVE | 版付き判断履歴 |
| GET/POST | `/api/jan-mappings` | READ / APPROVE | JAN有効期間台帳 |

画面の選択肢は操作ミスを減らすために絞るが、対象job、product、判断形、期間、版、権限はサーバー台帳が再検証する。動的値はDOMへ`textContent`で設定し、登録後はサーバー台帳を再読込する。

## モジュール境界

| ファイル | 責務 |
|---|---|
| `matching.html` | semantic HTML、登録form、job・候補・商品台帳領域 |
| `matching.css` | JAN名寄せ画面固有layout |
| `matching_api.js` | 一覧・詳細・登録APIのrequest組立て |
| `matching_forms.js` | job、判断、JAN期間入力の契約変換と検証 |
| `matching_render.js` | 候補根拠、数量、判断履歴、商品台帳のDOM生成 |
| `matching_app.js` | state、権限、event、検索、選択、再読込 |

共通の`api.js`はtokenとHTTP、`format.js`は状態・数値表示、`styles.css`は全画面共通デザインを担当する。

## 実行順

1. `/ui/intake`で原本を取込み、現在採用中の原本から正規化jobを成功させる。
2. `/ui/matching`で正規化jobと候補条件を選び、名寄せjobを登録する。
3. matching Workerを実行し、候補根拠と数量を確認する。
4. 必要なcanonical productを登録する。
5. 候補へ版付き判断を記録し、確認済み根拠に基づいてJAN有効期間を登録する。
6. `/ui/readiness`で取扱期間、予定完全性、6種類の日次状態へ進む。

## 未実施事項

リポジトリには実データを置かない。本実装では人工fixtureとPostgreSQL台帳で画面、API、権限、Worker境界を検証する。実業務原本に対する名寄せ判断、JAN有効期間の確定、データ準備、実データ受入は未実施であり、人工データの成功で置き換えない。
