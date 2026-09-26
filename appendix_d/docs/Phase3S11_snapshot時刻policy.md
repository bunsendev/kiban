# Phase 3S-11 snapshot時刻policy運用手順

## 目的

在庫CSVにsnapshot日時列がない場合、ファイル名末尾の`_YYYYMMDD.csv`を日付として使用する。
時刻とtimezoneは推測せず、業務確認済みの値を版付きpolicyとして先に登録する。

生成規則は次のとおりである。

```text
ファイル名の日付 + policyの締め時刻 + policyのIANA timezone → UTC snapshot日時
```

同じファイル名、同じpolicy、同じ入力mappingからは常に同じsnapshot日時が生成される。

## 1. 業務確認

登録前に次を確認する。

- ファイル名の日付が、どの業務時点の在庫を表すか
- その日の正式な締め時刻（秒まで）
- IANA timezone。日本時間は`Asia/Tokyo`

未確認の値、便宜上の午前0時、過去のdry runで使用した09:00を正式値として登録してはいけない。

## 2. policy CSV

UTF-8 CSVを1行で作成する。

```csv
日付取得方式,締め時刻,timezone,確認メモ
FILENAME_YYYYMMDD,HH:MM:SS,Asia/Tokyo,確認済み
```

`HH:MM:SS`は業務確認済みの時刻に置き換える。

## 3. policy登録

SQLiteの例:

```powershell
kiban-snapshot-time-policy-import `
  --sqlite .kiban/inventory.sqlite3 `
  --csv confirmed-snapshot-time-policy.csv `
  --created-by operator-id `
  --reason "在庫締め時刻を業務確認"
```

出力された`policy_version`を保存する。出力には在庫ファイル名や原本値を含めない。

## 4. Inventory Input Mapping

Phase 3S-10のCSVへ次の2列を追加する。

```text
snapshot取得方式,snapshot時刻policy版
```

ファイル名方式では次を設定する。

- `snapshot日時列`: `__snapshot_at__`
- `snapshot取得方式`: `FILENAME_YYYYMMDD`
- `snapshot時刻policy版`: 手順3の`policy_version`

旧形式のmapping CSVは引き続き`COLUMN`方式として登録できる。`COLUMN`方式では、入力CSV内の
`snapshot日時列`が必須であり、policy版を指定しない。

## 5. 入力ファイル名

ファイル名は末尾が次の形式である必要がある。

```text
任意の接頭辞_YYYYMMDD.csv
```

日付が存在しない、実在しない日付、`.csv`の後ろに文字がある場合、Workerは
`CSV_CONTRACT_FAILED`で処理を停止する。ファイル内の時刻やサーバー現在時刻で補完しない。

## 監査・再現性

- policyは内容SHA-256と不変な`policy_version`を持つ。
- mapping版はsnapshot取得方式とpolicy版を含む。
- snapshotは既存どおりmapping版を保持する。
- policyとmappingは同じversionの内容を変更できない。
- 実在庫データや実ファイル名はRepositoryへ保存しない。
