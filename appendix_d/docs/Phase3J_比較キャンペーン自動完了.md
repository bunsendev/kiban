# Phase 3J 比較キャンペーン自動完了

## 目的

OSSモデルの一括登録後に残っていた手動の比較作成をなくす。キャンペーン登録時に評価条件を固定し、
全モデルのProvider適合試験と予測runが完了した時点で、独立Workerが保存済み証跡から比較結果を
生成する。比較結果は自動生成しても、採用・昇格・rollbackの判断は担当者が別に行う。

## 操作

1. `/ui/analysis`へANALYZE権限で接続する。
2. 同じdataset snapshotで比較する2〜12モデルを選ぶ。
3. `主評価期間`または`指定horizon`を選び、キャンペーンを開始する。
4. Provider適合試験Worker、対象Provider Worker、自動比較Workerを起動しておく。
5. キャンペーンカードでモデル別進捗と自動比較状態を確認する。
6. `比較結果作成済み`になったら「比較結果を開く」から指標、系譜、費用を確認する。
7. 失敗した場合は原因を直し、「自動比較を再実行」を押す。

開発Composeは次で必要な共通Workerを起動する。追加Providerはそれぞれのprofileも起動する。

```powershell
docker compose --profile worker up -d --build api worker provider-conformance-worker comparison-campaign-worker
```

## 固定条件と永続化

`POST /api/comparison-campaigns`は従来項目に加えて次を受け付ける。

- `mode`: `primary`または`horizon`。省略時は`primary`。
- `horizon`: horizon評価だけ1〜400を指定する。
- `policy_version`: 省略時は`evaluation-v2.9`。

キャンペーン自動完了台帳は`WAITING`、`RUNNING`、`SUCCEEDED`、`FAILED`を保存する。成功時は
`comparison_id`を保存し、失敗時は500文字以内の安全な理由を保存する。結果導線は
`/ui?comparison_id=<id>`で対象比較を直接選択する。既存のPhase 3I
キャンペーンはschema初期化時に主評価期間・`evaluation-v2.9`の`WAITING`として補完する。

Workerは保存済みrun ID、適合記録ID、truth snapshot、評価方式、policy、依頼者、目的だけから
既存の評価サービスを呼ぶ。評価サービスは予測値と正解snapshotを再読込し、Provider版とadapter
設定の一致を再検査する。比較結果は内容アドレス方式なので、同じ定義の再処理は同じ結果へ収束する。

## 並行制御と復旧

SQLiteは`BEGIN IMMEDIATE`、PostgreSQLは`FOR UPDATE SKIP LOCKED`で1つの待機項目を取得する。
複数Workerが同時に動いても同じキャンペーンを二重取得しない。モデル処理中なら待機へ戻し、別の
キャンペーンが先へ進めるよう最終確認時刻を更新する。適合試験またはrunが失敗した場合と、評価条件
不一致の場合は`FAILED`にする。原因修正後の再実行APIはFAILEDだけをWAITINGへ戻す。

## API

- `GET /api/comparison-campaigns`、`GET /api/comparison-campaigns/{id}`: `finalization`を返す。
- `POST /api/comparison-campaigns/{id}/retry-finalization`: ANALYZE権限で失敗を再実行する。
- `GET /api/comparisons/{comparison_id}`: 自動生成した比較結果の詳細を返す。

## 制約

- HTTP request内では適合試験、予測、比較再計算を実行しない。
- `SUCCEEDED`または`PARTIAL`のrunと成功した適合試験が全モデル分そろうまで比較しない。
- 自動比較成功はモデル採用や業務効果の承認ではない。
- 人工データ試験は実データ精度を保証しない。実データの受入とtrialは別に実施する。
