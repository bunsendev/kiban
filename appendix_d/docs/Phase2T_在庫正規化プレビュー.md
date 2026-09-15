# Phase 2T 在庫正規化プレビュー

## 目的

保存済みの商品コード・JAN対応表を使い、在庫CSVを日付、JAN、数量、倉庫、単位へ変換できるか、
台帳更新前に確認する。

## 入力

- ZIP展開先の相対prefix
- `product-jan-<sha256>`形式の保存済みJAN対応表ID
- 担当者が確認した固定数量単位
- 1ファイルあたり1〜1,000行の検査行数

## 変換候補

- 日付: ファイル名末尾の`_YYYYMMDD.csv`
- JAN: `商品コード`を保存済み対応表で変換
- 数量: `明細バラ数`。有限の非負数だけを採用
- 倉庫: `明細倉庫コード`
- 単位: 画面で指定した固定値

## 隔離理由

`INVENTORY_DATE_INVALID`、`PRODUCT_MAPPING_MISSING`、`QUANTITY_INVALID`、`CENTER_MISSING`を
行単位で判定し、理由別件数だけを返す。すべてのサンプル行が合格した場合は
`READY_FOR_INVENTORY_NORMALIZATION`、それ以外は`REVIEW_REQUIRED`となる。

レスポンスは件数、設定、内容アドレス方式の証跡IDだけを含み、商品名、JAN、数量、倉庫の原値を
含めない。本機能は正規化プレビューであり、在庫行台帳への本登録ではない。
