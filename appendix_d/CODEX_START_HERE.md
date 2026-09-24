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

Phase 2Iでローカルデータ検証job、独立Worker、登録APIと`/ui/intake`の実行導線を追加した。登録済みmappingと入力root内のCSV相対pathを指定し、Phase 2Gの検査とPhase 2Hの証跡確認をUIから開始できる。詳細は[ローカルデータ検証UI](docs/Phase2I_ローカルデータ検証UI.md)。

Phase 3Aで全`POST /api/*`へ任意の`Idempotency-Key`を共通適用し、本番では要求fingerprintと成功応答をPostgreSQLへ永続化する。HTTP例外、入力検証、内部例外、HTTPS・Host拒否は`code/message/details/request_id`へ統一し、入力値と例外本文を公開しない。詳細は[API共通契約](docs/Phase3A_API共通契約.md)。

Phase 3Bで全Provider共通の資源・費用台帳を追加した。Workerは起点attemptごとのCPU、推論時間、取得可能なprocess peak memoryを記録し、固定学習共通Executorは前処理、実fit、推論、artifact容量を分離する。単価は取得日・参照元・認証subject付きでADMINだけが登録し、単価不明または通貨混在時の総費用はNULLにする。run APIと比較CSVは同じ集計を返す。詳細は[Provider共通の資源・費用台帳](docs/Phase3B_資源費用台帳.md)。

Phase 3Cで`/ui/resources`の資源・費用管理画面を追加した。READ利用者はrun一覧、8種類の集計、origin・attempt明細、単価履歴を参照し、ADMINはProvider共通または個別単価を根拠・取得日付きで登録できる。比較画面は同じ集計から推論時間と総費用を表示する。詳細は[資源・費用管理画面](docs/Phase3C_資源費用管理画面.md)。

Phase 3DでProvider専用Workerのrun取得をProvider IDで分離した。組込executorはmetadataから対象Providerを固定し、カスタムexecutorは`--provider-id`を必須とする。Baseline、AutoETS、MLForecast、TimesFMを同時起動しても別Providerのrunを取得しない。詳細は[Provider別Worker実行分離](docs/Phase3D_Provider別Worker実行分離.md)。

Phase 3Eで`/ui/analysis`の分析実行ワークスペースを追加した。READ利用者はsnapshot、実験、Provider、run、適合記録、比較履歴を参照し、ANALYZE利用者はメタデータ既定値から実験を作成してrun登録、進捗確認、適合条件が一致するrunの比較作成まで行う。詳細は[分析実行ワークスペース](docs/Phase3E_分析実行ワークスペース.md)。

Phase 3FでProvider専用Workerのheartbeatとキュー診断を追加した。分析実行画面はProviderごとの処理中、待機中、応答遅延、未起動と、全件集計した待機・実行中run数を表示する。同じWorker IDで再起動した旧processはinstance IDでフェンスする。詳細は[Worker稼働状態とキュー診断](docs/Phase3F_Worker稼働状態とキュー診断.md)。

Phase 3Gでbuiltin baselineのOBSERVED区間予測を追加した。各historical originの`available_at`
締切を再現してTRAIN残差を作り、遅れて到着した履歴や正解値を過去へ遡及させない。分析実行画面
ではOBSERVED snapshotでも区間水準を選択できる。詳細は
[OBSERVED時点再現区間予測](docs/Phase3G_OBSERVED時点再現区間予測.md)。

Phase 3Hで保存済み実験に一致するProvider適合試験jobを追加した。分析実行画面から登録し、Provider別の独立Workerが人工データで固定7項目を実行する。進捗、失敗理由、正式比較可否を画面に表示し、証跡はSHA-256の内容アドレスで保存する。詳細は[Provider適合試験の自動実行](docs/Phase3H_Provider適合試験自動化.md)。

Phase 3Iで同じsnapshotを使う2〜12個のOSSモデルを比較キャンペーンとして一括登録できるようにした。実験、Provider適合試験、予測runを既存の独立Workerキューへまとめて登録し、モデル別進捗と失敗理由を一画面で追跡する。同じrequest keyの再送は同一キャンペーンと決定的run IDへ収束する。詳細は[OSS比較キャンペーン](docs/Phase3I_OSS比較キャンペーン.md)。

Phase 3Jでキャンペーン登録時に主評価期間またはhorizonを固定し、全モデル完了後に独立Workerが保存済みrun・Provider適合記録・truth snapshotから比較結果を自動生成する。待機・実行・成功・失敗、比較ID、再実行をSQLite/PostgreSQLへ保存し、分析実行画面から結果へ移動できる。詳細は[比較キャンペーン自動完了](docs/Phase3J_比較キャンペーン自動完了.md)。

Phase 3KでWindows現場PC向けの「予測OSS分析を起動」を追加した。PC資源を検査してDocker Desktop、データ準備、Baseline、AutoETS、Ridge、適合試験、自動比較Workerを一括起動し、全serviceとProvider heartbeatの確認後に分析画面を開く。TimesFMは高負荷のため空きメモリ検査付きの別ランチャーから追加する。詳細は[Windows予測OSS分析ランチャー](docs/Phase3K_Windows予測OSS分析ランチャー.md)。

Phase 3Lで2〜12件の保存済みdataset snapshotへ同じOSSモデル集合を一括登録し、完了した公式比較指標を期間・評価幅ごとに横断表示する機能を追加した。同じ要求の再送は既存キャンペーンへ収束し、snapshotや比較結果を上書きしない。詳細は[複数条件再テスト](docs/Phase3L_複数条件再テスト.md)。

Phase 3Mで完了した複数条件から、モデルごとの公式掲載率、1位回数、平均順位、順位幅、WAPE平均・振れ幅、絶対Bias平均、最低成功率を自動集計する機能を追加した。条件不足と順位変動を表示するが、採用可否は自動判定しない。詳細は[モデル条件間安定性](docs/Phase3M_モデル条件間安定性.md)。

Phase 3Nで対象品目、モデル設定、評価方式、期間幅が一致する公式比較結果を時系列で照合し、直前期間からのWAPE、絶対Bias、成功率、順位の変化を表示する機能を追加した。同じテスト期間の再実行は最新だけを使い、履歴不足とWAPEの上昇・低下を示すが、採用可否は自動判定しない。詳細は[モデル精度の時系列変化](docs/Phase3N_モデル精度時系列変化.md)。

Phase 3Oで比較可能な精度変化に対し、確認中、データ要因、業務要因、モデル要因、問題なしの判断、根拠、次の対応を版付きで追記するレビュー台帳を追加した。判断時点の指標をSHA-256付き証跡として固定し、認証済みAPPROVE利用者を記録者とするが、採用、昇格、rollbackは自動実行しない。詳細は[モデル精度変化レビュー](docs/Phase3O_モデル精度変化レビュー.md)。

Phase 3Pで精度変化レビューに紐づく対応タスクを追加した。担当者・期限・状態・完了根拠をrevision付きイベントとして追記し、期限超過を現在状態から表示する。APPROVE利用者が登録・更新し、READ利用者が現在状態と履歴を参照する。詳細は[レビュー対応タスク](docs/Phase3P_レビュー対応タスク.md)。

Phase 3Qで`RETEST`対応タスクから既存比較と同じモデル集合・評価方法を使う追加テストを開始できるようにした。request keyと期待revisionで二重登録・競合を防ぎ、成功時はキャンペーンIDと比較IDを完了根拠へ、失敗時は安全な理由を保留履歴へ自動追記する。詳細は[レビュー追加テスト自動連携](docs/Phase3Q_レビュー追加テスト自動連携.md)。

Phase 3Rで追加テスト前後の保存済み公式結果をモデル単位で突き合わせ、WAPE・MAE・RMSE・絶対Bias・成功率・順位の差分と改善・悪化・変化なし・比較不能を表示する。対象モデルの差分は確認後に新しいレビュー判断版へ引き継げる。詳細は[追加テスト差分と再レビュー](docs/Phase3R_追加テスト差分と再レビュー.md)。

Phase 3S-1で既存在庫機能を変更せず、FACTORY / WAREHOUSE、JAN、EXPIRY_BUCKET、Decimal CASE、snapshot_at / known_atを持つinventory foundation domainとadditive schemaを追加した。route別12〜36時間の版付きlead time policy、決定的snapshot ID、PDF抽出の人間承認境界をSQLite / PostgreSQL共通contractとして定義した。CSV取込、Projection、Risk、Shipment Recommendationは未実装である。詳細は[Phase 3S-1実装結果](planning/PHASE3S1_RESULT.md)。

Phase 3S-2で版付きCSV mappingによる正式な入力adapterとvalidationを追加した。UTF-8 / CP932、JAN直接入力・商品コード変換、FACTORY / WAREHOUSE、賞味期限、Decimal CASE、timezone付きsnapshot日時を検証し、異常行を原値なしの固定reasonで隔離する。重複排除、決定的bucket集約、原本数量と正規化数量の照合までを純粋moduleとして実装した。DB保存、job、Worker、API、UIは未接続である。詳細は[Phase 3S-2実装結果](planning/PHASE3S2_RESULT.md)。

Phase 3S-3でCSV変換結果をcontent-addressed snapshot job、SQLite / PostgreSQL store、lease付き独立Workerへ接続した。quarantine、数量照合、正式snapshot、APPROVED / REJECTED decision、job完了を同一transactionで確定する。heartbeat、期限切れ再取得、旧Worker fencing、3回retry、Phase 3S-1 DBからの追加migrationに対応した。詳細は[Phase 3S-3実装結果](planning/PHASE3S3_RESULT.md)。

次のPhase 3S-4では既存認証・認可とAPI共通契約を使い、job登録・状態、隔離理由、数量照合、decision、snapshot一覧、賞味期限順FEFO readのAPIと確認画面を追加する。PDF adapterは3S-5、実データpreflightは3S-6で追加する。
実データ受入は未実施であり、人工データだけで精度や業務効果を保証しない。

## 変更報告

変更ファイル、理由、契約への影響、pytest・ruff・実データ検証、未対応事項を記載する。
契約変更は仕様・コード・テストを同時更新し、テスト削除や期待値の弱体化で通さない。
