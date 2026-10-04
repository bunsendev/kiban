# Windows Portable 実行時候補版選択 実装結果

## 完成した範囲

- `active_assignments`と正式予測Run登録をPilot Scope版で接続した。
- Scope外はBaseline、Scope内は有効な候補manifestとの完全一致時だけ候補版を選ぶ。
- 複数割当、失効承認、履歴改変、manifest不在・重複・hash/契約不一致、未対応adapterを実行前に停止する。
- 異なる実行設定を1つのProduction Runへ混在させない。
- 選択結果をSQLiteの追記型台帳とProduction受渡し記録へ保存し、content hashで再検証する。
- 担当者画面の手順16とread-only APIで、配置候補と選択履歴を確認できる。
- Gateへ候補manifest SHA-256を追加し、確認済みファイルを実行時に再照合する。

## モジュール境界

- `runtime_assignment_domain.py`: 不変な選択証跡と入力契約
- `runtime_assignment_store.py`: SQLite/PostgreSQL共通の追記型保存
- `runtime_assignments.py`: Scope、承認、manifest、adapterの解決
- `runtime_assignment_routes.py`: read-only表示API
- `production_handoff.py`: 解決済み単一設定を既存Experiment/Runへ渡すadapter
- `runtime-assignments.js`: 担当者向け表示

候補解決は予測計算やHTML生成から分離しました。新しいProviderを許可する場合はresolverの対応設定契約と既存Provider Workerを同時に追加し、manifestだけで任意実行できない構成を維持します。

## 安全性と互換性

- DB変更は追加tableだけで、既存適用計画・予測Runを変更しない。
- 適用計画がない既存フローは同じ組込Baselineへ解決される。
- 保存済み受渡し記録は再送時に再利用され、実行中の設定を後から切り替えない。
- Gateにmanifest SHAがない旧適用計画は候補版として使わず停止する。
- SHADOW制約を維持し、出荷指示や正式設定へ自動昇格しない。
- 実データ、API key、署名秘密鍵は配布物とRepositoryへ含めない。

## 検証項目

- 正確なScope・承認・manifestによる候補版選択
- Scope外のBaseline維持
- manifest改変、複数割当、異なる設定混在の停止
- 追記型証跡と改変検出
- API/UI asset
- 既存Portable一連フローとProduction Worker完走
- Ruff、全体pytest、JavaScript構文、配布SHA一覧

## 次工程

候補版に新しいOSS Providerやパラメータを実際に割り当てる場合は、Provider Workerの実装、固定artifact、資源上限、smoke test、rollback可能な配布単位を追加します。その後、同一ScopeのBaseline/候補比較と担当者の受入結果を既存の週次改善台帳へ戻します。
