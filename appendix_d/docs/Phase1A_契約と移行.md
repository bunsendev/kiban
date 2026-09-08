# Phase 1A 共通契約と移行

本書は統合仕様v2.9第11章のPhase 1A補足。版番号は2.9.0を維持する。
本書の未実装事項はPhase 1A時点の記録。後続のローカル保存・復元は[Phase 1B](Phase1B_保存と復元.md)を参照する。
DB/API/UIやモデル永続化の完成を示すものではない。

## モジュールの責務

| モジュール | 責務 |
|---|---|
| contracts.py | Dataset/ProviderConfig/ModelRef/ContextRef/Provider契約 |
| run_context.py | RunContextの単一定義、起点別派生、締切・参照照合 |
| fingerprint.py | 学習条件の正規化とSHA-256生成 |
| failures.py | 失敗record・sink契約・メモリsink・既存errors変換 |
| runner.py | 固定学習と各起点の実行制御 |

共通層からrunnerや個別Providerへの実行時依存を置かない。型の相互参照にはTYPE_CHECKINGを使う。
RunContextの既存import（forecast_provider / forecast_provider.contracts）は再公開により維持する。

## 設定と時点情報

ProviderConfig.preprocessing_versionは必須keyword引数。非空文字列を指定し、空白のみ・None・非文字列はValueError。
immutableなparamsと同じく、生成後に変更できない。自動デフォルトは設定しない。
デモ・fixtureのdaily-nan-preserving-v1は、日次整形済み入力のNaNを保持し0補完しない既存処理を表す。
上流の整形・欠損処理を変えたら新しい前処理版とsnapshotを使用する。

RunContext.availability_modeとcutoff_atも必須keyword引数。availability_modeはASSUMED/OBSERVEDのみ。
cutoff_atはtimezone付き・非欠損datetime。naive、NaT、文字列、utcoffsetがNoneの日時は拒否する。
seedはboolを除く整数。numpy整数はPython intへ正規化する。
deadlineは実行期限、cutoff_atは情報利用締切であり、強制timeoutの実装は含まない。

親contextのorigin_dateはNoneでもよい。runnerは親のcutoffを全起点に流用せず、for_originで派生する。
Providerへ直接渡すcontextはorigin_dateも必須で、対象originと一致しなければ契約違反。
fitにはTRAIN_END、refresh/predictには対象originを使い、翌日00:00 Asia/Tokyoをcutoffにする。
同一実時刻のUTC表現も一致として扱う。任意時刻のcutoffによる運用変更は本Phaseの対象外。

```python
config = ProviderConfig(
    "builtin-baseline", "seasonal_naive_7",
    preprocessing_version="daily-nan-preserving-v1",
)
# parentは既存run情報とavailability_mode/cutoff_atを指定して生成する。
fit_context = parent.for_origin(dataset.train_end)
model = provider.fit_parameters(train, dataset, config, fit_context)
origin_context = parent.for_origin(origin_date)
ref = provider.refresh_context(model, history, origin_date, origin_context)
result = provider.predict(model, ref, future, horizons, origin_context)
```

runnerはdataset/runner引数/contextのavailability一致をProvider生成前に検証する。
Provider直接呼出しでもfit時のdataset一致、refresh/predict時のモデルavailability一致を検証する。
既存のavailable_history・known_at版選択が同じJST締切を使用するため、時点フィルターの計算方式は変更しない。
直接呼出しの場合、available_at/known_atによる入力選択は引き続き呼出側の責務。

ContextRef.cutoff_atは必須keyword引数。Providerは呼出contextのcutoffを保存する。
predictではmodel_id/origin_date/cutoff_at/history_endを照合する。runnerもrefreshの戻り値を照合する。
baselineはモデルstateのrun_id/experiment_idを照合し、別runへの暗黙再利用を拒否する。

## モデル識別とv2.2との対応

v2.2 §10.1は「重みと前処理の識別」「パラメータ指紋」を概念として定義しているが、具体的な英語フィールド名は指定していない。
既存のpreprocessing_versionへ統一し、重みにはweights_id、指紋にはparameter_fingerprintを採用する。

ModelRefへtrain_start_date/preprocessing_version/parameter_fingerprint/weights_id/availability_modeを必須keyword引数として追加する。
前処理版はProviderConfigから引き継ぎ、別の設定値として入力しない。weights_id=Noneは正式に「外部の学習済み重み非該当」を表す。
重みを持つProviderは版やchecksum等の安定識別子を明示する。空文字は拒否する。
baselineはweights_id=None、artifact_uri=Noneであり、重みartifactを作らない。TRAIN由来の残差キャッシュはstateに保持する。

fingerprint方式はtraining-conditions-v1。正規化後のUTF-8 JSONからSHA-256小文字hexを生成する。
材料はprovider_id/version、model、params、interval_levels、preprocessing_version、weights_id、snapshot、selection、availability、TRAIN開始/終了、対象系列、seed。
加えてTRAIN残差キャッシュの範囲に関わるmax_horizon、入力特徴列、ライブラリ・依存版、container_digest、Python実装/版を含める（v2.2 §14の環境識別）。

辞書キー・系列集合・区間水準・特徴列・依存一覧の順序は正規化する。params内の配列順序は保持する。
paramsのNone/文字列/bool/整数/有限実数/date/辞書/配列/集合を型付きで表し、整数とfloatとboolを区別する。
numpy整数はint、実数はfloat表現へ正規化する。floatはhex表現で保持し、負の0と正の0は同一とする。
floatへの変換で精度が失われる実数型は拒否し、異なる設定を同じ指紋に丸めない。
不正値・未対応型をdefault=strで丸めず拒否する。

run_id/experiment_id/model_id/context_id/fitted_at/deadline、起点更新の履歴は材料にしない。
同条件の再fitはUUIDや学習時刻が異なっても同じ指紋になる。snapshot IDの再利用でデータ改変を隠さないことは上流の責務。
これは学習条件の識別でありstate全体の改ざん検出checksumではない。refresh前後の学習済みパラメータ不変性は別のテストで検証する。

## 失敗記録

RunContext.failure_sinkは省略可（None）。FailureSink.record(FailureRecord)を実装する任意の記録先を接続できる。
FailureRecordはfrozen dataclassでrun_id/experiment_id/origin_date/cutoff_at/error/exception_type/retryable/message/tracebackを保持する。
fit失敗のorigin_dateはNone、cutoff_atはTRAIN_END翌日00:00 JST。起点失敗には対象originとそのcutoffを保持する。
InMemoryFailureSinkはテスト・プロセス内用途であり永続化ではない。

runnerは同じrecordから既存errorsの辞書を作る。既存キー、originの文字列表現、ProviderErrorの分類、UNCLASSIFIED_ERRORのtracebackとretryable=Falseを維持する。
通常の起点失敗は次の起点へ進み、fit失敗は全予定FAILEDを返す。ContractViolationErrorはsinkに通常失敗として渡さず送出する。
sinkが例外を送出した場合はFailureSinkErrorで停止する。record属性に元の失敗、__cause__にsink例外を保持し、cleanupを実施する。
既存errorsへの追記はsink呼出しより先に行う。sink失敗時は通常のrun戻り値を返さず、呼出側が例外のrecordを確認する。

## 互換性と未対応

旧呼出しに必須keyword引数の追加が必要。Provider直接呼出しはfit/起点ごとにcontextを派生する。
旧ModelRef/ContextRefは再利用せずfitから再生成する。データベースmigrationは不要（DB未実装）。
stateはDataFrame/Seriesを含むプロセス内オブジェクトのまま。DB/sink永続化、artifact checksum検証、Worker再開、強制timeout、retry schedulerは次Phase。

## 検証記録とハッシュ

既存pytestにハッシュ照合が含まれる。全件実行前にmake_release.pyで作業版ハッシュを生成し、テスト削除・skip追加で回避しない。
最終検証後にtest_results.txtを更新し、再びmake_release.pyと--checkを実行する。文書・型・テストは同じ変更単位で管理する。
