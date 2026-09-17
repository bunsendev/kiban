# Phase 3H Provider適合試験の自動実行

## 目的

保存済み実験に一致するProvider適合試験を、分析担当者が`/ui/analysis`から開始できるようにする。HTTP requestはjob登録だけを行い、学習・予測・試験はProvider別の独立Workerが人工データで実行する。結果は既存の不変な評価台帳へ保存し、実験条件と一致する合格記録だけを正式比較に使用する。

人工データ試験は実データの精度、業務効果、実データ受入を保証しない。Provider実装が固定学習比較の技術契約を守ることを確認する試験である。

## 固定7項目

| code | 自動確認する内容 |
|---|---|
| `TRAIN_BOUNDARY` | TRAIN終了翌日の実績を学習入力として拒否する |
| `PARAMETER_IMMUTABILITY` | context更新・予測後も学習時parameter fingerprintを維持する |
| `CONTEXT_REFRESH` | 起点時点までの履歴を新しいContextRefへ反映する |
| `FUTURE_NON_REFERENCE` | 予測対象に混入した未来実績`y`を拒否する |
| `OUTPUT_COMPLETENESS` | 全系列・全horizonのPOINTと要求quantile、固定列、キー、有限値を満たす |
| `REPRODUCIBILITY` | 同じモデル・context・入力の2回予測が完全一致する |
| `FAILURE_NOTIFICATION` | 不正horizonを`ContractViolationError`として通知する |

試験系列は2系列、履歴はモデルの最小履歴以上かつ420日、horizonは最大15日である。実験と同じmodel、params、interval levels、前処理版、seed、resource profileと、snapshotのavailability modeを使う。実データやsnapshot CSVは読み込まない。

## jobと証跡

`POST /api/provider-conformance-jobs`へ`experiment_id`を渡すと、認証subject付きの`QUEUED` jobを登録する。同じ実験に`QUEUED`または`RUNNING`があれば同じjobを返す。`READ`権限では一覧・詳細、`ANALYZE`権限では登録ができる。

Workerは対象Providerのjobだけを取得する。SQLiteは排他transaction、PostgreSQLは`FOR UPDATE SKIP LOCKED`を使う。完了時は7項目、実行環境、依存版、adapter設定を評価台帳へ登録し、証跡JSONをSHA-256の内容アドレスで`KIBAN_CONFORMANCE_DIR`へ保存する。試験を完了できない場合はjobを`FAILED`とし、固定長のerror codeと操作用メッセージを表示する。失敗jobは画面から再実行できる。

## ローカル起動と操作

Baselineを検証する通常構成は次で起動する。

```powershell
docker compose --profile worker up -d --build postgres api worker provider-conformance-worker
```

StatsForecast、MLForecast、TimesFMを使う場合は対応profileを追加する。

```powershell
docker compose --profile worker --profile statsforecast-worker --profile mlforecast-worker up -d --build
docker compose --profile timesfm-worker up -d --build
```

1. `http://127.0.0.1:58000/ui/analysis`を開き、tokenで接続する。
2. dataset snapshot、Provider、モデルを選び、実験条件を保存する。
3. 保存済み実験の「適合試験を実行」を押す。
4. 「待機」「実行中」の表示が「固定7項目に合格」に変わるまで待つ。
5. 同じ実験の「この条件で実行登録」を押し、run完了後に比較対象へチェックを付ける。
6. 同一snapshotのrunを選び、比較結果を作成する。

OSSモデルを変えるときは手順2でProviderまたはモデルを変え、新しい実験を保存する。適合記録はProviderとライブラリの版、model、params、interval levels、前処理版が完全一致するものだけが自動選択されるため、別モデルや更新前ライブラリの記録は流用されない。比較APIも保存時に現在のProvider metadataと版を再検証する。

## CLI

SQLiteで1回だけ処理する例:

```powershell
kiban-provider-conformance-worker --sqlite .\kiban.sqlite3 --provider-id builtin-baseline --evidence-root .\conformance_output --once
```

1 processで複数のCPU Providerを処理する場合は`--provider-id`を繰り返す。TimesFMは固定checkpointとPyTorchを含む専用imageで分離する。

## 本番構成

`deploy/compose.production.yaml`の`provider-conformance-worker`はBaseline、StatsForecast、MLForecastを処理する。`timesfm-conformance-worker`は固定checkpointをread-onlyでmountし、TimesFMだけを処理する。両serviceは証跡rootだけを書込み可能とし、APIはDBのURIとchecksumを参照する。
