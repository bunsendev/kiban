# Phase 3T Windows Portable Pilot停止Gate

`PAUSE_PILOT`という担当者判断を、新規予測だけに効く安全な停止へ接続する。判断の保存だけでは停止せず、手順15-4で担当者が影響を確認して確定する。

確定時は評価、Runtime週次評価、判断、適用計画のID・SHA-256・revisionを`PILOT_PAUSED`イベントへ固定し、状態を`PILOT_ACTIVE`から`PAUSED`へ一度だけ進める。古い評価判断、別の評価、競合revision、改変された証跡は拒否する。

`PAUSED`後の新規正式予測Runは候補版を選ばず、Baselineと理由`PILOT_PAUSED`をRuntime選択証跡へ記録する。停止前に固定したRunとRuntime選択証跡、業務データ、候補manifest、正式設定は変更しない。候補版の復元や削除を伴うrollbackとは別の操作である。

既存SQLiteは起動時にイベント表の制約だけを拡張し、既存行を同一transactionで移送する。新規DBとPostgreSQLは更新済みschemaを使用する。
