# Windows Portable Pilot変更適用Gate 実装結果

## 完成した流れ

手順14で別担当者が`APPROVED_FOR_IMPLEMENTATION`と判断した正式変更案から、固定したPilot Scope、候補版、事前backup参照・SHA-256、適用担当者・時刻を持つ適用計画を作成できる。

開始前はbackup照合、候補版の分離配置、候補設定・API起動・対象データ参照のsmoke testを全件確認する。合格時だけ`PILOT_ACTIVE`とし、不合格時は`BLOCKED`で止める。Pilot後は変更案に固定した受入基準とrollback条件を全件評価し、未達時は`ROLLBACK_REQUIRED`にする。rollback先版は変更案の値に固定し、backup復元と復帰後検査がすべて合格した場合だけ`ROLLED_BACK`にする。

## 実装境界

- Domain、Store、Service、Route、画面JavaScriptを分離した。
- 計画と各判定eventをcontent hash付きの追記型台帳へ保存する。
- revision競合、元承認の失効、保存後改変、不完全な検査、固定した受入・rollback条件の差替えを拒否する。
- SQLiteとPostgreSQLで同じschema・store契約を利用する。
- 担当者画面の手順15から、準備、開始Gate、受入、rollbackを順に操作できる。

## 安全境界

この実装は候補版の配置や設定ファイルの書換えを行わない。`active_assignments`は、別の実行環境がPilot Scopeを照合して候補版を選択するための監査済みread modelである。正式変更案の`application_status`は承認・受入後も`NOT_APPLIED`のままで、現場全体への自動展開を表さない。

受入未達時は`ACCEPTED`にならず、rollback完了まで`ROLLBACK_REQUIRED`を維持する。backup本体、実データ、資格情報はRepositoryと配布物へ含めない。

## 検証

- 承認済み変更案から開始Gate、受入完了までの正常系。
- smoke test不合格による`BLOCKED`と再評価。
- 受入未達からrollback失敗、再試行、完了までの状態遷移。
- 元承認の取消後の操作拒否、revision競合、固定条件、hash改変の検出。
- API、画面資産、非エンジニア向け操作フォームの表示。

## 次工程

Pilot実行環境に候補版resolverを接続し、`active_assignments`と実際に読み込んだ版・範囲の一致を実行時証跡として返す。現場全体への昇格は、Pilot受入完了とは別のリリース承認Gateとして設計する。

