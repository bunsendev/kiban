# Windows Portable Production Forecast Run受渡し 実装結果

## ゴール

担当者が承認したPortableの日次buildを、予測基盤で既に使っているDataset Snapshot、
Experiment、Forecast Run queueへ安全に登録する。Portable独自の予測台帳は増やさない。

## 実装した境界

`POST /api/formal-forecast/{build_id}/production-run` は登録者、理由、明示確認を受け、
次を順に行う。

1. `manifest.json` と `daily.csv` のbuild ID・状態・SHA-256を再検証する。
2. `forecast_eligible=true` の系列を既存日次CSV契約へ変換する。
3. 内容アドレスのDataset Snapshotを既存Catalogへ登録する。
4. `builtin-baseline/seasonal_naive_7` のExperimentを登録する。
5. build IDから決定したRun IDで既存Forecast Run queueへ登録する。
6. 対象系列と確認待ち・隔離系列を分けた受渡し記録をSHA-256付きで保存する。

同じbuildの再送は同じSnapshot、Experiment、Run、受渡し記録へ収束する。確認待ち・
隔離系列は予測入力へ混ぜないが、受渡し記録の`blocked_series`から失われない。

## 安全条件

- 改変された日次CSVまたは受渡し記録は拒否する。
- `MISSING`と`PARTIAL_OR_INVALID`は0へ変換しない。
- Portableで予測対象が0系列の場合はRunを登録しない。
- API要求内では学習・予測を実行せず、既存Worker queueへ登録する。
- 現場の実データ、APIキー、個人情報はRepositoryへ保存しない。

## API

- `GET /api/formal-forecast/{build_id}/production-run`: 登録前確認または登録済み受渡し記録
- `POST /api/formal-forecast/{build_id}/production-run`: Production queue登録

POST本文例:

```json
{
  "actor": "運用管理者",
  "reason": "日次予測更新",
  "confirm_production_queue": true
}
```

## テスト

- 承認済み10系列を既存Run queueへ登録できる。
- 再送しても同じRunへ収束する。
- 9系列を登録し、欠測1系列を受渡し記録へ保持する。
- 受渡し記録の改変を拒否する。

## 次の接続

既存のProvider別WorkerがQUEUED Runを処理する。次工程では担当者画面に登録確認と
Run進捗を表示し、完了したPOINT予測をWarehouse Projectionへ接続する。
