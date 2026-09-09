# 予測OSS比較基盤 — Phase 1A

v2.9基準版とPhase 1Aの実装計画を管理するリポジトリです。

- `appendix_d/`: v2.9基準版をもとにPhase 1Aの契約を追加した予測・比較コア。
- `planning/CODEX_IMPLEMENTATION_INSTRUCTION_v2.9_PHASE1A.md`: 提供された実装指示書。
- `planning/PHASE1A_PLAN.md`: モジュール構成・実装順序・検証計画。

Phase 1A〜1Eはマージ済みです。Phase 1Fでは版付きdataset snapshot・実験catalog、保存済み実験からのrun作成、artifactを復元する組込baseline Workerを統合します。計画は`planning/PHASE1F_PLAN.md`、契約は`appendix_d/docs/Phase1F_実験SnapshotとBaseline統合.md`を参照してください。

## 開発管理

`main`を基準とし、変更は`codex/`で始まるブランチで行います。PRには目的、変更内容、互換性、検証結果、未対応事項を記録します。実データ・資格情報・生成物はコミットしません。

`.gitattributes`で改行の自動変換を無効化し、配布ハッシュがcheckout時に変化しないようにします。

実行コマンドは`appendix_d/README.md`を参照してください。計画文書は配布パッケージの外に置き、基準版のハッシュ対象を変更しません。
