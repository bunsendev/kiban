# Phase 2A 実装計画

## ゴール

Apache-2.0で利用できるTimesFM 2.5 200Mを4つ目の予測Providerとして追加する。固定revisionとSHA-256で検証したローカル重みだけをzero-shot推論へ使い、APIと通常Workerから大容量PyTorchランタイムを分離する。

## 実装範囲

1. `timesfm==3.0.2`の`TimesFM_2p5_200M_torch`を固定設定で呼び出す。
2. checkpointのrepository、revision、file名、size、SHA-256を固定し、実行時ダウンロードを禁止する。
3. 因果的な日次前方補完後の最大512日をcontextとし、horizon 1〜400のPOINT予測を返す。
4. Provider、checkpoint検証、runtime、artifact codec、executorを別moduleにする。
5. 重みやpathをartifactへ保存せず、固定識別子とchecksumだけをJSONへ保存する。
6. PyTorch CPU依存をTimesFM専用Docker Workerだけへ導入し、開発・本番Composeへ接続する。
7. registry、共通runner、独立Worker、仕様書、テスト、wheel、配布checksumを更新する。

## 完了条件

- checkpointがない場合、またはsize・SHA-256が違う場合は推論前に停止する。
- checkpoint取得は運用者の明示CLIだけが行い、Provider/runtimeはネットワークへ接続しない。
- TRAIN外と起点より未来の実績を参照しない。
- JSON artifactから再fitなしで同じ予測を再現し、改ざんを拒否する。
- API imageはPyTorchを含まず、専用WorkerだけがCPU PyTorchと重みvolumeを使う。
- pytest、ruff、Docker、PostgreSQL、wheel、配布checksumが成功する。
- TimesFM 3.0重みは非商用ライセンスのため対象外と明記する。
- 人工データ・smoke testを実データ精度や業務効果の保証に使わない。
