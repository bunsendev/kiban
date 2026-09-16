# Phase 3C 資源・費用管理画面

## 目的

Phase 3Bの資源・費用台帳を、APIを直接操作しない現場担当者が確認できるようにする。
`/ui/resources`でrunを選び、全体集計とorigin・attempt別明細を確認する。ADMINは同じ画面で
Provider共通または個別の単価を登録し、再計算された費用を確認する。

## 操作

1. APIを起動して`http://127.0.0.1:58000/ui/resources`を開く。
2. API tokenを入力する。tokenは画面のメモリ内だけで使用し、保存しない。
3. 左側の一覧をrun ID、モデル、Provider、状態で絞り込み、対象runを選ぶ。
4. 処理時間、CPU・GPU、最大メモリ、保存容量、適用単価と費用を確認する。
5. 必要に応じて「origin・attempt別の計測明細」を開き、再試行を含む記録を確認する。
6. ADMINは「資源単価を登録」を開き、Provider ID、計測項目、単価、通貨、取得日、根拠を登録する。

Provider IDの`*`は全Provider共通単価を表す。個別Providerの単価がある場合はそちらを優先する。
計測済み項目に単価がない場合、画面は0円とせず「単価未登録」と表示する。明示的な0円単価は
0円として表示する。異なる通貨が混在する場合も総費用を確定しない。

## API

- `GET /api/runs?limit=200&status=SUCCEEDED`: run一覧。READ権限が必要。
- `GET /api/runs/{run_id}/resources`: run集計とattempt明細。READ権限が必要。
- `GET /api/resource-unit-prices`: 単価履歴。READ権限が必要。
- `POST /api/resource-unit-prices`: 単価登録。ADMINの`MANAGE_RESOURCE`権限が必要。

run一覧にはProvider IDとモデル名を含む。比較詳細の各runにもPhase 3Bと同じ資源集計を含め、
比較画面では推論時間と総費用を表示する。attempt明細は専用APIだけで返し、比較応答を肥大化させない。

## モジュール構成

- `resource_cost.html`: 画面構造と説明。
- `resource_cost_app.js`: 画面状態、権限制御、操作イベント。
- `resource_cost_api.js`: 資源・費用API呼び出し。
- `resource_cost_render.js`: 一覧、集計、明細、単価履歴の表示。
- `resource_cost.css`: この画面固有のレイアウト。

認証token、共通HTTP処理、OIDC PKCE、共通styleは既存moduleを再利用する。

## 受入条件

- VIEWERを含むREAD利用者がrun一覧、資源集計、attempt明細、単価履歴を参照できる。
- ADMINだけが単価を登録でき、登録者はAPIが認証subjectから確定する。
- 未登録単価と明示的な0円を区別する。
- 比較画面でrun別の推論時間と総費用を確認できる。
- すべての管理画面から資源・費用画面へ移動できる。
- tokenをlocalStorageまたはsessionStorageへ保存しない。
