# Phase 3T-A-0 Pilot Gate Foundation

## 目的

現場検証を全商品一括で始めず、業務承認した10〜20商品だけを安全にShadow検証するための基盤である。
対象外データを異常として扱わず、対象内の異常だけを停止条件にする。一方で、対象外を無言で削除せず、
原本との件数・数量照合へ残す。

## 登録順

1. `build_pilot_scope`で承認済みJAN×WAREHOUSEと適用期間を版にする。
2. `build_inventory_forecast_bridge`でJAN / warehouseと予測IDの対応を版にする。
3. 在庫CSVを対象内、対象外、対象内隔離へ分類し、`build_scope_reconciliation`で照合する。
4. 既存inventory snapshotと照合を`build_scoped_snapshot_reference`で結ぶ。
5. `FieldLearningService.register_reference_case`でSHADOW参考値を記録する。
6. 担当者の独立判断を`record_operator_decision`へ追記する。
7. 後日実績を`record_actual_outcome`へrevision付きで追記する。

## 運用上の注意

- `PILOT_PARTIAL`は全在庫snapshotではない。
- scope外件数と数量も監査値として保存する。
- 対象内隔離が1件でもあれば、その照合は正式参照にしない。
- Shadowのsystem referenceは参考値であり出荷指示ではない。
- `known_at`は情報を利用できた時刻、`recorded_at`は台帳へ書いた時刻である。
- 欠測数量は`None`、実際に0と確認した数量だけDecimal `0`にする。
- 担当者判断とActualからモデルやpolicyを自動変更しない。

## 現在の制約

CSV登録CLI、認可API、現場UI、既存Snapshot WorkerのPilot自動抽出は未接続である。業務確認済みの実JAN、
倉庫、canonical product、forecast centerを入手した後、専用adapterで正式版を登録する。
