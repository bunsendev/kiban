# Windows Portable Unified Inbox・正式在庫Snapshot 接続結果

判定日: 2026-10-01。対象branch: `codex/portable-unified-inbox-snapshot`。

## ゴール

Portable版で担当者が確認した正式在庫候補を、既存の正式取込経路へ安全に接続する。候補CSVをそのまま正式在庫にせず、Pilot Scope、Unified Inbox、既存Worker、数量照合、担当者の明示承認を順に通す。

## 完成した操作フロー

1. ZIPを分析し、JAN・賞味期限・数量の未解決項目を確認する。
2. 倉庫コード、在庫基準時刻、原本列`明細バラ数 = CASE`を確認して正式在庫候補を準備する。
3. 倉庫ごとに10〜20商品のJANをPilot対象として選び、確認者と理由を入力する。
4. ［Unified Inboxへ登録］で版付きLocation、Input Mapping、Pilot Scope、Pilot Intake、Inbox Policyを保存する。
5. 候補CSVのSHA-256を再検証し、対象JANだけのCSVをUnified Inboxへ投入する。
6. 既存Inventory Snapshot Workerで再検証し、対象内外の行数・CASE数量を照合する。
7. 隔離0件、数量一致、最新ジョブである場合だけ、担当者がSnapshotを明示承認する。

同じhandoff、担当者、理由、選択JANは同じ登録IDとなり、再操作で重複登録しない。

## モジュール構成

- `portable/api/formal_pipeline_contracts.py`: 担当者入力、候補SHA、Pilot契約、Inbox Policyの構築。
- `portable/api/formal_pipeline.py`: Unified Inbox、Worker、数量照合、Snapshot承認の編成と永続化。
- `portable/api/formal_pipeline_routes.py`: 参照、登録、承認のHTTP境界。
- `portable/api/static/inventory.js`: JAN選択、登録結果、照合結果、承認操作。
- `portable/api/app.py`: route登録だけを担当する。

処理を既存の大きなAPIファイルへ追加せず、契約構築、業務処理、HTTP境界、画面を分離した。

## 保存先と監査情報

- 正式在庫候補: `Data/FormalInventory/<handoff_id>/`
- 登録記録: `Data/FormalInventory/Registrations/<registration_id>.json`
- Unified Inbox原本・台帳: `Data/Inbox/`
- Location、Mapping、Scope、Intake、Job、Snapshot、Decision: `Data/State/formal-pipeline.sqlite3`

原本候補のSHA-256が変わった場合は登録を拒否する。担当者、理由、選択JAN、policy・mapping・location・scope・intake版、job、snapshot、decision revisionを追跡できる。

## 安全境界

- 倉庫ごとのPilot対象は10〜20の13桁JANに限定する。
- 画面の初期候補表示は選択支援であり、担当者の確認チェックがなければ登録しない。
- 候補に存在しないJAN、倉庫の選択漏れ、改ざんされた候補CSVを拒否する。
- 隔離行、数量不一致、旧ジョブ、複数Snapshotは承認できない。
- 予測値や欠測値を生成して在庫を補完しない。
- 承認済みInventory Snapshotだけで「予測更新完了」と表示しない。

## 検証

- Portable統合試験: 22 passed。
- 10 JAN×1倉庫の候補について、登録、Worker成功、10行受入、隔離0行、原本55 CASEと正規化55 CASEの一致、Snapshot承認を確認した。
- アプリ再起動後も登録、ジョブ、Snapshot、承認状態を同じSQLiteから復元できることを確認した。
- 未確認のPilot Scopeと9 JANの登録を拒否し、登録記録を作らないことを確認した。

## 未接続の次工程

承認済み在庫Snapshotは完成したが、正式な出荷実績の日次build、Forecast run、JAN・倉庫identity bridgeとの自動接続はこの工程に含めていない。画面は`WAITING_FOR_FORMAL_SHIPMENT_DAILY_BUILD`を表示する。次工程では、承認済みShipment daily buildを検出し、同じPilot ScopeのForecast runを作成して結果画面へ渡す。架空の出荷実績や確定ゼロを生成して先へ進めない。

実データはRepositoryへ追加していない。
