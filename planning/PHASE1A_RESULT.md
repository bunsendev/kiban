# Phase 1A 実装結果

基準版v2.9を維持し、共通契約を追加した。作業ブランチはcodex/phase1a-contracts。
Phase 1Bには進まず、本変更をレビュー対象とする。

## Baseline確認

- 環境: Windows 11、Python 3.12.14。提供記録のLinux/Python 3.12.13とは環境差があるが、下記の結果は一致。
- pandas 2.2.3 / numpy 2.3.5 / pytest 9.1.1 / ruff 0.16.6。
- pytest: 115 passed in 5.59s。
- ruff: All checks passed。
- demo: 成功。人工データ3系列・点予測2方式。
- scale_check: 37起点、通期成立True、profile (10, 10)、点予測54,500行、POINT＋QUANTILE218,000行、365日/系列、重複0。
- make_release --check: 32/32一致。

## 変更ファイル

| ファイル | 内容 |
|---|---|
| forecast_provider/contracts.py | 必須前処理版、ModelRefの識別項目・学習開始日、ContextRef締切。RunContextは再公開 |
| forecast_provider/run_context.py（新規） | RunContextを単一定義し、起点派生とcutoff・参照を検証 |
| forecast_provider/fingerprint.py（新規） | 型付き正規化と決定論的SHA-256 |
| forecast_provider/failures.py（新規） | FailureRecord、FailureSink、メモリsink、既存errors変換、sink障害の送出 |
| forecast_provider/runner.py | fit/起点別contextをProviderへ渡し、失敗記録を委譲。cleanupをfinallyに集約 |
| forecast_provider/providers/builtin_baseline.py | ModelRef識別、cutoff保存、時点・runの照合。予測計算は維持 |
| demo.py / scale_check.py | 前処理版・時点引数を明示し、直接Provider呼出しを移行 |
| tests/test_builtin_baseline.py、test_v26/27/28_regressions.py | 既存検証を維持しfixture・呼出しを移行 |
| tests/conftest.py と新規テスト5ファイル | 型、fingerprint、sink、統合動作の追加試験 |
| docs/統合仕様_v2.9.md / CODEX_START_HERE.md / 付録D | Phase 1Aの完成範囲・モジュール・参照先を更新 |
| docs/Phase1A_契約と移行.md（新規） | API変更・具体例・識別ルール・例外・未対応事項を記録 |
| make_release.py | WindowsでもmanifestをLFで出力し、不要な改行差分を防止 |
| test_results.txt / SHA256SUMS.json | 検証証跡・配布ハッシュを更新 |

上記はappendix_d配下。リポジトリ直下READMEとplanningの状態も更新した。
新しい実行処理は3モジュールへ分離し、runnerは変更前より短くなった。
evaluation.py / features.py / frames.py / errors.pyの計算・分類仕様は変更していない。

## 契約変更

- preprocessing_version: 必須keyword引数・非空・immutable。既定値の自動挿入なし。
- RunContext: availability_mode/cutoff_at必須。origin_dateは親ではNone可、Provider呼出し時はfor_originで明示。JST翌日00:00。
- ContextRef: cutoff_at必須。predict前にmodel/origin/cutoff/history_endを照合する。
- ModelRef: train_start_date、preprocessing_version、parameter_fingerprint、weights_id、availability_modeを追加。baselineの外部重みはNoneで非該当。
- fingerprint: 指示書の全必須条件に加えmax_horizon、特徴列、依存環境を含む。UUID・学習時刻・起点履歴は除外。
- failure sink: 同じrecordから既存errorsを生成。契約違反は送出し、sink障害は元recordを保持したFailureSinkErrorで停止。

## v2.2完全仕様との対応

- §7/10.1: 各originの情報利用時点とcontext参照を明示。run/experimentを跨ぐモデルの暗黙共有を拒否。
- §10.1: 前処理・重み識別・パラメータ指紋に対応。具体名の指定がなかった重みはweights_idを採用。
- §10.3/AC-08: refreshでモデルの学習済みstateが変更されないことを別途検証。
- §14: fingerprintへライブラリ・依存・Python版・container識別を含める。永続artifact checksumやWorker再開は未対応。
- DB/API/UI、実データ受入、月次再学習は本Phaseの対象外。

## 追加テスト

| テストファイル | 代表的なテスト・検証内容 |
|---|---|
| test_provider_config.py | test_preprocessing_version_rejects_invalid_values / test_preprocessing_version_is_required_and_frozen |
| test_run_context.py | test_context_derivation_preserves_shared_resources_and_parent、cutoffの不正値・UTC同時刻・mode・日付の検証 |
| test_fingerprint.py | test_fingerprint_ignores_order_and_run_identity、各条件変更、provider/environment変更、不正型・精度喪失拒否、再fit一致、refreshで学習済みstate不変 |
| test_phase1a_integration.py | test_runner_delivers_fit_and_each_origin_context、参照のmodel/origin/cutoff誤用、直接Provider呼出し、OBSERVED点予測 |
| test_failure_sink.py | fit/起点でのProviderError・KeyError記録、契約違反送出、sink障害でrecord保持・cleanup実行 |

既存テストを削除・skip追加・期待値の弱体化で回避していない。OBSERVED既存テストにはOBSERVED contextを明示し、元の区間未対応検証に到達させた。

## 全テスト結果

- pytest: 190 passed（既存115件＋追加75件）。記録・ハッシュ更新後の再確認は4.61秒で成功。
- ruff: All checks passed。demo / scale_checkも終了コード0。実測結果はappendix_d/test_results.txtに保存。
- デモ出力7ファイルはBaselineとバイト単位で一致。予測CSV・失敗照合・累計・比較JSONの変化なし。
- 規模検証: 37起点、54,500点予測、218,000総行、365日/系列、重複0。
- ハッシュ照合: 42/42一致。ハッシュ再生成後にもpytest全件と照合を実施済み。

## 互換性への影響

- 既存import経路は維持。ProviderConfig/RunContext/ModelRef/ContextRefの生成には新しい必須keyword引数が必要。
- 直接Provider呼出しでは、fit/refresh/predictごとの時点contextを明示する。
- 旧ModelRef/ContextRefはfitから再生成する。DB migrationは不要。
- fingerprintは学習条件の識別であり、可変stateの改ざん検出や永続化保証ではない。

## 今回実装しなかったもの

DB、API、UI、原本CSV取込、JAN名寄せ、artifact永続化、Worker再開、分散実行、強制timeout、retry scheduler、2つ目のOSS、月次再学習、クラウド構成。

## 残っている懸念

- 人工データでの動作検証のみ。実データ精度・業務効果は未検証。
- snapshot発行・前処理版更新の統制、訂正履歴の保管、重みchecksum検証は上流・次Phaseの責務。
- stateの永続化・復元は未実装。今回のfingerprintだけでモデル状態の保存・再開はできない。
- sink障害時は通常のrun戻り値を返さない。将来WorkerはFailureSinkError.recordと原因例外を回収する必要がある。
