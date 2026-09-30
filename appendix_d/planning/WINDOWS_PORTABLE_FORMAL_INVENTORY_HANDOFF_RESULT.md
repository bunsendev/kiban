# Windows Portable 正式在庫handoff 実装結果

判定日: 2026-09-30。対象branch: `codex/portable-formal-inventory-handoff`。

## ゴール

担当者が確定した情報を使い、倉庫別の最新在庫を既存Phase 3S正式inventory intake契約へ渡せる形にする。過去の全在庫を一つのSnapshotへ混ぜず、未解決行を推測で補完しない。

## 操作フロー

1. 在庫・出荷ZIPを分析し、JAN等の確認作業を行う。
2. 最新在庫として検出した倉庫ごとに、正式拠点コード、拠点名、在庫基準時刻を入力する。
3. 原本列`明細バラ数`を箱（CASE）として扱うこと、確認者、理由を記録する。
4. ［正式取込用データを準備］を押す。
5. JAN、WAREHOUSE、賞味期限、CASE数量、snapshot日時を既存`inventory_foundation`契約で再検証する。
6. 全行が通った場合だけ、manifestと倉庫別CSVを含むZIPを保存できる。

## 保存・追跡

- 保存先: `Data/FormalInventory/<handoff_id>/`
- 配布候補: `Data/FormalInventory/<handoff_id>.zip`
- package identity: 分析ID、判断履歴SHA-256、拠点・時刻・CASE確認内容から生成する。
- manifest: 原本ZIP SHA-256、原本CSV名・SHA-256、判断履歴SHA-256、mapping version、location master version、候補CSV SHA-256、行数、bucket数、CASE合計を保持する。
- 同じ原本、判断履歴、確認内容の再実行は同じhandoffを返す。

## 安全境界

- 各拠点でファイル名日付が最も新しい在庫CSVだけを対象にする。
- JAN未解決、賞味期限欠損、不正数量が1行でもあれば`BLOCKED`とする。
- `BLOCKED`時はダウンロード可能なhandoff ZIPを生成しない。
- 賞味期限欠損を「確認済み」にしただけでは、EXPIRY_BUCKETを作らない。
- 拠点コード、基準時刻、CASE確認を自動推測しない。
- パッケージ生成は正式Snapshotの最終承認ではない。既存の明示承認Gateを維持する。

## 実データ技術検証

Repository外の`data_b`を使用した。テスト用拠点コードと16:00 JSTを使った変換可能性の確認であり、業務承認ではない。

| 拠点 | 最新在庫日 | 原本行 | 正規化expiry bucket | CASE合計 | 未解決 |
| --- | --- | ---: | ---: | ---: | ---: |
| 加須 | 2025-07-29 | 107 | 89 | 493,066 | 0 |
| 神戸 | 2025-07-29 | 114 | 100 | 510,812 | 0 |

実データおよびテスト生成パッケージはRepositoryへ追加していない。

## モジュール構成

- `portable/api/inventory_handoff.py`: ZIP選択、正規化、Phase 3S validation、manifest・package生成。
- `portable/api/inventory_routes.py`: HTTP境界とダウンロード境界。
- `portable/api/static/inventory.js`: 現場入力と結果表示。
- `portable/api/app.py`: route登録のみ。変換処理を置かず、既存ファイルの肥大化を抑えた。

## 検証

- Portable対象試験: 19 passed
- ruff: passed
- JavaScript構文検査: passed
- `git diff --check`: passed
- 最新ファイル選択、Phase 3S契約合格、UTC変換、ZIP内容、冪等性、賞味期限欠損block、CASE未確認拒否を人工データで確認した。

## 残る業務確認と次工程

1. 加須・神戸の正式拠点コードを現場・管理者が確定する。
2. ファイル名日付に適用する正式な在庫基準時刻を倉庫別に確定する。
3. handoff packageをUnified Inboxの承認済みmapping・scopeへ自動登録するadapterを接続する。
4. Worker成功、数量照合、明示承認後に最新Snapshotを予測更新へ渡す。
