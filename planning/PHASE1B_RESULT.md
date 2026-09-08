# Phase 1B 実装結果

## ゴールと結果

ModelRef/ContextRefの版付き保存契約、差し替え可能な保存先、ローカル保存、baseline state変換、checksum・条件検証、別プロセス予測再現を一つのPhaseとして実装した。Phase 1Aは維持し、DB/API/UI、Workerジョブ再開、分散実行、自動再試行には進んでいない。

## 構成

| モジュール | 役割 |
|---|---|
| artifacts/contracts.py | ArtifactRef、保存先・Codec Protocol、例外 |
| artifacts/json_format.py | 厳密JSON、日時・数値・配列の検証 |
| artifacts/metadata.py | ModelRef/ContextRefメタデータ変換 |
| artifacts/local.py | 内容アドレス方式の原子的ローカル保存 |
| artifacts/repository.py | 保存・復元の条件と親子参照の照合 |
| providers/baseline_series.py | 日次Series、NaN/0の変換 |
| providers/baseline_codec.py | TRAIN系列、残差、起点履歴の変換・検証 |
| artifact_demo.py | 親プロセスで保存し、子プロセスで再現 |

共通保存層は個別Providerを参照せずCodecを注入する。保存I/OもArtifactStoreで差し替える。新規実装は責務別に8ファイルへ分け、最大はrepository.pyの172行。既存runner、予測式、評価式、Providerの6メソッドは変更していない。

## 保存契約

- format_version=1、baseline codec_version=1の厳密なUTF-8 JSON。
- ArtifactRefはSHA-256とsize。モデルとcontextを別々に内容アドレスで参照。
- contextは正確なmodel artifact、model_id、run/experiment、origin、cutoffへ結び付ける。
- parameter_fingerprintを現在のdataset/config/provider環境から再計算して照合。
- baselineのTRAIN系列・残差・除外系列・起点履歴を保存。NaNはnull、0は0.0。
- 復元したModelRefのartifact_uriはsha256:<digest>。元参照は変更しない。
- pickleや任意コード実行形式を使用しない。

## ローカル保存

- 一時ファイルをflush/fsync後、hard linkで排他的に公開。既存artifactを上書きしない。
- 同じ内容の同時保存は同一参照。破損済みの同名artifactは上書き修復せず拒否。
- 読込みは既定256 MiB上限、sizeとSHA-256を検証。
- 一時ファイル、artifact_output、build/dist、生成ZIPはGit・配布対象外。

## 検証

- pytest: 250 passed（Phase 1Aの190件＋Phase 1Bの60件）。
- ruff: All checks passed。
- demo: 7ファイルが変更前とバイト単位で一致。
- scale_check: 37起点、POINT 54,500行、総行218,000、365日/系列、重複0。
- artifact_demo: 別プロセスで再fit・残差再計算なしに24行のPOINT/QUANTILEが完全一致。
- 4つのbaselineをASSUMED/OBSERVEDで保存・復元。OBSERVED区間非対応の既存契約は維持。
- checksum再計算済みの改変でも、版・Provider・fingerprint・seed・run・系列・日付・残差・親モデルの不一致を拒否。
- 同時保存、途中失敗、破損、切詰め、過大サイズ、欠落、重複JSONキー、非有限値を検証。
- 配布ハッシュは最終記録保存後に再生成し、56/56一致。

## 互換性

既存のインメモリAPIとimportは変更なし。保存機能は明示的にRepositoryを生成して使用する。Phase 1A以前の独自保存物を読むmigrationはない。保存物を復元するには同じ学習条件・run情報が必要。Provider・ライブラリ・Python版が変わるとfingerprintが変わるため、意図しない環境差で復元しない。

## 未対応と残課題

- ArtifactRefのDB保存、runからの追跡、アクセス制御、backup/restore運用。
- Workerの完了起点、再開・二重出力防止、キャンセル、timeout、retry、分散実行。
- クラウド/ネットワーク保存。ローカル実装はhard link対応の信頼された領域が対象。
- 署名と発行元認証。checksumは与えられた参照との内容一致のみを保証する。
- 原本・feature版・snapshot本体の保存、実データ検証、追加OSS。

Phase 1Bの次は、run/起点/予定/予測/失敗/artifact参照を一貫して保存するDB境界と、完了済み起点を安全に再利用するWorker再開契約をまとめるのが適切。ただしPhase 1Bのレビュー前には進めない。
