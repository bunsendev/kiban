# Phase 3T Pilot変更適用Gate

## 目的

手順14で`APPROVED_FOR_IMPLEMENTATION`となった正式変更案を、固定したPilot Scopeだけで安全に試すための運用契約である。正式変更案、適用計画、開始判定、受入判定、rollback判定を分離し、誰が、いつ、何を根拠に進めたかを追跡できる。

このGateはモデル、特徴量、policy、現場全体の設定ファイルを自動変更しない。`PILOT_ACTIVE`または`ACCEPTED`は、固定した範囲で候補版を利用できるという監査済みの状態である。実行環境は`active_assignments`を読み、対象範囲を照合したうえで候補版を選ぶ。

## 操作手順

1. 手順15で承認済み正式変更案を選ぶ。
2. Pilot用の候補版、事前backupの参照名とSHA-256、適用担当者、準備基準日時を入力する。
3. ［Pilot適用計画を準備］を押す。正式変更案の適用範囲、受入基準、rollback条件、rollback先版は変更できない。
4. 事前backupをSHA-256まで照合し、候補版をPilot領域へ分離配置する。
5. 候補設定、API起動、Pilot対象データ参照のsmoke testを実施し、各根拠を入力して開始Gateを評価する。
6. すべて合格した場合だけ`PILOT_ACTIVE`になる。不合格は`BLOCKED`となり、修正後に同じ計画で再評価する。
7. Pilot期間後、正式変更案に固定した受入基準とrollback条件を全件評価する。
8. 全受入基準が合格し、rollback条件が1件も発生しなければ`ACCEPTED`になる。それ以外は`ROLLBACK_REQUIRED`になる。
9. rollbackでは、固定したrollback先版と事前backupを使い、旧設定への復帰、API再起動、既存データ参照を確認する。全検査の合格後に`ROLLED_BACK`となる。

## 状態遷移

| 現在状態 | 操作 | 結果 |
|---|---|---|
| `PREPARED` / `BLOCKED` | 開始Gate評価 | 合格=`PILOT_ACTIVE`、不合格=`BLOCKED` |
| `PILOT_ACTIVE` | 受入評価 | 合格=`ACCEPTED`、未達=`ROLLBACK_REQUIRED` |
| `PILOT_ACTIVE` / `ROLLBACK_REQUIRED` | rollback評価 | 合格=`ROLLED_BACK`、未達=`ROLLBACK_REQUIRED` |

元の正式変更案の承認が取り消された、または新しいrevisionへ更新された場合、その計画の次の遷移を拒否する。各更新は`expected_revision`を使い、同時更新の上書きを防ぐ。

## 保存と監査

- `field_change_applications`: 候補版、固定したPilot Scope、承認revision、backup参照・SHA-256、準備担当者・時刻を保存する不変レコード。
- `field_change_application_events`: Gate、受入、rollbackの判定、担当者、理由、検査根拠をrevision付きで追記する。
- 計画とeventは正規化内容からSHA-256を計算し、読込時に再計算する。保存後の改変はエラーにする。
- 正式変更案の`application_status`は`NOT_APPLIED`のまま維持する。
- 実データ、backup本体、資格情報はRepositoryや配布物へ格納しない。

## モジュール境界

- `field_learning/change_application_domain.py`: 不変な計画・eventとhash生成。
- `field_learning/change_application_store.py`: SQLite/PostgreSQL共通の追記台帳。
- `portable/api/change_applications.py`: 状態遷移、安全条件、元承認の有効性確認。
- `portable/api/change_application_routes.py`: HTTP境界。
- `portable/api/static/change-applications.js`: 非エンジニア向けの入力・確認画面。

この分割により、将来の候補版配置処理や実行時resolverは`active_assignments`を契約として追加でき、監査台帳とUIを肥大化させずに拡張できる。

