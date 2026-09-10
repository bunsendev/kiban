# 予測OSS比較基盤 — v2.9

v2.9基準版から段階的に拡張する予測・比較基盤の実装と計画を管理します。

- `appendix_d/`: v2.9基準版をもとにPhase 1A〜1Lを追加した予測・比較基盤。
- `planning/CODEX_IMPLEMENTATION_INSTRUCTION_v2.9_PHASE1A.md`: 提供された実装指示書。
- `planning/PHASE1*_PLAN.md`: 各Phaseのモジュール構成・実装順序・検証計画。
- `planning/PHASE1*_RESULT.md`: 各Phaseの実装結果・検証・未対応事項。

Phase 1A〜1Kはマージ済みです。共通予測契約、artifact保存、再開可能なrun台帳、PostgreSQL lease、API/Worker、dataset・実験catalog、原本取込、出荷行正規化、JAN名寄せ・取扱期間、予定完全性・6種類の日次状態、少数実品目受入契約までを実装しました。

Phase 1Kでは、実データ3〜5品目を対象とする受入case、技術判定、品質レポート、業務判断履歴を追加しました。匿名データは`DRY_RUN`に固定し、実データ受入済みとは扱いません。計画は`planning/PHASE1K_PLAN.md`、契約は`appendix_d/docs/Phase1K_少数実品目受入.md`を参照してください。

Phase 1Lでは、重要品目候補の数量・構成比・変動係数・出荷0率・欠損率・JAN変更・業務指定を算出し、対象centerと理由を持つ初期3〜5または拡大20〜50品目の`selection_version`を不変保存する機能を追加しました。計画は`planning/PHASE1L_PLAN.md`、契約は`appendix_d/docs/Phase1L_重要品目候補と選定版.md`を参照してください。

実データはまだ提供されていないため、3〜5品目での実受入、元数量照合、業務承認、全3年の20〜50品目確定は未実施です。実データ到着前に進める場合は、2つ目のOSS候補と共通契約適合試験へ進みます。

## 開発管理

`main`を基準とし、変更は`codex/`で始まるブランチで行います。PRには目的、変更内容、互換性、検証結果、未対応事項を記録します。実データ・資格情報・生成物はコミットしません。

`.gitattributes`で改行の自動変換を無効化し、配布ハッシュがcheckout時に変化しないようにします。

実行コマンドは`appendix_d/README.md`を参照してください。計画文書は配布パッケージの外に置き、基準版のハッシュ対象を変更しません。
