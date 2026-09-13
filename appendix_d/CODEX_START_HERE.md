# Codex開始ガイド v2.9

README → docs/統合仕様_v2.9.md → docs/実装仕様書_v2.2_完全版.mdの順で読む。
これは予測・比較コアの修正完成パッケージ。基盤全体の本番完成ではない。

## 起動確認

READMEのOS別手順で依存をインストールする。

```text
python -m pytest -q
ruff check .
python demo.py --output demo_output
python make_release.py --check
```

全体の件数・結果はtest_results.txt。旧標準ランナー47件だけで完了判定しない。

## 維持する仕様

- 固定学習と月次再学習を混ぜない。`training_policy`と評価集合で明示的に分離する。
- 確定ゼロだけ0。欠測はNaN、予測失敗は全予定の台帳に残す。
- POINTと中央値を別保存する。
- ownは自run集合、commonは全run共通、officialは完全runのみの共通集合。
- 単独精度が比較相手の追加で変わらないことを維持する。
- comparison_set_idとofficial_comparison_set_idを別々に保存する。
- 正式候補1件は単独評価。優勝という表示をしない。
- 将来変数はカレンダー内部生成かknown_atによる版選択。最終確定列を直接使わない。
- 失敗例外の記録と契約違反による停止を区別する。

## 開発順

Phase 1Aで前処理版・起点別RunContext・ContextRef締切・モデル識別・failure sink interfaceを追加した。
必須引数とProvider直接呼出しの移行は[契約と移行](docs/Phase1A_契約と移行.md)を参照する。
既存RunContext importは維持するが、旧ModelRef/ContextRefはfitから再生成する。
時点処理はrun_context.py、識別はfingerprint.py、失敗記録はfailures.pyへ分離する。
Phase 1Aはレビュー・マージ済み。Phase 1Bでローカルartifact保存・復元を追加した。
詳細は[保存と復元](docs/Phase1B_保存と復元.md)。python artifact_demo.pyで別プロセス再現を検証する。
DB・Workerジョブ再開は未実装。Phase 1Bはレビュー後に次の段階へ進める。

Phase 1Cで製品非依存のRunStore、SQLite参照台帳、起点単位transaction、attempt fencing、再開Workerを追加した。詳細は[run台帳と再開](docs/Phase1C_run台帳と再開.md)。本番PostgreSQL、複数Worker、強制timeout、API/UIは未実装。

Phase 1DでPostgreSQL実装、SKIP LOCKED claim、lease/heartbeat、期限切れ回収、起点timeoutを追加した。詳細は[PostgreSQLとWorker lease](docs/Phase1D_PostgreSQLとWorkerLease.md)。

Phase 1EでBearer認証付きrun APIと独立Workerプロセスを追加した。HTTPは台帳操作だけを行い、予測はWorkerのOriginExecutorで実行する。詳細は[APIとWorker process](docs/Phase1E_APIとWorkerProcess.md)。

Phase 1Fで版付きdataset snapshot・実験catalog、保存済み実験からのrun生成、artifactを復元する組込baseline Workerを追加した。詳細は[実験SnapshotとBaseline統合](docs/Phase1F_実験SnapshotとBaseline統合.md)。

Phase 1Gで原本取込job、独立取込Worker、SHA-256原本保存、重複・訂正版候補・隔離台帳を追加した。詳細は[原本取込台帳](docs/Phase1G_原本取込台帳.md)。

Phase 1Hで版付き列mapping、出荷行正規化、訂正版の明示採用、行隔離、数量照合、品質APIを追加した。詳細は[出荷行正規化と数量照合](docs/Phase1H_出荷行正規化と数量照合.md)。

Phase 1Iで決定論的なJAN名寄せ候補、承認履歴、canonical product、JAN有効期間、商品×center取扱期間を追加した。詳細は[JAN名寄せと取扱期間](docs/Phase1I_JAN名寄せと取扱期間.md)。

Phase 1Jで予定ファイル完全性、6種類の日次状態、休業日の時点選択、日次dataset snapshotの自動発行を追加した。詳細は[予定完全性と日次状態](docs/Phase1J_予定完全性と日次状態.md)。

Phase 1Kで日次buildを対象とする3〜5品目の受入case、10項目の技術判定、決定的な品質レポート、版付き業務判断を追加した。匿名データは`DRY_RUN`となり承認できない。詳細は[少数実品目の受入](docs/Phase1K_少数実品目受入.md)。

Phase 1Lで成功済み日次buildから重要品目候補の数量・構成比・変動係数・出荷0率・欠損率・JAN変更・業務指定を算出し、初期3〜5または拡大20〜50品目を対象center・理由付きの不変な`selection_version`として保存する機能を追加した。詳細は[重要品目候補と選定版](docs/Phase1L_重要品目候補と選定版.md)。

Phase 1Mで`statsforecast==2.1.1`のAutoETSを2つ目のOSS Providerとして追加した。TRAINで選択した構造・平滑化パラメータを固定し、起点以前の履歴だけを因果的に前方補完して`forward`へ渡す。安全なJSON artifact、共通runner、独立Worker processまで適合確認済み。詳細は[StatsForecast AutoETS Provider](docs/Phase1M_StatsForecast_AutoETS.md)。

Phase 1NでProvider適合試験記録と保存済みrun比較をSQLite/PostgreSQLへ永続化した。比較APIはrun台帳とchecksum検証済みsnapshotから指標を再計算し、適合済みの完全runだけを正式集合へ含める。詳細は[Provider適合試験と比較結果の永続化](docs/Phase1N_評価レジストリ.md)。

Phase 1Oで保存済み比較から決定的なUTF-8 BOM付きCSVを発行し、正式比較、実データ受入、最新の業務承認、日次buildを照合する不変な採用判断台帳を追加した。詳細は[比較レポートCSVと採用判断](docs/Phase1O_比較レポートと採用判断.md)。

Phase 1Pで比較・受入・採用を同じ画面で扱う`/ui`を追加した。Bearer tokenはメモリ内だけで保持し、一覧、指標・系譜、受入判断、比較CSV、採用判断を既存APIへ接続する。詳細は[比較・受入・採用管理画面](docs/Phase1P_比較受入採用管理画面.md)。

Phase 1Qでsubjectとroleを持つ複数Bearer credential、endpoint別permission、認証subjectによる監査主体の固定、productionのHTTPS・Host制約と共通security headerを追加した。従来の単一tokenはdevelopment専用ADMINとして維持する。詳細は[認証・認可とセキュリティ境界](docs/Phase1Q_認証認可とセキュリティ.md)。

Phase 1Rで外部IdPのJWT/OIDC検証、credential fileとJWKSのrotation、構造化監査log、liveness・readiness・metrics、PostgreSQL backup/restore、Caddy TLS終端、本番Composeを追加した。API、認証、観測、DB操作、deploy設定は独立moduleへ分割した。詳細は[本番運用基盤](docs/Phase1R_本番運用基盤.md)。

Phase 1Sで月次拡大学習、reference比較、champion/challengerの承認付き昇格、revision付きrollback、冪等scheduler、30日以上の将来trial台帳を追加した。詳細は[継続学習と安全なモデル切替](docs/Phase1S_継続学習とモデル切替.md)。

Phase 1Tで専用Lifecycle管理画面を追加し、計画、cycle、昇格、rollback、予測事前記録、trial評価をrole別APIへ接続した。詳細は[Lifecycle運用画面](docs/Phase1T_Lifecycle運用画面.md)。

Phase 1Uで専用データ準備画面を追加し、取扱期間の登録・履歴と日次buildのファイル完全性、6状態、欠測理由、条件検索をrole別APIへ接続した。詳細は[取扱期間と欠測判定画面](docs/Phase1U_取扱期間と欠測判定画面.md)。

Phase 1Vで専用重要品目選定画面を追加し、候補jobの登録・一覧、候補指標・分類・品質条件・centerの確認、INITIAL/FULL選定版の確定と履歴をrole別APIへ接続した。詳細は[重要品目候補・選定画面](docs/Phase1V_重要品目選定画面.md)。

Phase 1Wで専用実データ受入画面を追加し、INITIAL 3〜5品目からのcase登録、独立Workerの10項目技術判定、品質レポート識別子、版付き業務判断履歴をrole別APIへ接続した。詳細は[実データ受入画面](docs/Phase1W_実データ受入画面.md)。

Phase 1Xで専用原本取込・正規化画面を追加し、取込job、原本checksum・訂正系譜、版付き採用、列mapping、正規化job、隔離行、数量照合をrole別APIへ接続した。正規化行は100件単位で取得する。詳細は[原本取込・正規化画面](docs/Phase1X_原本取込正規化画面.md)。

Phase 1Yで専用JAN名寄せ・商品マスター画面を追加し、成功済み正規化jobからの名寄せjob登録、候補根拠・center別数量、canonical product、版付き判断、JAN有効期間をrole別APIへ接続した。名称一致だけでは統合せず、候補計算は独立Workerが行う。詳細は[JAN名寄せ・商品マスター画面](docs/Phase1Y_JAN名寄せ商品マスター画面.md)。

Phase 1Zで`mlforecast==1.1.0`と`scikit-learn==1.9.1`のRidgeを3つ目の予測Providerとして追加した。lag・曜日特徴をMLForecastで生成し、系列別の係数を固定して各起点の履歴へ再帰適用する。pickleを使わないJSON artifact、共通runner、独立Worker、開発・本番Composeまで接続した。詳細は[MLForecast Ridge Provider](docs/Phase1Z_MLForecast_Ridge.md)。

Phase 2AでApache-2.0のTimesFM 2.5 200Mを4つ目の予測Providerとして追加した。固定revision・size・SHA-256で検証したローカル重みだけを使い、実行時ダウンロードを禁止する。最大512日の因果的context、POINT予測、重みを含まないJSON artifact、PyTorchを分離した専用Worker、開発・本番Composeまで接続した。TimesFM 3.0重みは非商用ライセンスのため対象外である。詳細は[TimesFM 2.5 Provider](docs/Phase2A_TimesFM_2p5.md)。

Phase 2BでTimesFM専用Workerの起動前検査と運用計測を追加した。固定checkpoint、モデル初期化、warm-up、反復推論、CPU時間、process peak RSS、cgroup上限を分離して測り、技術判定を内容アドレス方式のJSONへ保存する。benchmark serviceはCPU 2、memory 4 GiB、networkなし、checkpoint read-onlyで動作する。詳細は[TimesFM運用計測](docs/Phase2B_TimesFM運用計測.md)。

Phase 2Cで実データ受入プリフライトを追加した。原本を読む前に5つのdata rootの存在・権限・symlink・重複・application境界と、PostgreSQL 17のPhase 1X〜1K必須schema・Worker権限を10項目で検査し、path・DSN・原本名を含まない不変JSON証跡を保存する。詳細は[実データ受入プリフライト](docs/Phase2C_実データ受入プリフライト.md)。

Phase 2DでPostgreSQL隔離リカバリ訓練を追加した。内部生成した一時DBだけへcustom archiveを復元し、backup前後の元DB安定性、archive検証、schema・全table内容のstreaming指紋一致、一時DB削除を判定する。証跡にDSN、DB/user名、path、relation名、行値を含めない。詳細は[Phase2D PostgreSQL隔離リカバリ訓練](docs/Phase2D_PostgreSQL隔離リカバリ訓練.md)。

Phase 2Eで全7管理画面のOIDC Authorization Code + PKCEログインを追加した。state、S256 challenge、code交換、callback URL消去を共通moduleで行い、access tokenはmodule memoryだけに保持する。詳細は[OIDC PKCEログイン](docs/Phase2E_OIDC_PKCEログイン.md)。

Phase 2Fで外部IdP接続プリフライトを追加した。DiscoveryとJWKSを証明書検証付きHTTPSで直接取得し、設定との完全一致、Authorization Code、PKCE S256、署名方式、互換鍵と`kid`を14項目で検査する。URL・host名・公開鍵値・例外本文を含めない不変JSON証跡を保存する。詳細は[外部IdP接続プリフライト](docs/Phase2F_外部IdP接続プリフライト.md)。

Phase 2Gでクレンジング・列マッピングドライランを追加した。入力rootとマッピングをread-onlyで読み、Phase 1Hと同じ規則により文字コード、ヘッダー、サンプル行、隔離理由、数量照合を台帳更新なしで判定する。証跡にはpath、列名、原値、数量を保存しない。詳細は[クレンジング・列マッピングドライラン](docs/Phase2G_クレンジング列マッピングドライラン.md)。

Phase 2Hでマッピングドライラン証跡のread-only APIと原本取込管理画面のレビュー機能を追加した。APIは内容とファイル名のSHA-256、重複JSON key、固定schema、ID、判定整合性を再検証し、原値を含まない固定項目だけを返す。詳細は[マッピングドライラン証跡レビュー](docs/Phase2H_マッピングドライラン証跡レビュー.md)。

次はプリフライトが`READY_FOR_DATA`の環境で実業務原本へPhase 2Gを実行し、Phase 2H画面で`READY_FOR_NORMALIZATION`または隔離理由を確認する。その後Phase 1Xから全行の数量照合、JAN名寄せ判断、Phase 1J〜1Kの受入へ進み、全3年の重要品目選定とPhase 1Sの将来trialを開始する。
実データ受入は未実施であり、人工データだけで精度や業務効果を保証しない。

## 変更報告

変更ファイル、理由、契約への影響、pytest・ruff・実データ検証、未対応事項を記載する。
契約変更は仕様・コード・テストを同時更新し、テスト削除や期待値の弱体化で通さない。
