# Phase 1Z 実装計画

## ゴール

OSS比較の第3系統として`mlforecast==1.1.0`と`scikit-learn==1.9.1`を使うRidge Providerを追加する。固定学習、起点別の履歴更新、安全なJSON artifact、共通runner、独立Worker、Docker運用まで一つの実験条件として再現できるようにする。

## 実装範囲

1. MLForecastでlag 1・7・14・28日と曜日を生成し、系列別Ridgeを固定条件で学習する。
2. 起点以前の履歴だけを因果的に前方補完し、保存済み係数で再帰POINT予測する。
3. 学習済み係数、切片、特徴名、署名をpickleなしの版付きJSONへ保存・復元する。
4. Provider本体、学習状態、artifact codec、executorを別moduleとして実装する。
5. registry、Worker CLI、開発・本番Compose、固定依存へ接続する。
6. 共通runner、3 Provider比較、独立Worker、wheel、配布checksumまで検証する。

## 完了条件

- MLForecastのネイティブ再帰予測と、保存可能な係数表現からの予測が一致する。
- TRAIN外と起点より未来の実績を学習・予測に使用しない。
- 学習済み係数は起点更新・予測で変化せず、改ざんしたartifactは復元できない。
- baseline、AutoETS、Ridgeが同じ比較契約と正式集合を使用する。
- HTTPでは学習せず、`--mlforecast-ridge`を指定した独立Workerが処理する。
- 開発・本番Composeで専用Workerを選択できる。
- pytest、ruff、Docker、PostgreSQL、wheel、配布checksumが成功する。
- 人工データの試験結果を実データ精度や業務効果として扱わない。
