# Phase 1H 出荷行正規化と数量照合

Phase 1Hは、Phase 1GでSHA-256付き不変保存した原本を、版付き列mappingに従って出荷行へ正規化する。列名や日付形式を推測しない。mappingは正規化JSONのhashで識別し、同じ定義は同じIDになる。

mappingは出荷日、JAN、商品名、数量、単位、center、行区分、利用可能時刻の各列、許可単位、日付形式、`FULL`/`DELTA`、`ASSUMED`/`OBSERVED`を固定する。一つの原本列を複数の意味へ割り当てない。OBSERVEDではtimezone付きavailable_at列を必須としUTCで保存する。ASSUMEDでは出荷日の翌日00:00 JSTを生成する。

`POST /api/mappings`でmappingを保存し、`POST /api/normalizations`は原本IDとmapping IDだけを受け付ける。HTTP request内ではCSVを処理しない。`kiban-normalization-worker`が保存原本のchecksumを再検証してから処理する。

正規化行は原本ID・行番号、center、出荷日、原JAN、原商品名、数量、単位、行区分、available_atを保持する。JANは文字列のまま扱い、先頭0を落とさない。日付不正、非数・非有限・負数量、不明単位、返品・取消、不明行区分は原値と理由を残して隔離し、0への補正や相殺をしない。

数量照合はparse可能数量を採用数量と隔離数量に分け、未説明差分を明示する。品質APIは原本状態、文字コード、job・行状態、center×月の採用数量、隔離理由件数を返す。

訂正版候補は自動採用しない。`POST /api/source-selections`でlogical path、原本ID、decision version、担当者、理由を保存して初めて正規化できる。選択履歴は`GET /api/source-selections`で取得でき、新版選択後は旧原本を別mappingで新規処理できない。

この段階ではJAN名寄せ、返品・取消の業務対応、日次集計、予定ファイルに基づく0/欠測判断を行わない。後続処理は採用行と隔離・照合結果を入力にする。
