# Phase 3T（Shadow実績接続）後日実績CSV取込

現場のShadow比較で後日判明した数量を、既存の`field_reference_cases`へ接続する。
実績は参考予測・担当者判断と別の追記型eventであり、過去版は上書きしない。
この工程はCSV取込境界のみ。Shadow画面・週次review・正式な補充精度判定は次工程で扱う。

## 入力条件

先に業務確認済みのPilot scope、identity bridgeとreference caseを登録する。
未登録caseへ実績だけを作らない。CSVはUTF-8またはUTF-8 BOM、最大10 MiB・500行で、
1ファイルにつき1つの`source_version`と`known_at`を指定する。列名と順序は次の通り。

```csv
case_id,expected_revision,unit,actual_shipped_quantity,actual_demand_quantity,stockout_quantity,expired_quantity,interwarehouse_transfer_quantity
field-case-...,0,CASE,20,,0,,
```

`unit`は`CASE`のみ。数量欄の空欄は**欠測**、`0`は**確認済みゼロ**として区別する。
少なくとも1つの数量が必要で、負値・float表記の不正値は拒否する。
`actual_shipped_quantity`、`actual_demand_quantity`、欠品、期限切れ、倉庫間移動は異なる指標であり、
空欄を推定値で補完しない。`expected_revision=0`は初回、訂正版は直前のrevisionを指定する。
同じcaseを1ファイルに2回書けない。訂正版は新しい`source_version`と新しいCSV原本を用意する。

CSV原本のバイト列からSHA-256を計算して各eventに保存する。原本内容は台帳へ保存せず、
`known_at`（情報を利用可能になった時刻）と`recorded_at`（台帳記録時刻）を分ける。
全行の形式・case・revision・時点を事前検証し、適用時は全件を単一transactionで追記する。
別処理が先にrevisionを進めた場合は全件を取り消す。

## 操作

まず`--apply`なしで検証する。件数、原本SHA、case IDのみが出力され、数量は表示しない。
問題がなければ同じファイル・source version・known_atに`--apply`を付けて実行する。
PostgreSQLでは`--sqlite <DB>`を`--postgres-dsn <DSN>`へ置き換える。
CLIが見つからない場合は`python -m forecast_provider.field_actuals.cli`を使う。

```powershell
kiban-field-actual-import --sqlite pilot.sqlite3 --csv actual.csv --source-version actual-2026-09-28-v1 --known-at 2026-09-28T15:00:00+09:00
kiban-field-actual-import --sqlite pilot.sqlite3 --csv actual.csv --source-version actual-2026-09-28-v1 --known-at 2026-09-28T15:00:00+09:00 --apply
```

同じCSVの再適用はrevision不一致で停止する。現場原本・実績数量・資格情報はRepositoryへcommitしない。
この機能の人工データ試験だけでは実データの意味・取得元・確定時刻の業務受入を示さない。
