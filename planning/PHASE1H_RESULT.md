# Phase 1H 実装結果

## 結果

Phase 1Gで不変保存した原本を、内容アドレス方式の列mappingで出荷行へ正規化する経路を追加した。APIはmapping・原本選択・正規化jobだけを管理し、CSV処理は独立Workerで行う。

## 正規化契約

- mappingに日付・JAN・商品名・数量・単位・center・行区分・available_atの列と形式を固定。
- 原JANを文字列で保存して先頭0を維持し、原本IDと行番号から追跡可能。
- 日付不正、非数・非有限・負数量、不明単位、返品・取消を理由付きで行単位隔離。
- ASSUMEDは翌日00:00 JST、OBSERVEDはtimezone必須でUTC保存。
- Workerが保存原本のSHA-256を再検証し、改ざん時は行を保存せずjobを失敗。

## 訂正と品質

- 訂正版候補はdecision version・担当者・理由付きの明示採用後だけ正規化可能。
- 新版選択後に旧原本を別mappingで処理することを抑止し、選択履歴APIを提供。
- parse可能・採用・隔離数量と未説明差分を保存。
- 原本状態、文字コード、job・行状態、center×月数量、隔離理由を品質APIで集計。

## 構成

contract、mapping domain、CSV processor、SQLite store、PostgreSQL claim、API route、Worker CLIを分割した。既存API本体から取込・正規化routeも分離した。

## 検証

最終件数は`appendix_d/test_results.txt`へ記録する。PostgreSQL実DBとCompose実起動はDocker/PostgreSQLがある環境で追加確認する。

## 次段階

正規化済み行を入力に、商品名比較、JAN変更候補、承認履歴、有効期間を持つJAN名寄せを実装する。その後、取扱期間・予定ファイル完全性・日次状態確定へ進む。
