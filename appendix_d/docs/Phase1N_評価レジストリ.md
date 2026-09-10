# Phase 1N Provider適合試験と比較結果の永続化

Phase 1Nは、保存済みrunからサーバーが再計算した比較結果とProvider適合試験を、不変な評価記録としてSQLite/PostgreSQLへ保存する。クライアントは予測値、精度指標、正式ランキング掲載可否を登録できない。

## モジュール境界

| モジュール | 責務 |
|---|---|
| `evaluation_registry/contracts.py` | 適合記録、比較記録、run評価、Store Protocol |
| `evaluation_registry/domain.py` | 7項目の適合判定、内容アドレスID、JSON正規化 |
| `evaluation_registry/service.py` | run・experiment・snapshotの照合、truth読込、既存評価関数の実行 |
| `evaluation_registry/store.py` | SQLiteの不変保存と検索 |
| `evaluation_registry/postgres_store.py` | PostgreSQL接続差分 |
| `api/evaluation_schemas.py` | 外部から受け付ける適合条件と比較条件 |
| `api/evaluation_routes.py` | Bearer認証付きHTTP操作 |

予測Provider、runner、評価式はDBへ依存しない。`compare_runs`には適合済みrun集合を任意に渡せる境界だけを追加し、未指定時の既存挙動を維持する。

## Provider適合記録

`POST /api/provider-conformance-tests`は、登録中ProviderのID・版、モデル、ライブラリ、adapter設定、Python・platform・依存版、試験suite版、実施者・日時、項目別証跡を受け付ける。固定条件の試験項目は次の7件で、重複や不足を拒否する。

1. `TRAIN_BOUNDARY`
2. `PARAMETER_IMMUTABILITY`
3. `CONTEXT_REFRESH`
4. `FUTURE_NON_REFERENCE`
5. `OUTPUT_COMPLETENESS`
6. `REPRODUCIBILITY`
7. `FAILURE_NOTIFICATION`

全項目が`PASSED`であり、Providerの能力宣言がcontext更新を行いパラメータ再学習を要求せず、対象モデルがprimaryの場合だけ`fixed_ranking_eligible=true`となる。判定値は入力できず、サーバーが導出する。条件全体のSHA-256から`conformance_id`を作るため、同じ記録の再送は同じIDになり、既存内容を変更しない。

`GET /api/providers`はregistryの能力宣言と各モデルの最新適合記録を返す。履歴は`GET /api/provider-conformance-tests`、詳細は`GET /api/provider-conformance-tests/{id}`で取得する。

## 保存済みrunの比較

`POST /api/comparisons`の入力はrun ID、各runのconformance ID、truth snapshot ID、mode/horizon、評価policy版、依頼者、目的に限定する。サービスは次を検査してから既存`compare_runs`を呼ぶ。

- runが`SUCCEEDED`、`PARTIAL`、`FAILED`のいずれかである。
- 全runが指定されたtruth snapshotと同じdataset snapshotを参照する。
- conformanceがrunのProvider、model、params、interval levels、前処理版と一致する。
- snapshotファイルのSHA-256がcatalog記録と一致する。
- datasetの評価scopeが一致し、通期比較では運用profileも一致する。

truthはsnapshotの`unique_id / ds / y`から読み、`MISSING / NOT_HANDLED / CLOSED / PARTIAL_OR_INVALID`の日次状態は欠測として扱う。予測はrun台帳の保存値から復元する。比較結果には全run共通の`comparison_set_id`と、適合済みかつ完全なrunだけの`official_comparison_set_id`を別々に保存する。

不完全または適合未通過のrunも`own_metrics`、`common_metrics`、成功・失敗件数とともに残す。`incomplete_runs`は予測不足のrun、`official_excluded_runs`は予測不足または適合未通過で正式集合に入らないrunを表す。適合済みrunが1件だけなら単独評価であり、`official_ranking_ready=false`となる。

比較条件のSHA-256から`comparison_id`を作る。同じ条件の再送は保存済み結果を返し、run評価を上書きしない。詳細は`GET /api/comparisons/{id}`、履歴は`GET /api/comparisons`、run単位の絞込みは`GET /api/comparisons?run_id={run_id}`で取得する。

## API入力例

```json
{
  "run_ids": ["RUN_A", "RUN_B"],
  "conformance_ids": {
    "RUN_A": "conformance-...",
    "RUN_B": "conformance-..."
  },
  "truth_snapshot_id": "SNAPSHOT_ID",
  "mode": "horizon",
  "horizon": 7,
  "policy_version": "evaluation-v2.9",
  "requested_by": "analyst@example.test",
  "purpose": "baselineとAutoETSの固定条件比較"
}
```

## 検証範囲

人工データで、2つの完了runの比較、同内容再送、不適合runの正式集合除外、クライアント指標の拒否、adapter条件不一致、非終端run、snapshot改変、Provider一覧、SQLite/PostgreSQL保存を検証する。人工データ結果は実データ精度や業務効果を示さない。非同期比較Worker、実測時間・CPU・メモリ・費用、採用承認、UIは対象外である。
