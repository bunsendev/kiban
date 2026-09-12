# Phase 2B TimesFM運用計測

Phase 2Bは、Phase 2Aで追加したTimesFM 2.5専用Workerの起動前検査とCPU計測を再現可能にする。計測は予測runやAPIから独立した一回実行のCLIで行い、公式checkpoint、人工系列、resource profile、実行環境、測定値、技術判定を内容アドレス方式のJSONへ保存する。

## 運用プロファイル

既定の`cpu-timesfm`は、初期3〜5品目の確認に先立つ最小プロファイルである。

| 項目 | 既定値 |
|---|---:|
| CPU上限 | 2.0 CPU |
| memory上限 | 4 GiB |
| 人工系列数 | 3 |
| context | 512日 |
| horizon | 15日 |
| warm-up | 1回 |
| 計測run | 3回 |
| model初期化上限 | 600秒 |
| 1計測run上限 | 600秒 |
| peak RSS上限 | 4 GiB |

これらはWorkerが指定resource内で動作するかを確認する技術上限であり、本番SLAではない。系列数、horizon、反復回数、上限を変更したレポートは別の`benchmark_id`になる。

## checkpoint配置

取得はネットワーク利用を許可した準備工程だけで行う。実行時は固定revision、`925181104` bytes、SHA-256 `2f776efe6245e42b24bc4153ffdf61810140210e4bd3b01fb21f7aa779ab6ce8`を再検証する。

Windows開発環境では次の例を使う。

```powershell
New-Item -ItemType Directory -Force .\timesfm_checkpoint, .\timesfm_benchmark_output
kiban-timesfm-checkpoint fetch --output .\timesfm_checkpoint
kiban-timesfm-checkpoint verify --output .\timesfm_checkpoint
docker compose --profile timesfm-benchmark run --rm timesfm-benchmark
```

本番LinuxではGit checkout外の運用管理領域を作り、コンテナ実行user `65532`だけがレポートを書けるようにする。checkpointはWorkerからread-onlyである。

```bash
sudo install -d -m 0750 -o root -g 65532 /srv/kiban/timesfm
sudo install -d -m 0750 -o 65532 -g 65532 /srv/kiban/timesfm-benchmarks
export KIBAN_TIMESFM_DIR=/srv/kiban/timesfm
export KIBAN_TIMESFM_BENCHMARK_DIR=/srv/kiban/timesfm-benchmarks
export KIBAN_TIMESFM_CPUS=2.0
export KIBAN_TIMESFM_MEMORY=4G
export KIBAN_TIMESFM_MEMORY_BYTES=4294967296
docker compose -f deploy/compose.production.yaml --profile operations run --rm timesfm-benchmark
```

checkpointの取得後は、所有者をroot、modeを`0440`、groupを専用実行groupへ設定する。秘密情報ではないが、誤更新を防ぐため一般userからwrite不可にする。

## 計測と判定

CLIは次を順に実行する。

1. checkpointの存在、file名、size、SHA-256、実行processからwrite不可であることを検証する。失敗時はmodelをロードしない。
2. process内model cacheを空にし、モデルロードとcompileを初期化時間として測る。
3. 決定的な週周期付き人工系列を生成し、warm-upを計測対象から分離する。
4. 同じ入力を3回推論し、wall time、CPU time、p50相当のmedian、nearest-rank p95、最大値を記録する。
5. Linux `getrusage`のprocess peak RSSとcgroup v1/v2のCPU・memory上限を取得する。
6. checkpointの固定値と実効read-only、有限出力、時間、peak RSS、cgroup隔離の8項目を判定する。

全項目が`PASSED`の場合だけCLIは終了code 0を返す。失敗時も測定が完了していれば不変レポートを発行し、終了code 2を返す。checkpointの固定値・権限検証やモデルロード自体が失敗した場合はレポートを作らず終了する。

レポートは`timesfm-benchmarks/<report_sha256>.json`へatomicに保存する。固定のweights ID、SHA-256、sizeは含むが、checkpointのローカルpath、重み、PyTorch object、入力系列、予測値は含めない。出力領域はGit、Docker build context、配布ZIPから除外する。benchmark serviceは`network_mode: none`で動作する。

## 制約

この計測は人工系列と公式checkpointによる専用Workerの技術確認である。実データの予測精度、業務効果、同時実行時の容量、本番SLAを評価しない。実データ評価はPhase 1Xから原本を取り込み、Phase 1Kの受入と保存済みrun比較で別に行う。
