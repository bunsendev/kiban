# Phase 3I OSS比較キャンペーン

## 目的

同じdataset snapshotで複数のOSSモデルを比較するとき、モデルごとに実験条件、Provider適合試験、
予測runを繰り返し登録する操作を一つにまとめる。学習・予測は従来どおり独立Workerが行い、
HTTP request内では実行しない。

## 操作

1. `/ui/analysis`へANALYZE権限のtokenで接続する。
2. 「比較セットをまとめて開始する」でdataset snapshotを選ぶ。
3. 比較するProvider・モデルを2〜12件選び、目的を入力する。
4. 「選択したモデルをまとめて開始」を押す。
5. キャンペーンカードでモデル別の適合試験と予測runの状態を確認する。
6. 完了後に「完了runを比較対象に入れる」を押し、評価方法と目的を確認して比較結果を作る。

Provider固有の`params`、区間水準、前処理版、seed、資源profile、学習方式には登録済み
`experiment_defaults`を使う。個別条件を変える場合は従来の実験フォームを使用する。

## APIと永続化

`POST /api/comparison-campaigns`は次を受け付ける。

- `request_key`: 利用者が操作ごとに生成する8〜100文字の一意キー
- `snapshot_id`: 全モデルで共有する不変snapshot
- `models`: 重複しないProvider ID・model IDを2〜12件
- `purpose`: 比較目的

APIは内容アドレス方式の実験を保存し、Provider適合試験jobと予測runだけを登録する。
`GET /api/comparison-campaigns`と`GET /api/comparison-campaigns/{id}`は、保存した識別子と現在の
job/run台帳を合成し、`RUNNING`、`COMPLETED`、`NEEDS_ATTENTION`を返す。READ権限で参照し、
ANALYZE権限で登録する。

キャンペーン本体とモデル構成はSQLite/PostgreSQLへ保存し、`request_key`はSHA-256だけを保持する。同一認証subjectと`request_key`の
再送は同じキャンペーンへ収束する。snapshot、目的、モデル構成が異なる再利用は拒否する。
run IDはキャンペーンとProvider・モデルから決定的に生成し、異常終了後の再送でも二重runを
作らない。成功済みまたは処理中の適合試験jobも再利用する。

## 状態と制約

- 全項目で適合試験が成功し、runが`SUCCEEDED`または`PARTIAL`なら`COMPLETED`。
- 適合試験jobが失敗、またはrunが`FAILED`/`CANCELLED`なら`NEEDS_ATTENTION`。
- それ以外は`RUNNING`。画面は5秒間隔で更新する。
- 適合試験の合格可否と正式順位への掲載可否は既存評価台帳の規則を変更しない。
- キャンペーン完了は比較結果の作成や採用判断を意味しない。比較APIで再計算し、採用台帳へ
  担当者判断を別に保存する。
- 人工データでの試験は実データ精度や業務効果を保証しない。

## 検証範囲

API認可、入力制約、未登録snapshot、2モデルの一括登録、再送時の同一キャンペーン・同一run、
一覧・詳細、SQLite外部キー、PostgreSQL schemaと実DB契約、管理画面導線、JavaScript構文を検査する。
