# Phase 2W 在庫正規化結果の承認と採用版

## 目的

Phase 2Vで数量照合した在庫正規化結果について、担当者の技術確認と業務判断を分離し、どのジョブを正式な在庫データとして採用したかを不変履歴で管理する。

## 採用条件

APPROVE権限を持つ利用者だけが`APPROVED`または`REJECTED`を記録できる。`APPROVED`には次の条件をすべて要求する。

- ジョブが`SUCCEEDED`である
- 採用元数量と正規化後数量が一致する
- 隔離行が0行である
- 判断版と理由が入力されている

隔離行がある結果は内容を確認して`REJECTED`を記録し、JAN対応表または原本を修正して新しい正規化ジョブを実行する。却下した結果を後続処理へ渡さない。

## 不変台帳

`inventory_normalization_decisions`は判断ID、ジョブID、判断版、判断、認証主体、理由、時刻を追記保存する。同じ判断版は再利用できず、既存判断を更新・削除しない。リクエストの担当者入力は認証主体で上書きする。

現在の採用版は最新の`APPROVED`判断から導出する。候補への`REJECTED`判断は、すでに採用済みの別ジョブを解除しない。採用版を切り替える場合は、新しいジョブへ新しい判断版で`APPROVED`を記録する。

## APIと画面

- `GET /api/inventory-normalization-jobs`: 最近のジョブをREAD権限で取得する。
- `POST /api/inventory-normalization-jobs/{job_id}/decisions`: APPROVE権限で判断を追記する。
- `GET /api/inventory-normalization-jobs/{job_id}/decisions`: ジョブの判断履歴を取得する。
- `GET /api/inventory-normalization-adoption`: 現在の採用版を取得する。

`/ui/intake`は最近の在庫正規化ジョブ、処理件数、隔離件数、現在の採用版を表示する。成功ジョブを開くと数量照合、結果、判断履歴を確認でき、権限がある利用者は判断版・判断・理由を入力できる。

## 制約

この段階では正式な在庫正規化結果を一意に識別できる。予測datasetへ在庫特徴量として接続する処理は次段階で行う。人工データによる採用試験は実業務データの受入や予測効果を保証しない。
