# Windows Portable 複数倉庫・日次業務サマリー 実装結果

## ゴール

担当者がWindows Portableの一画面で、複数倉庫の正式予測、現在庫、7日・14日需要、
不足、賞味期限リスク、確認対象を日次確認できるようにする。

## 操作フロー

既存の手順7で正式予測が完了すると、手順8「倉庫別の日次業務サマリー」を表示する。

1. 出荷時に必要な残存日数と賞味期限の注意期間を確認する。
2. 条件を業務確認したことを明示して「日次サマリーを作成」を押す。
3. 倉庫別集計とJAN別明細で、現在庫、需要、不足、期限注意を確認する。
4. 計算できない倉庫と予測対象外系列は、理由コード付きの別欄で確認する。

画面の数量は`SHADOW`の参考値であり、正式な出荷指示ではない。14日不足があるJANは
補充の確認候補として表示するが、リードタイムと安全在庫policyが未確定のため推奨出荷量は
生成しない。

## 構成

- `production_projection.py`: 複数Pilot ScopeのProjection、FEFO、倉庫別集計、保存済み
  サマリーの改変検査を担当する。
- `production_handoff.py`: Dataset Snapshot、Experiment、Run登録に限定した。
- `production.js`: Run進捗と日次サマリーの入力・表示を担当する。
- `POST /api/formal-forecast/{build_id}/daily-summary`: 明示確認した期限policyで内容アドレスの
  サマリーを作成する。

## 維持する契約

- 倉庫ごとのPilot Scope、承認済み在庫Snapshot、identity bridge、POINT予測を既存Serviceで
  再検証する。
- 1倉庫の計算失敗で他倉庫の結果を失わず、`PARTIAL`と理由コードを返す。
- 予測対象外系列を0にせず、`excluded_series`へ保持する。
- POINTとQUANTILEを混在させない。
- 同一build・同一期限条件・同一確認者・同一理由は、再起動後も同じ保存済みサマリーを返す。
- サマリーはSHA-256で検証し、改変時は表示しない。
- 実データと資格情報をRepositoryへ保存しない。

## 検証

人工データの2倉庫、各10 JAN、合計20系列で、正式在庫承認、日次build、Production Run、
複数Projection、FEFO、倉庫集計を一連で実行した。不足候補と賞味期限注意を表示し、再起動後の
同一結果、保存サマリーの改変拒否を確認した。

Portable・Projection・FEFO対象試験は41件成功した。最終の全体回帰と配布ハッシュ件数は
`test_results.txt`を参照する。

## 次のゴール

工場在庫、生産予定、工場から倉庫までの12〜36時間のroute別lead time、安全在庫policyを
接続し、到着時点在庫に基づく推奨出荷量を再現可能なDecision Engineとして計算する。
