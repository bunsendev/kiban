# Phase 3T-A 倉庫在庫Projection 実装結果

## 完成した範囲

Pilot部分在庫snapshotと予測runを明示版・as-of条件で接続し、JAN×倉庫の14日日別gross在庫、
7日・14日需要、最初の不足日、累積不足量を決定的に算出する。計算coreは
`warehouse_projection/domain.py`、読取・Gateは`service.py`、運用入口は`cli.py`に分離した。

予測runに`finished_at`を追加し、旧runは移行時刻より前の計算へ混入させない。
run台帳からは対象origin・Pilot seriesのPOINT値だけを読む。通常の在庫・予測runの既存IDと
既存結果は変更しない。

## 安全境界

APPROVED、scope照合、bridge有効期間、run完了時刻、origin cutoff、14日完全性、CASE、
商品identityの一致を確認し、不足や曖昧さがあれば停止する。欠測は0に変換しない。
出力は`SHADOW`のgross計算で、賞味期限の将来消化・工場供給・補充を含まない。

## 検証・次工程

人工10商品×14日の在庫・予測台帳を使い、同一入力の同一ID、不足日、7日・14日合計、
不完全horizon・後知恵runの停止、旧runの保守的移行、CLI出力を確認した。
全体回帰と静的検査は`test_results.txt`に記録する。実データ・実PostgreSQLでの業務受入は未実施。
次はPhase 3T-Bの賞味期限bucket別FEFO Simulation。
