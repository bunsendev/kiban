# Phase 3O モデル精度変化レビュー

## 目的

Phase 3Nで表示した同一条件の精度変化について、担当者が調査中の状態、原因分類、根拠、
次の対応を版付きで記録する。表示した指標を判断時点の証跡として固定し、後から公式結果の
取得範囲や最新期間が変わっても、何を見て判断したかを再現できるようにする。

## 判断区分

- `INVESTIGATING`: 確認中
- `DATA_ISSUE`: 欠測、mapping、正規化などのデータ要因
- `BUSINESS_EVENT`: 販促、終売、休業などの業務要因
- `MODEL_ISSUE`: モデルまたは学習条件の要因
- `NO_ACTION`: 確認の結果、追加対応なし

区分は原因と対応状況の記録であり、モデルの採用、昇格、rollback、精度合格を実行しない。
判断を変更するときは既存行を更新せず、新しい`decision_version`を追加する。

## 登録条件と証跡

`comparison_profile_id`が現在の公式比較結果に存在し、異なるテスト期間を2件以上持つ場合だけ
登録できる。登録時に認証済み`APPROVE`利用者を記録者として固定し、クライアント指定の担当者は
受け付けない。証跡には次を保存する。

- Provider、モデル、匿名化された比較プロフィールID
- 対象系列数、学習・評価日数、availability、評価方式、予測幅
- 直前・最新のキャンペーン、選定版、期間、WAPE、Bias、成功率、順位
- WAPE、絶対Bias、成功率、順位の差分、期間間隔、Phase 3Nの方向表示

証跡JSONはkey順を固定したcanonical JSONからSHA-256を算出する。対象品目ID、原本値、token、
ローカルpathは保存しない。

## API

- `POST /api/model-drift-reviews`: `APPROVE`権限で版付きレビューを追加
- `GET /api/model-drift-reviews`: `READ`権限で直近200件まで取得
- `comparison_profile_id`指定時はそのプロフィールだけを取得

同じ`comparison_profile_id`と`decision_version`の再登録は409で拒否する。POSTの共通
`Idempotency-Key`再送契約はPhase 3Aに従う。

## 画面

`/ui/analysis`の時系列変化表の下に、比較可能な系列だけを選べる登録フォームと履歴を表示する。
フォームは判断版、判断区分、判断根拠、次の対応を必須とする。履歴にはモデル、最新評価期間、
WAPE変化、判断版、根拠、対応、認証記録者、記録日時を表示する。

## 実装境界

domain、SQLite/PostgreSQL台帳、現在結果との照合serviceは`model_review` package、認可APIは
`api/model_review_routes.py`、画面描画は`analysis_model_reviews.js`へ分離する。公式比較結果、
Phase 3N集計、採用台帳、Lifecycle台帳は変更しない。
