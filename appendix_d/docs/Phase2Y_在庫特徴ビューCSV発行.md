# Phase 2Y 在庫特徴ビューの再現可能なCSV発行

## 目的

Phase 2XでREADYとなった時点安全な在庫特徴ビューを、後続分析へ受け渡せる固定形式のCSVとして発行する。出力内容、順序、文字コードを固定し、内容ハッシュと系譜IDを一緒に提供する。

## 出力契約

`GET /api/inventory-feature-views.csv`へJAN名寄せ版とtimezone付き参照時点を指定する。EXPORT権限を要求し、内部でPhase 2Xと同じ採用時点・JAN有効期間の検査を再実行する。READYでない場合は409とし、部分的なCSVを作らない。

CSVはUTF-8 BOM付き、CRLF改行で、次の固定列を持つ。

- `feature_view_id`
- `canonical_product_id`
- `center_id`
- `ds`
- `unit`
- `inventory_quantity`
- `available_at`

原JAN、商品名、元ファイル名、絶対path、対応表の原値は含めない。行はPhase 2Xの決定的な順序を維持する。

## 同一性確認

レスポンスは`X-Kiban-Feature-View-ID`と`X-Content-SHA256`を返す。SHA-256はBOMを含む実際のダウンロードbytesから算出する。同じ採用判断、ジョブ、JAN名寄せ版、UTC参照時点では同じビューID、CSV、checksumになる。

## 画面

`/ui/intake`で特徴ビューがREADYになった場合だけ「在庫特徴CSVをダウンロード」を表示する。ファイル名には特徴ビューIDを含める。

## 対象範囲

本CSVは分析用の受渡成果物であり、予測datasetへの自動結合、本番システムへの書戻し、在庫最適化、自動発注を実行しない。モデル特徴量として利用する場合は別の受入条件と比較試験が必要である。
