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

- 固定学習と月次再学習を混ぜない。現在のrunnerは固定方式。
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

次は実データ3〜5品目でPhase 1Kを実行し、全3年の重要品目選定を確定する。実データ到着前に進める場合は、2つ目のOSS候補と共通契約適合試験へ進む。
実データ受入は未実施であり、人工データだけで精度や業務効果を保証しない。

## 変更報告

変更ファイル、理由、契約への影響、pytest・ruff・実データ検証、未対応事項を記載する。
契約変更は仕様・コード・テストを同時更新し、テスト削除や期待値の弱体化で通さない。
