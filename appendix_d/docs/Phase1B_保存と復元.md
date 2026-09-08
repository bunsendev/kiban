# Phase 1B 保存と復元

目的は、ModelRefとContextRefを保存し、別プロセスで復元した予測を保存前と一致させること。
Phase 1Aの190テストを維持し、Providerの6メソッド、runner、予測式、評価式を変更しない。
パッケージ版は2.9.0のまま、保存形式のformat_versionとCodecのcodec_versionを独立管理する。

## 責務分割

| モジュール | 責務 |
|---|---|
| artifacts/contracts.py | ArtifactRef、ArtifactStore、StateCodec、例外 |
| artifacts/json_format.py | 厳密なJSONと日付・時刻・数値の検証 |
| artifacts/metadata.py | ModelRef/ContextRefのメタデータ変換 |
| artifacts/local.py | ローカルファイルの排他的公開と読込み |
| artifacts/repository.py | 保存/復元時の条件と参照関係の照合 |
| providers/baseline_series.py | 日次Seriesと欠損値の変換 |
| providers/baseline_codec.py | baselineの学習state・残差・contextの変換 |

共通保存層はbaselineをimportしない。新しいProviderはStateCodec、別の保存先はArtifactStoreを実装して注入する。
DBやクラウド製品への依存、pickleによるPythonオブジェクト復元は持たない。

## 保存形式

ArtifactRefはsha256（小文字64桁）とsize_bytes（正整数）の変更不能な参照。
to_dict/from_dictでJSONに記録できる。モデルとcontextそれぞれの参照を呼出側で保存する。
ローカルの保存名は<sha256>.json。run名・商品名・任意パスをファイル名に使用しない。

JSONはUTF-8、キー整列、厳密な有限数、format_version=1。
ルートはformat_version/kind/codec_version/provider_id/binding/metadata/state/model_artifactで構成する。
kindはmodelまたはcontext、baseline codec_version=1。未対応版・余分/欠落フィールド・重複JSONキーを拒否する。
bindingはrun_id/experiment_id。contextのmodel_artifactには保存モデルのArtifactRefを埋め込み、正確な保存内容へ結び付ける。

ModelRefの全識別項目と学習範囲・fitted_atを保存する。artifact_uriは保存物自身から導出するためJSONに含めず、復元時にsha256:<digest>を設定する。
これはArtifactStore内の内容参照であり、外部URLではない。元のModelRefは変更しない。
weights_id=Noneは引き続き「外部の学習済み重み非該当」。今回保存するTRAIN系列・残差はbaselineの実在する学習stateである。

日時はUTCのtimezone付きISO表現、日付はYYYY-MM-DD。復元後のcutoffは元のJST表現と同じ実時刻になる。
Seriesは開始日・値配列・系列名・index名を保存し、連続した日次float64へ復元する。
NaNはJSON null、確定0は0.0として区別する。非連続・日中・timezone付き日次index、負数量、無限大、bool数量は拒否する。
残差は[horizon, quantile, correction]の配列。負の補正値は有効、非有限値・重複・要求外horizon/quantile・分位の部分欠落は拒否する。
学習対象・除外対象系列、最小履歴、TRAIN範囲、history_end上限も検証する。

## 保存と復元のAPI

```python
from pathlib import Path
from forecast_provider.artifacts import ForecastArtifactRepository, LocalArtifactStore
from forecast_provider.providers.baseline_codec import BuiltinBaselineCodec

repository = ForecastArtifactRepository(
    LocalArtifactStore(Path("artifact_output/objects")),
    [BuiltinBaselineCodec()],
)
fit_context = parent.for_origin(dataset.train_end)
origin_context = parent.for_origin(origin_date)

# fit/refresh済みの参照を保存する。
model_artifact = repository.save_model(model, dataset, config, fit_context)
context_artifact = repository.save_context(
    context_ref, model_artifact, dataset, config, origin_context,
)

# 別プロセスでも同じdataset/config/run情報とArtifactRefを指定する。
loaded_model = repository.load_model(model_artifact, dataset, config, fit_context)
loaded_context = repository.load_context(
    context_artifact, model_artifact, dataset, config, origin_context,
)
predictions = provider.predict(loaded_model, loaded_context, future, horizons, origin_context)
```

復元時は、保存元と同じdataset・config・run/experiment・seed・利用可能条件を渡す。
現在のProviderメタデータと設定からparameter_fingerprintを再計算し、保存値と比較する。
そのためsnapshot/selection・前処理・TRAIN・対象系列・区間・依存/Python版が異なれば復元を拒否する。
保存したModelRefのmodel_id、ContextRefのcontext_idも維持する。
contextはmodel artifact、model_id、origin、cutoff、history_endを照合する。
context保存/復元時にも保存モデルを検証・復元し、呼出側の別モデルを誤って使用しない。

## ローカル保存の保証と限界

一時ファイルへ全内容を書き、flush/fsync後に同一ファイルシステムのhard linkで公開する。
既存ファイルを置換しないため、同時に同じ内容を保存しても同じArtifactRefになる。
既存内容が破損していれば上書き修復せず拒否する。例外時は作成した一時ファイルを削除する。
プロセス強制終了で.pending-*が残っても、ArtifactRefからは読まない。自動削除・GCは対象外。
読込み時はサイズ上限とsha256を検証し、保存先を差し替えた場合もRepository側で再検証する。
既定上限は1 artifactあたり256 MiB。LocalArtifactStoreのmax_bytesで設定できる。

対象はhard link対応の信頼されたローカル保存領域（今回の検証はWindows/NTFS）。
非対応ファイルシステムでは保存エラーとなる。クラウド同期・ネットワークFS・電源断時の耐久性・複数ホスト運用は検証対象外。
checksumは与えられたArtifactRefとの内容一致を保証するもので、署名や発行元の認証ではない。
参照自身の保管・runからの追跡・アクセス制御は呼出側、将来DB/Workerの責務。

形式・checksum・参照/条件不一致はArtifactError（ContractViolationErrorの派生）、I/O障害はArtifactStorageErrorで送出する。
通常の欠測やFAILED予測へ変換せず、自動再試行しない。

## 実行確認

```text
python artifact_demo.py verify --output artifact_output
```

親プロセスで人工データから保存し、子プロセスでモデル/履歴を復元して24行のPOINT/QUANTILEを完全一致で照合する。
saveとrestoreを別々に実行してもよい。テストでは子プロセスのfitと残差再計算を禁止して復元のみで成立することを確認する。
既定のartifact_output、wheel生成時のbuild/distはGitと配布ZIPから除外する。別名の保存先を使う場合はソース配布ディレクトリの外を指定する。

## 完成範囲

v2.9第11章のModelRef/ContextRefのローカル永続化・復元・artifact checksumに対応する。
v2.2 §10/13/14の成果物追跡・再現性に必要な保存契約を提供するが、DBのrun台帳・ジョブ再開は完成していない。
原本・将来変数・snapshotそのものは保存しない。期待条件を呼出側から受け取る。
Workerの完了起点管理、再開時の二重出力防止、キャンセル、強制timeout、retry、クラウド保存は次の段階。
既存インメモリAPIは互換。Phase 1A以前の独自保存物を自動変換するmigrationはない。
