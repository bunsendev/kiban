# Phase 1A 実装計画

状態: 計画済み・実装未着手。基準版: v2.9。ユーザー要件: ファイル肥大を避け、保守と機能追加を容易にする。

## 対象範囲

共通契約、起点ごとの時点情報、再現性識別、失敗記録インターフェースを整備する。DB/API/UI、原本CSV取込、JAN名寄せ、追加OSS、永続化、Worker再開、再学習は対象外。

## 責務分割

| モジュール | 責務 |
|---|---|
| contracts.py | 既存公開型・Provider契約。RunContextの既存importは再公開で維持 |
| run_context.py（追加） | RunContextの単一定義、fit/起点context派生、時点検証 |
| fingerprint.py（追加） | 学習条件の正規化、決定論的SHA-256生成 |
| failures.py（追加） | FailureRecord、FailureSink、メモリ実装、既存errors形式への変換 |
| errors.py | 例外分類 |
| runner.py | 実行手順の制御と各機能の接続 |
| providers/builtin_baseline.py | baseline計算とProvider側契約検証 |

共通層からrunnerや個別Providerへ依存させない。型を重複定義しない。行数だけでなく責務と変更理由で分割し、大規模リファクタリングは避ける。

## 実装順序

1. Baseline確認: pytest 115件、ruff、demo、scale_check、make_release --check 32/32。差異があれば環境と原因を報告して実装停止。
2. 型の生成箇所、fixture、公開import、Provider呼出しの影響調査。
3. ProviderConfig.preprocessing_versionを必須化。空・空白のみ・None・非文字列を拒否。paramsのimmutable仕様を維持。
4. RunContextにavailability_mode/cutoff_at/origin_dateを追加。fitはTRAIN_END、起点処理はoriginを基準として翌日00:00 JSTへ派生。deadlineとは区別。dataset/runner/contextのmode一致を検証。
5. ContextRefにcutoff_atを保存。predict前にmodel_id/origin/cutoff一致を検証。Provider直接呼出しも検証対象。
6. ModelRefに前処理・重み識別とfingerprintを追加。baselineの重みは該当なしと明示し、artifactを捏造しない。前処理識別はconfigから引き継ぐ。
7. 型付きFailureRecordとsinkを接続。既存errorsの意味を維持。契約違反は送出。sink失敗時は元recordを保持した専用例外で停止する設計案。
8. 仕様、開始ガイド、必要なら付録Dを更新し、全検証。Phase 1A報告で停止する。

## fingerprint

provider_id/version、model、params、interval_levels、preprocessing_version、snapshot、selection、availability、TRAIN期間、対象系列、seedを含める。辞書キーと系列集合の順序、日付・数値の表現を正規化し、方式にも版を付ける。未対応型は拒否する。UUID、fitted_at、起点ごとの履歴は除外する。

学習条件のfingerprintと学習済みパラメータの不変性は別に検証する。refresh前後で学習パラメータが変更されない試験を行う。

## テスト構成

既存115件の検証内容を維持し、必須引数に対応するfixtureを更新する。test_provider_config.py、test_run_context.py、test_fingerprint.py、test_failure_sink.py、test_phase1a_integration.pyへ責務ごとに追加する。

型の不正値、複数起点のcutoff、別モデル・起点・cutoffの誤用、同条件でのfingerprint一致、各条件変更、通常例外・未分類例外・契約違反・sink失敗を確認する。

最終ゲート: pytest全件、ruff、demo、scale_check、make_release --check。

## ハッシュと配布

既存pytestに配布ハッシュ照合が含まれるため、変更後の全件検証前に作業版ハッシュを更新する。検証記録更新後にも再生成・照合する。指示書15章の更新保留可能という記載に対する手順上の補足として記録する。テスト削除・skipによる回避はしない。版番号は変更しない。

## 完了報告

Baseline、変更ファイル、契約変更、v2.2との対応、追加テスト、全検証結果、互換性・移行点、未実装事項、残課題を報告する。人工データ検証を本番精度保証としない。
