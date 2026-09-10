# Phase 1M 実装結果

## 達成したゴール

`statsforecast==2.1.1`のAutoETSを2つ目のOSS Providerとして追加し、builtin baselineと同じ固定学習runner、snapshot、予定表、失敗台帳、評価処理で比較できるようにした。学習済みパラメータをTESTで再推定せず、起点以前の履歴だけを反映して別Worker processから再現できる。

## 実装

- 日次週周期の`AutoETS(season_length=7, model="ZZZ")`を明示設定とし、POINT予測へ適合範囲を限定した。
- 欠損を未来から補完せず、過去の最終観測値だけで因果的に前方補完した。確定0は維持し、実観測28日未満を除外した。
- AutoETSのモデル構造、平滑化パラメータ、初期状態をpickleなしの版付きJSONへ保存した。
- 学習済み状態のSHA-256署名を保存し、context更新、予測、artifact復元でパラメータ不変を検査した。
- snapshot読込、model/context artifact、起点予測を`FixedProviderExecutor`へ共通化し、各Providerのexecutorを小さなwrapperにした。
- `run_fixed_provider`へProvider非依存の固定学習処理を移し、`run_fixed_baseline`は互換wrapperとして維持した。
- StatsForecastをoptional extraとし、未導入環境ではAutoETSだけをregistryから除外できる構成にした。
- CLIとDocker Composeへ独立StatsForecast Workerを追加した。

## 検証

- PostgreSQL 17実DBを含むpytest 337件とruffを実行し、全件合格した。
- TRAIN固定、起点履歴反映、未来非参照、horizon 1〜15一括出力、署名不変を人工系列で確認した。
- JSON model/context artifactの復元後に予測値が完全一致し、署名改変を拒否した。
- APIでexperiment/runを作り、2回の独立Worker processで同じmodel artifactを復元してrunを完了した。
- baselineとAutoETSを同一dataset・予定・truthで評価し、official比較集合の成立を確認した。
- StatsForecast依存を含むDocker imageをbuildし、コンテナ内で両Providerのregistry登録を確認した。
- demo、100系列規模確認、既存artifact demo、wheel、配布ZIP checksumを確認した。

## 未対応事項

実データ3〜5品目の受入と全3年20〜50品目の業務確定は未実施である。AutoETSの予測区間、外生変数、月次再学習、実データ上の処理時間・精度・費用評価、比較結果と適合記録のDB永続化、UI、本番role/TLS/監視は後続とする。
