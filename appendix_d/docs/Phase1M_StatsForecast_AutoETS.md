# Phase 1M StatsForecast AutoETS Provider

Phase 1Mは`statsforecast==2.1.1`のAutoETSを、builtin baselineに続く2つ目のOSS予測Providerとして追加する。Provider IDは`statsforecast-ets`、モデルIDは`auto_ets_weekly`である。

## 固定学習条件

実験定義は次の値を必須とする。

```json
{
  "provider_id": "statsforecast-ets",
  "model_name": "auto_ets_weekly",
  "params": {"season_length": 7, "model": "ZZZ"},
  "interval_levels": [],
  "preprocessing_version": "statsforecast-causal-ffill-v1"
}
```

TRAINで`AutoETS(season_length=7, model="ZZZ")`を1回だけfitする。選択されたETS構造、平滑化パラメータ、初期状態を固定し、各起点では`forward`でその時点までの履歴へ適用する。学習済み状態のSHA-256署名はModelRefへ保存し、refresh、predict、artifact復元で一致を検査する。

初期範囲はPOINT予測だけを提供する。AutoETSの標準区間はforward対象履歴から分散を再計算するため、固定比較の区間予測としては採用しない。外生変数、月次再学習、パラメータ探索条件の比較もこのPhaseの対象外とする。

## 欠損処理

学習期間または起点以前の範囲を日次へreindexし、過去の最終観測値だけで前方補完する。先頭欠損は切り落とし、未来からの逆方向補完と0補完は行わない。確定0は観測値として維持する。最小履歴28日は補完後の日数ではなく実観測数で判定し、学習・起点ごとの補完件数をartifactへ保存する。

## 保存と復元

AutoETSの実行可能オブジェクトをpickleへ保存しない。forwardに必要な周期、構造、パラメータ、fit結果を有限数値・配列・文字列からなる版付きJSONへ変換する。NaNのパラメータ枠はJSONの`null`として保存する。モデル、署名、系列集合、学習条件、run、experimentが一致しないartifactは復元しない。

## 実行

開発・検証環境は次で依存を導入する。

```powershell
python -m pip install -r requirements-dev.txt
```

独立Workerは次のように起動する。

```powershell
kiban-worker --postgres-dsn <DSN> --statsforecast-ets --artifact-root <DIR> --work-root <DIR> --worker-id <ID>
```

Docker Composeでは次を使う。

```powershell
docker compose --profile statsforecast-worker up -d --build statsforecast-worker
```

`statsforecast` extraを導入しない基本packageでは、この任意Providerだけがregistryへ登録されない。builtin baselineと共通契約は引き続き利用できる。

## 検証範囲

人工データで、TRAIN外をfitへ渡さないこと、起点履歴の反映、未来実績の非参照、horizon 1〜15の一括POINT出力、署名不変、JSON復元後の完全一致、APIから独立Worker processまでの完走を確認する。これは実データでの精度、業務効果、処理時間を保証する試験ではない。
