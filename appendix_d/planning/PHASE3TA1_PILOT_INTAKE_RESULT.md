# Phase 3T-A-1 実装結果

## 目的と達成内容

前工程で定義したPilot契約を、業務確認済みCSVから版付きで登録し、既存Inventory Snapshot
Workerに接続した。原本全体から対象行を選び、対象外の件数・CASE数量を残す。対象内異常は
隔離し、部分snapshotを正式な全量snapshotと混同しない。

## 実装

- `pilot_scope/imports.py`, `pilot_scope/intake.py`: 確認済みScopeと原本値selectorを検証。
- `inventory_forecast_bridge/imports.py`: 予測identity bridgeの確認済みCSV登録。
- `pilot_gate_import.py`: Scope、bridge、Intakeの登録とscope付きjobの投入。
- `inventory_foundation/service.py`, `worker.py`: 原本SHA検証後に対象を選択し、既存validationで隔離・snapshot生成。
- `pilot_scope/schema.sql`, `store.py`, Inventory store: 版、対象外監査、部分参照を同一DBに保存。
- `inventory_foundation/read_service.py`: 通常as-ofから部分snapshotを除外し、明示scope版でのみ取得。

SQLiteとPostgreSQLの既存job/snapshot tableへnullable列を追加する。通常jobのIDとsnapshot IDは
変えない。部分jobだけscope・Intake版をIDとsnapshot headerに含める。旧データにはNULLを維持する。

## 検証と制約

人工CSVで対象内、対象外、隔離、数量照合、再現性、CLI登録、Worker、read modelを確認する。
全体回帰と静的検査は`test_results.txt`に記録する。
実在庫・予測identityの業務確認、正式APPROVED、実PostgreSQL接続は本工程では行っていない。
次工程はAPPROVED部分snapshotと需要予測の版付き接続、およびWarehouse Projection。
