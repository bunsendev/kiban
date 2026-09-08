# Codex 実装指示書 — v2.9 基準版 / Phase 1A

## 0. この指示書の目的

`yosoku_kiban_codex_ready_v2.9.zip` を、今後の開発の基準版として使用する。

このフェーズではDB、API、UI、原本CSV取込、JAN名寄せ、2つ目の予測OSS追加には進まない。

まず `docs/統合仕様_v2.9.md` 第11章に残っている「DB/API/Workerを固定する前に必要な共通Contract」を先に整える。

今回のゴールは、後工程で破壊的なAPI変更が起きにくい状態にすること。

---

# 1. v2.9を基準版として扱う

最初に必ず以下の順で読む。

1. `README.md`
2. `CODEX_START_HERE.md`
3. `docs/統合仕様_v2.9.md`
4. `docs/実装仕様書_v2.2_完全版.md`
5. `forecast_provider/contracts.py`
6. `forecast_provider/runner.py`
7. `forecast_provider/evaluation.py`
8. `forecast_provider/features.py`
9. `tests/`

v2.7 / v2.8の旧差分を優先して解釈しない。

現行の実装契約は `docs/統合仕様_v2.9.md` を正とする。

全体業務要件は `docs/実装仕様書_v2.2_完全版.md` を参照する。

---

# 2. 作業開始前のBaseline確認

コードを変更する前に、現在のv2.9をそのまま検証する。

実行する。

```bash
python -m pytest -q
ruff check .
python demo.py --output demo_output
python scale_check.py
python make_release.py --check
```

期待するBaseline。

```text
pytest:
115 passed

ruff:
All checks passed

make_release --check:
32/32 一致
```

規模確認の基準。

```text
予測起点数              37
通期評価の成立          True
評価プロファイル        (10, 10)
点予測行数（1OSS）      54,500
POINT＋QUANTILE行数     218,000
通期評価 対象日／系列   365
通期評価 重複件数       0
```

上記と異なる場合は、実装へ進まない。

原因を調査し、

- 実行環境
- Python version
- pandas / numpy / pytest / ruff version
- 失敗したテスト
- 差分

を報告して停止する。

Baselineを通すためだけに既存テストを削除、skip、弱体化、期待値変更してはならない。

---

# 3. v2.9で維持する契約

今回の修正で以下を変更しない。

## データ

- 日単位、timezoneなし00:00
- 確定ゼロだけ `0`
- 未観測は `NaN`
- 負数量、bool、inf、NaT、不正重複を拒否
- TRAINの翌日をTEST開始日とする

## 学習・予測

- 現在のrunnerは固定学習方式
- TEST期間でパラメータを再学習しない
- `refresh_context()` は起点までの利用可能履歴だけを使う
- `POINT` と `QUANTILE=0.5` は別物
- `yhat_raw` を保存し、`yhat=max(0,yhat_raw)`
- OBSERVED + baseline区間予測は未対応のまま維持する

## 評価

- 予測前に全予定を固定
- 予測失敗とtruth欠損を分離
- `own_metrics` は自run自身の評価
- `common_metrics` は全run共通集合
- `official_common_metrics` は完全runだけの共通集合
- 不完全run追加で正式比較集合を縮めない
- `comparison_set_id` と `official_comparison_set_id` を混同しない
- 完全run1件は「単独評価」でありランキングではない

## 将来変数

- 固定カレンダーは内部生成
- 変更される将来変数は `known_at` 付き版テーブルから選択
- `known_at <= 起点翌日00:00 JST` の最新版だけを使う
- 最終確定値を直接過去起点へ渡さない

---

# 4. 今回実装する範囲 — Phase 1A

`docs/統合仕様_v2.9.md` 第11章のうち、まず「型・契約・時点情報」を固定する。

このPhaseでは永続DBやWorkerそのものはまだ作らない。

対象は主に以下。

```text
forecast_provider/contracts.py
forecast_provider/runner.py
forecast_provider/errors.py
tests/
docs/統合仕様_v2.9.md
CODEX_START_HERE.md
```

必要な場合のみ小さな補助moduleを追加してよい。

既存のforecast計算ロジックや評価式を不要に書き換えない。

---

# 5. ProviderConfig.preprocessing_version

`ProviderConfig` に前処理の版を明示する。

要件。

```text
preprocessing_version
- 空でない文字列
- 実行中に変更不能
- experiment/runの再現性識別へ使用可能
```

既存の `params` immutable仕様は維持する。

`preprocessing_version` を空文字、None、非文字列で渡した場合は生成時に拒否する。

既存コードへの影響箇所をすべて洗い出してから変更する。

ダミー文字列を自動挿入して契約を満たしたことにしてはならない。

テストfixtureでは明示的な値を設定する。

例：

```text
preprocessing_version="preprocess-v1"
```

名称はv2.2完全仕様に既存定義がある場合、それを優先する。

---

# 6. RunContextへ時点契約を追加

`RunContext` が「このProvider呼出しで何時点までの情報を使用可能か」を表せるようにする。

最低限必要。

```text
availability_mode
cutoff_at
```

## availability_mode

許可値。

```text
ASSUMED
OBSERVED
```

`ForecastDataset.availability_mode` と不一致なら実行前に拒否する。

## cutoff_at

timezone付きdatetimeを必須とする。

JST基準の予測では、

```text
起点日 + 1日 00:00 Asia/Tokyo
```

をその起点の締切とする。

fit時は、

```text
TRAIN_END + 1日 00:00 Asia/Tokyo
```

を使用する。

timezoneなし日時、NaT相当、不正型を受け入れない。

---

# 7. 起点ごとのRunContextを生成する

現在の1つの `RunContext` を全起点へそのまま流用する構造を見直す。

ただし、run_id / experiment_id / seed / input_dir / output_dir / resource_profile / loggerなど、run全体で共有する情報は維持する。

起点ごとに、

```text
origin_date
cutoff_at
availability_mode
```

が一意に決まるcontextをProviderへ渡す。

推奨は、親contextから安全に派生contextを生成するhelperを設けること。

例の考え方：

```text
fit context
    cutoff_at = TRAIN_END翌日00:00 JST

origin context
    cutoff_at = origin翌日00:00 JST
```

具体的な関数名は既存設計に合わせる。

同じ意味の型を複数新設しない。

---

# 8. ContextRef.cutoff_at

`ContextRef` に、そのcontextがどの締切時点の情報を反映したものかを保存する。

最低限、

```text
context_id
model_id
origin_date
history_end
cutoff_at
state
```

を持つ。

Providerが返す `ContextRef.cutoff_at` は、呼出し時の `RunContext.cutoff_at` と一致させる。

predict時に以下を確認する。

```text
ContextRef.model_id == ModelRef.model_id
ContextRef.origin_date == 対象origin
ContextRef.cutoff_at == RunContext.cutoff_at
```

別起点のContextRefを誤って再利用できないようにする。

---

# 9. parameter fingerprint

ModelRefに「何を使って学習したモデルか」を機械的に識別するfingerprintを追加する。

ただし、意味のないUUIDや時刻だけをhashしてはいけない。

fingerprintには、少なくとも以下の再現性条件を含める。

```text
provider_id
provider_version
model_name
ProviderConfig.params
ProviderConfig.interval_levels
preprocessing_version
dataset_snapshot_id
selection_version
availability_mode
TRAIN期間
対象系列集合
seed
```

v2.2完全仕様でさらに必須条件が定義されている場合は追加する。

JSON等へcanonical化してからSHA-256等で決定論的に生成する。

同じ条件なら同じfingerprint。

関連条件が1つ変わればfingerprintも変わることをテストする。

`fitted_at` やrandom UUIDなど、再実行のたびに変わる値をfingerprint材料にしない。

---

# 10. 重み・前処理識別

v2.2完全仕様にある、

```text
ModelRefの重み識別
前処理識別
```

を確認する。

既存用語が仕様書にある場合は、その名前をそのまま採用する。

勝手に似た概念を別名で増やさない。

builtin-baselineには学習済みweight artifactがないため、存在しないartifactを捏造してはいけない。

「該当なし」を正式にどう表現するかを契約で決める。

前処理については `preprocessing_version` と二重管理にならないよう整理する。

実装前にv2.2完全仕様との対応をコメントまたは変更報告に記載する。

---

# 11. failure sinkはInterfaceまで

v2.9ではrunnerが `errors` を返している。

このPhaseではDB保存を実装しない。

ただし将来DB/Workerへ接続できるよう、失敗記録先のinterfaceを定義する。

要件。

- runner内部で特定DB製品へ依存しない
- 失敗recordの型を明確にする
- ProviderError / UNCLASSIFIED_ERROR / ContractViolationErrorの意味を壊さない
- 既存の戻り値 `errors` との意味を変えない
- テスト用のin-memory実装を用意してよい
- DB sinkはまだ作らない

既存runnerのエラー台帳を消さず、移行可能な構造にする。

---

# 12. このPhaseでは永続化を完成させない

次はまだ実装しない。

```text
ModelRef/ContextRefのDB保存
S3 / Blob storage
Worker再開
分散Worker
強制timeout
retry scheduler
本番artifact storage
```

ただし、次Phaseで永続化できなくなる型設計は避ける。

`state` にDataFrame/Series等が入る現行仕様は、このPhaseでは残してよい。

「永続化済み」と誤認させる変更はしない。

---

# 13. 新規テスト

既存115テストはすべて維持する。

最低限以下を追加する。

## ProviderConfig

```text
preprocessing_version正常値 → 成功
空文字 → ValueError
None → ValueError
非文字列 → ValueError
```

## RunContext

```text
availability_mode不正 → 拒否
timezoneなしcutoff_at → 拒否
datasetとのavailability_mode不一致 → ContractViolationError
```

## 起点context

複数originで実行し、

```text
origin A cutoff != origin B cutoff
cutoff = origin翌日00:00 JST
```

を確認する。

fitでは、

```text
cutoff = TRAIN_END翌日00:00 JST
```

を確認する。

## ContextRef

```text
別model_id → 拒否
別origin → 拒否
別cutoff_at → 拒否
```

## parameter fingerprint

```text
同条件で再生成 → 同一

params変更 → 変更
preprocessing_version変更 → 変更
dataset_snapshot_id変更 → 変更
selection_version変更 → 変更
availability_mode変更 → 変更
train期間変更 → 変更
seed変更 → 変更
```

UUIDやfitted_atだけの違いでfingerprintが変わらないことも確認する。

## failure sink

```text
ProviderErrorが記録される
未分類例外が記録される
ContractViolationErrorは通常失敗として飲み込まれない
```

---

# 14. 回帰確認

新規テストだけではなく必ず全テストを実行する。

```bash
python -m pytest -q
ruff check .
python demo.py --output demo_output
python scale_check.py
```

既存v2.9の以下の結果を壊していないこと。

```text
比較集合
known_at版選択
POINT/QUANTILE
予測失敗台帳
own/common/official評価
累計評価
OBSERVED点予測
baseline4方式
```

テストを通すために既存仕様を変更しない。

---

# 15. 文書更新

契約を変更したら、同じ変更単位で以下を更新する。

```text
docs/統合仕様_v2.9.md
CODEX_START_HERE.md
必要なら付録D
tests
```

ただし勝手に「v3.0」などへ版番号を上げない。

版番号を変更すべきと判断した場合は、変更理由を報告し、承認前にversion bumpしない。

`test_results.txt` と `SHA256SUMS.json` は実装レビュー前に書き換えなくてよい。

最終配布版を作る段階で更新する。

---

# 16. 禁止事項

今回以下をしない。

```text
原本CSV取込の実装
JAN名寄せ
DB schema作成
API作成
UI作成
2つ目のOSS追加
月次再学習
Docker/Kubernetes
クラウドストレージ
大規模リファクタリング
評価式変更
既存テスト削除
skip追加での回避
契約違反をNaNやFAILEDへ黙って変換
```

必要性を発見した場合は「次Phase候補」として報告する。

---

# 17. 完了条件

Phase 1Aは以下すべてを満たしたら完了。

```text
1. v2.9既存115テストが維持される
2. preprocessing_versionの契約が入る
3. RunContextにavailability_mode/cutoff_atが入る
4. 各originで個別cutoff_atがProviderへ渡る
5. ContextRefにcutoff_atが保存される
6. 別起点ContextRefの誤用を検出できる
7. deterministic parameter fingerprintがある
8. failure sink interfaceが定義される
9. DB/API/UIへまだ進んでいない
10. pytest全件成功
11. ruff成功
12. demo成功
13. scale_check成功
```

---

# 18. 作業完了後の報告形式

Phase 1Aが終わったら次Phaseへ勝手に進まず停止する。

以下の形式で報告する。

```text
## Phase 1A 実装結果

### Baseline確認
- Python:
- pytest:
- ruff:
- demo:
- scale_check:
- make_release --check:

### 変更ファイル
- file:
  - 変更内容

### 契約変更
- preprocessing_version:
- RunContext:
- ContextRef:
- ModelRef / fingerprint:
- failure sink:

### v2.2完全仕様との対応
- 対応した項目
- まだ未対応の項目

### 追加テスト
- テスト名
- 検証内容

### 全テスト結果
- pytest:
- ruff:
- demo:
- scale_check:

### 互換性への影響
- 既存API変更:
- fixture変更:
- migrationが必要な点:

### 今回あえて実装しなかったもの
- DB
- API
- UI
- artifact永続化
- Worker再開
- 2つ目のOSS
- その他

### 残っている懸念
- なし / 内容
```

この報告で停止し、レビューを受けてからPhase 1Bへ進むこと。
