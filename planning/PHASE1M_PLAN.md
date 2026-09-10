# Phase 1M 実装計画

## ゴール

StatsForecast AutoETSを2つ目のOSS Providerとして共通契約へ接続し、TRAINで推定したモデル構造・平滑化パラメータを固定したまま、各起点までの履歴だけで状態を更新する。builtin baselineと同じsnapshot、予定表、失敗台帳、評価処理を使い、Provider固有分岐を実行基盤へ増やさず比較できる状態にする。

## 採用構成

- ライブラリ: `statsforecast==2.1.1`、Apache-2.0。
- モデル: 日次週周期の`AutoETS(season_length=7, model="ZZZ")`。
- 前処理: `statsforecast-causal-ffill-v1`。欠損を0にせず、起点以前の値だけで前方補完する。先頭欠損は切り落とし、実観測28日未満の系列は除外する。
- 固定条件: TRAINでAutoETSを1回fitし、各起点は学習済みmodelの`forward`で固定パラメータを履歴へ適用する。
- 出力: 初期適合範囲はPOINTのみ。`forward`が履歴全体から分散を再計算するため、TEST情報で区間幅が変わる構成は固定条件から除外する。

## モジュール境界

`providers/statsforecast_ets.py`は共通Provider契約、`providers/statsforecast_state.py`は因果的前処理とOSSモデル状態変換、`providers/statsforecast_codec.py`は安全なJSON artifact契約を担当する。`executors/fixed_provider.py`へsnapshot読込・artifact復元・起点実行を共通化し、baselineとStatsForecastのwrapperはProviderとCodecだけを注入する。

## 実装範囲

1. metadataへライブラリ版、依存版、ライセンス、GPU・外部送信・context refresh能力を記録する。
2. Provider ID、モデル、明示パラメータ、前処理版、horizon、区間指定を事前検証する。
3. 欠損と確定0を区別した因果的前方補完を実装し、補完件数をmodel/context stateへ残す。
4. AutoETSのモデル構造、平滑化パラメータ、初期状態を安全なJSONへ保存・復元する。pickleは使わない。
5. 学習済みパラメータの署名を保存し、context更新・予測・artifact復元で不変性を検査する。
6. 共通固定学習runnerと共通Worker executorへStatsForecastを接続する。
7. optional依存とDocker imageを固定し、StatsForecastなしでもbaseline packageをimport可能にする。
8. 共通適合試験、別process Worker、artifact roundtrip、比較評価、wheel、Dockerを検証する。

## 完了条件

- 適合試験の固定パラメータ、履歴反映、未来非参照、horizon一括出力、再現性、失敗通知を満たす。
- context更新前後で学習済みパラメータ署名が変化しない。
- 同じsnapshot/config/seedのartifact復元後にPOINT出力が完全一致する。
- 欠損は0に変換されず、起点より未来の値は補完にも予測にも使われない。
- 共通runner、API experiment、RunStore、評価コードへProvider固有の条件分岐を追加しない。
- StatsForecast未導入環境では任意Providerだけが未登録となり、baseline機能は維持される。
- pytest、ruff、別process、Docker、wheel、配布checksumを確認する。

## 対象外

StatsForecastの予測区間、外生変数、月次再学習、モデル自動チューニング比較、実データ20〜50品目の性能・精度・費用評価、MLForecast、TimesFM、本番採用判断。
