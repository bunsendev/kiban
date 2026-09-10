# Phase 1N 実装計画

## ゴール

保存済みrunとdataset snapshotから比較結果をサーバー側で再計算し、比較条件、共通集合ID、run別件数・精度を不変な記録としてSQLite/PostgreSQLへ保存する。Provider適合試験はモデル・ライブラリ・実行環境・項目別証跡を完全識別して保存し、Provider一覧から固定条件ランキング掲載可否を確認できるようにする。

## モジュール境界

`evaluation_registry/contracts.py`は永続オブジェクト、`domain.py`は内容アドレスIDと適合判定、`service.py`はrun・catalog・snapshot・既存評価関数の組合せ、`store.py`と`postgres_store.py`はDB差分、`api/evaluation_routes.py`と`evaluation_schemas.py`はHTTP契約を担当する。予測Provider、runner、評価計算本体へDB処理を追加しない。

## 実装範囲

1. `provider_conformance_tests`へProvider/model/library、設定、環境、実施者・日時、7項目の結果と証跡を保存する。
2. 固定パラメータ不変、履歴反映、未来非参照、出力完全性、再現性、失敗通知、TRAIN境界の全項目合格とProvider能力宣言から掲載可否を導出する。
3. `POST /api/comparisons`はrun IDだけを受け、保存済み予測とchecksum検証済みsnapshotのTEST実績から既存`compare_runs`を実行する。
4. 比較条件、truth版、evaluation scope hash、comparison set ID、official comparison set ID、run別件数・metricsを不変保存する。
5. 不完全runは失敗率とown metricsを残し、完全runだけのofficial集合を既存評価規則どおり維持する。
6. 違うsnapshot・評価scope、非終端run、truth snapshot不一致、改変snapshot、重複runを拒否する。
7. Provider一覧、適合記録一覧・詳細、比較詳細のBearer認証付きAPIを追加する。
8. SQLite/PostgreSQL、API、同内容再登録、改変拒否、baselineとAutoETSの比較を検証する。

## 完了条件

- クライアントが予測値・metrics・掲載可否を直接登録できない。
- 同じ条件と入力は同じcomparison IDになり、既存記録を変更しない。
- comparison set IDとofficial comparison set IDを混同せず保存・取得できる。
- 適合項目に失敗があれば固定ランキング掲載可否はfalseになる。
- Provider・モデル・ライブラリ版または試験suite版変更時は別適合記録になる。
- PostgreSQL実DBを含むpytest、ruff、Docker、wheel、配布checksumが合格する。

## 対象外

比較jobの非同期Worker化、実測時間・CPU・メモリ・費用収集、実データ精度評価、採用承認、UI、月次再学習、MLForecast、TimesFM、本番role/TLS/監視。
