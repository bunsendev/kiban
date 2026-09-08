# Phase 1B 実装計画

## ゴール

モデルと起点履歴をローカル保存し、プロセス終了後に復元してPOINT/QUANTILEを含む同じ予測を得る。
保存形式・ストレージ・baseline変換・整合性検査・別プロセス試験を一つの成果として実装し、Draft PRでレビューする。

## まとめる範囲

1. 共通: バージョン付きJSON、ArtifactRef（SHA-256とサイズ）、ArtifactStore/StateCodec契約。
2. ローカル: 内容アドレス方式、不完全ファイルを公開しない原子的保存、上書き防止、読込みchecksum検証。
3. baseline: ModelRef/ContextRefのメタデータ、TRAIN系列、残差、起点履歴をJSONへ変換。NaNはnull、有限floatは往復で保持。pickleは使わない。
4. 保存API: モデル・contextの保存/読込み。現在の設定からfingerprint再計算、run/experiment/モデル/起点/締切/形式版を照合。contextは保存モデルのchecksumへ結び付ける。
5. 検証: 既存190テスト維持、保存前後・別Pythonプロセス・四つのbaseline・OBSERVED点予測・NaN・失敗系列・破損/版不一致/別run拒否。
6. 文書・デモ: artifact_demo.pyによる別プロセス再現、移行と制限、実測記録、GitHub PR。

## モジュール境界

artifacts/contracts.py（参照・Protocol）、json_format.py（厳密JSON）、local.py（I/O）、metadata.py（参照メタデータ）、repository.py（ユースケース）。
providers/baseline_codec.pyとbaseline_series.pyへbaseline固有の変換を配置する。
共通保存層は個別Providerをimportせず、Codecを注入する。runner・予測式・評価式は変更しない。

## 完了条件

全回帰・ruff・既存demo/scale・artifact_demo・配布ハッシュ成功。既存デモ7ファイルはBaselineと一致。
checksumと学習条件fingerprintを区別し、基準版の参照を上書きしない。別プロセスで復元した予測は完全一致。

## 今回含めないもの

DB/API/UI、クラウド実装、Workerジョブの再開・完了判定・重複出力制御、強制timeout、分散実行、retry scheduler、実データ受入、追加OSS。
Phase 1Bが提供するのは保存された状態の復元であり、業務ジョブの再開ではない。パッケージ版は2.9.0を維持し、保存形式には独立した版を設ける。
