# Phase 1Z MLForecast Ridge Provider

Phase 1Zは`mlforecast==1.1.0`と`scikit-learn==1.9.1`のRidgeを、builtin baseline、StatsForecast AutoETSに続く3つ目の予測Providerとして追加する。Provider IDは`mlforecast-ridge`、モデルIDは`ridge_lag_calendar`である。

## 固定学習条件

実験定義は次の値を必須とする。

```json
{
  "provider_id": "mlforecast-ridge",
  "model_name": "ridge_lag_calendar",
  "params": {"alpha": 1.0},
  "interval_levels": [],
  "preprocessing_version": "mlforecast-causal-ffill-lags-dow-v1"
}
```

各系列についてMLForecastがlag 1・7・14・28日と曜日を生成し、`Ridge(alpha=1.0, solver="cholesky")`をTRAINで1回だけ学習する。最小履歴は実観測56日かつ前方補完後56日である。各起点では学習済み係数と切片を固定し、その時点までの履歴に対してhorizon最大値まで再帰予測する。

初期範囲はPOINT予測だけを提供する。外生変数は入力契約上受け取れるが、このモデルでは使用しない。探索済みハイパーパラメーター、予測区間、複数系列を一つのglobal modelへまとめる方式は別のモデルIDと前処理版で追加する。

## 欠損と時点

学習期間または起点以前の範囲を日次へreindexし、過去の最終観測値だけで前方補完する。先頭欠損は切り落とし、未来からの逆方向補完と0補完は行わない。確定0は観測値として維持する。学習・起点ごとの補完件数をartifactへ保存する。

## 保存と復元

MLForecastやscikit-learnの実行可能オブジェクトをpickleへ保存しない。予測に必要な特徴名、有限な係数、切片、alphaだけを版付きJSONへ保存する。モデル状態のSHA-256署名をModelRefへ保存し、context更新、予測、復元時に一致を検査する。系列集合、学習条件、run、experiment、署名が一致しないartifactは復元しない。

## 実行

開発・検証環境は次で依存を導入する。

```powershell
python -m pip install -r requirements-dev.txt
```

独立Workerは次のように起動する。

```powershell
kiban-worker --postgres-dsn <DSN> --mlforecast-ridge --artifact-root <DIR> --work-root <DIR> --worker-id <ID>
```

Docker Composeでは次を使う。

```powershell
docker compose --profile mlforecast-worker up -d --build mlforecast-worker
```

`mlforecast` extraを導入しない基本packageでは、この任意Providerだけがregistryへ登録されない。他の登録済みProviderは引き続き利用できる。

## 検証範囲

人工データで、MLForecastネイティブ予測との一致、TRAIN外と未来実績の非参照、horizon 1〜15の一括POINT出力、係数署名の不変、JSON復元後の完全一致、3 Providerの共通比較、APIから独立Worker processまでの完走を確認する。これは実データでの精度、業務効果、処理時間を保証する試験ではない。
