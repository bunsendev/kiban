# Phase 2A TimesFM 2.5 Provider

Phase 2AはApache-2.0のTimesFM 2.5 200Mを、builtin baseline、StatsForecast AutoETS、MLForecast Ridgeに続く4つ目の予測Providerとして追加する。Provider IDは`timesfm-2p5`、モデルIDは`timesfm_2p5_200m_zero_shot`である。TimesFM 3.0の重みは非商用・非本番用途に制限されるため、この実装では取得も使用もしない。

## 固定条件

実験定義は次の値を必須とする。

```json
{
  "provider_id": "timesfm-2p5",
  "model_name": "timesfm_2p5_200m_zero_shot",
  "params": {
    "max_context": 512,
    "max_horizon": 400,
    "normalize_inputs": true,
    "force_flip_invariance": true
  },
  "interval_levels": [],
  "preprocessing_version": "timesfm-causal-ffill-context512-v1"
}
```

最小履歴は実観測64日かつ補完後64日である。学習処理は行わず、固定重みを起点以前の最大512日へ適用する。初期範囲はPOINT予測だけで、外生変数は使用しない。出荷数量の契約に合わせ、負のraw予測は`yhat_raw`へ維持し、`yhat`だけを0へ丸める。

## checkpoint契約

使用する重みは次へ固定する。

- repository: `google/timesfm-2.5-200m-pytorch`
- revision: `1d952420fba87f3c6dee4f240de0f1a0fbc790e3`
- file: `model.safetensors`
- size: `925181104` bytes
- SHA-256: `2f776efe6245e42b24bc4153ffdf61810140210e4bd3b01fb21f7aa779ab6ce8`

Providerとruntimeはローカルfileしか受け付けず、実行時にHugging Faceへ接続しない。運用者はネットワーク利用を許可した準備工程でだけ、次を実行する。

```powershell
kiban-timesfm-checkpoint fetch --output timesfm_checkpoint
kiban-timesfm-checkpoint verify --output timesfm_checkpoint
```

`timesfm_checkpoint`はGitと配布ZIPから除外する。本番では別の管理領域へ取得し、専用Workerへread-only volumeとしてmountする。artifactには重み、ローカルpath、PyTorch objectを含めず、固定weights ID、checksum、sizeだけを保存する。

## 実行境界

基本のAPI imageには`timesfm`の軽量なmetadata/runtime定義を含めるが、PyTorchは導入しない。CPU PyTorchはbuild argを有効にしたTimesFM専用Workerだけに導入する。

```powershell
docker compose --profile timesfm-worker up -d --build timesfm-worker
```

ホストで実行する場合は`requirements-timesfm-torch.txt`を追加導入し、`KIBAN_TIMESFM_CHECKPOINT`に検証済みfileまたは格納directoryを指定する。

```powershell
python -m pip install -r requirements-timesfm-torch.txt
$env:KIBAN_TIMESFM_CHECKPOINT = "C:\secure\timesfm\model.safetensors"
kiban-worker --postgres-dsn <DSN> --timesfm-2p5 --artifact-root <DIR> --work-root <DIR> --worker-id <ID>
```

## 検証範囲

人工データで固定設定、checkpoint拒否、因果的補完、未来非参照、POINT出力、JSON保存・復元、artifact改ざん拒否、共通runner、APIからWorker entry pointまでを検証する。実checkpoint smoke testは固定重みとPyTorchを用意した環境で明示的に実行する。この試験は実データでの精度、処理時間、業務効果を保証しない。
