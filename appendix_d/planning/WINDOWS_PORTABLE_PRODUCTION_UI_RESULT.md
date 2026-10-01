# Windows Portable 正式予測更新UI 実装結果

## ゴール

担当者がWindows Portableの一画面で、確認済み日次buildの正式予測Run登録、処理状況、
完了したPOINT予測、在庫見通しまで確認できるようにする。

## 操作フロー

既存の手順1〜6に次を追加した。

1. 手順7「正式予測を更新」で登録者、理由、対象・除外系列の確認を入力する。
2. 「正式予測を更新」を押すと既存Dataset Snapshot、Experiment、Run queueへ登録する。
3. 画面は登録済み、計算中、完了、失敗を既存Run台帳から自動更新する。
4. 完了後、系列ごとの7日・14日POINT予測を表示する。
5. 「在庫見通しを確認」で既存Warehouse Projection契約を実行する。

## 構成

- `production.js`: 手順7の表示、登録、進捗poll、結果、在庫見通しを担当する。
- `production_worker.py`: 既存`BuiltinBaselineExecutor`と`resume_run`を別daemon threadで実行する。
- `production_handoff.py`: Run台帳の現在状態・POINT結果をread model化し、既存
  `WarehouseProjectionService`へ接続する。

API request内では学習・予測を実行しない。登録後に独立したworker threadが処理する。
Portable終了時にはprocessと一緒に終了し、再起動後はresume APIで既存queueを再開できる。

## 安全条件

- 予測対象外系列を0へ変換せず、画面と受渡し記録に残す。
- 同一buildの再登録は同じRun IDへ収束する。
- POINTとQUANTILEを混ぜず、画面は確定POINTだけを集計する。
- Warehouse Projectionは既存のPilot Scope、承認済み在庫、identity bridge、14日完全性を
  再検証する。不足条件があれば理由付きで停止する。
- 実データ・資格情報はRepositoryへ保存しない。

## 検証

人工データ10系列で、登録、非同期Worker完走、140 POINT、再送、再起動後の状態取得、
10商品のWarehouse Projectionを確認した。欠測1系列は対象外として保持し、受渡し記録の
改変は拒否する。

## 次のゴール

複数倉庫の個別Pilot Scopeを束ねるProjection read modelと、担当者が不足・賞味期限・偏在を
一画面で確認する日次業務サマリーを追加する。
