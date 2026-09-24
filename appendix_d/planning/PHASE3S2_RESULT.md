# Phase 3S-2 実装結果

実施日: 2026-09-24  
対象Repository: `bunsendev/kiban`  
基準Branch: `main`  
基準Commit: `0ac3c88`  
実装Branch: `codex/phase3s2-csv-validation`

## 1. 完成した範囲

Phase 3S-1のinventory foundationを利用し、版付きCSV mappingから正式snapshot候補を作る直前までの純粋な変換処理を追加した。

```text
CSV bytes
  ↓ encoding / delimiter / header contract
安全なparsed row（raw値はreprへ出さない）
  ↓ product / location / expiry / quantity / snapshot_at validation
JAN × FACTORY/WAREHOUSE × EXPIRY_BUCKET × Decimal CASE
  ↓ deterministic aggregate
bucket候補 + quarantine metadata + 数量照合
```

DB保存、job lease、APPROVED / REJECTED decision、API、Worker、UIはPhase 3S-3以降へ分離した。既存の取込、在庫正規化、予測、比較処理から暗黙には呼び出されない。

## 2. 追加module

| module | 責務 |
|---|---|
| `csv_adapter.py` | 版付きencoding・delimiter・headerでCSVを解析し、source SHA-256と行SHA-256を計算 |
| `references.py` | location master versionとproduct mapping versionを固定した参照解決 |
| `validation.py` | JAN、拠点、賞味期限、Decimal数量、timezone付きsnapshot日時の検証とbucket集約 |
| `reconciliation.py` | 原本上でCASEとして解釈可能な数量と正式候補数量の照合contract |

CSV読取、master参照、業務validation、数量照合を分けたため、Phase 3S-3のservice / store / Worker接続で1ファイルへ処理を集中させる必要がない。

## 3. CSV契約

- encodingはmappingで明示した`utf-8`、`utf-8-sig`、`cp932`だけを許可する。
- delimiterはmappingの1文字を使用する。
- header行は1行目に固定せず、mappingの`header_row`を使用する。
- JANまたは商品コード、location、賞味期限、数量、snapshot日時の列を必須とする。
- 列不足、重複header、decode失敗、CSV構文不正は固定`InventoryCsvErrorCode`で処理を停止する。
- エラー文字列には列名、原値、ファイル名、pathを含めない。
- 空行は対象外とし、列数不一致行は`ROW_SHAPE_INVALID`で隔離する。

CSV全体の契約不成立と、読み取れた個別行の異常を分けた。前者は入力mappingまたは原本の修正が必要なため処理を停止し、後者は再確認可能なquarantineとして返す。

## 4. 商品識別

### JAN直接入力

- JAN-8 / JAN-13の桁数、数字、check digitを検証する。
- 欠損は`JAN_MISSING`、不正は`JAN_INVALID`とする。
- 既存canonical productを利用できるよう、JANからcanonical IDを引く任意の参照を持つ。
- canonical IDが未解決でもJAN自体が有効ならbucket候補にできる。

### 商品コード入力

- mappingへ`product_mapping_version`を必須とする既存契約を使用する。
- 指定version以外の商品対応は利用しない。
- 対応なしは`PRODUCT_MAPPING_MISSING`、同じ商品コードが複数のJANまたはcanonical IDへ解決される場合は`PRODUCT_MAPPING_AMBIGUOUS`とする。

## 5. location

- mappingの`location_master_version`に一致するmasterだけを参照する。
- snapshot日がlocationの有効期間内であることを確認する。
- `FACTORY`と`WAREHOUSE`を別のlocation IDとして保持する。
- 欠損、不明、曖昧、V1外typeを固定reasonで隔離する。
- 同名や表示名では解決せず、版付きlocation codeを使用する。

## 6. 賞味期限・数量・単位

- 賞味期限は`YYYY-MM-DD`、`YYYY/MM/DD`および同形式の日付時刻を日付へ正規化する。
- 欠損と不正値を分けて隔離する。
- snapshot日時より前の賞味期限も失わない。正式snapshot化時にPhase 3S-1の`EXPIRED_AT_SNAPSHOT`が付く。
- 数量はbinary floatへ変換せず、Decimalで扱う。
- 整数、小数、3桁区切りを検証し、欠損、不正、負数を分ける。
- mappingで`normalized_unit=CASE`が明示されている場合だけ処理する。
- `明細バラ数`という原本列名と、業務単位`CASE`を別のmapping項目として維持する。
- 数量換算や丸めは行わない。

## 7. snapshot日時

- ISO 8601のtimezone付き日時だけを受け付け、UTCへ正規化する。
- timezoneなしは`SNAPSHOT_AT_INVALID`とする。
- 1つのCSV内に複数のsnapshot日時がある場合、任意の時刻を選ばず、該当行を`SNAPSHOT_AT_INCONSISTENT`で隔離する。
- 同じ瞬間を表す`+09:00`と`Z`は同じUTC時刻として扱う。

## 8. quarantineと情報保護

quarantine結果が保持する情報は次だけである。

- 行番号
- canonical rowのSHA-256
- 固定`QuarantineReason`

原本行、商品コード、JAN、拠点、賞味期限、数量、自由文字はquarantine結果へ複写しない。parsed rowの`repr`にも値を出さない。CSV全体の例外は固定codeだけを表示し、decode例外のraw byteをcauseとして公開しない。

追加したreasonは次である。

- `ROW_SHAPE_INVALID`
- `LOCATION_AMBIGUOUS`
- `SNAPSHOT_AT_INCONSISTENT`

既存reasonの意味は変更していない。

## 9. 重複・集約・数量照合

- 同一CSV内でcanonical row hashが重複した場合、先頭行だけを候補にし、後続行を`SOURCE_DUPLICATE`で隔離する。
- 有効行は`JAN × canonical product × location × expiry`でDecimal合算する。
- 原本数量は、数量欄を非負Decimalとして解釈できた全行の合計とする。
- 正規化数量は、すべての検証に合格したbucket候補の合計とする。
- JANや賞味期限が不正でも数量だけ有効な行は原本数量へ含むため、隔離による数量欠落を照合差分として検知できる。
- 原本数量と正規化数量が一致し、quarantineが0件で、有効bucketが1件以上ある場合だけ`approval_ready=True`となる。

この段階の`approval_ready`はserviceが正式承認判断を作るための必要条件であり、DB上のAPPROVED decisionそのものではない。

## 10. 再現性

- source SHA-256は入力byte列から計算する。
- row SHA-256はCSV parserが得た列順の値をcanonical JSON化して計算する。
- reason codeは辞書順で固定する。
- bucketはcanonical key順で固定する。
- 数量はDecimalのまま合算する。
- version外のlocation、product mappingを参照しない。

同じCSV bytes、mapping version、location master、product mappingから、同じsource hash、row hash、隔離判定、bucket順、数量照合を得る。

## 11. 互換性

- 既存tableとschemaを変更していない。
- `inventory_daily_quantities`を変更していない。
- Phase 3S-1の公開contractへ追加exportしたが、既存class・関数の引数や意味は変更していない。
- Phase 2P〜2ZのAPI、Worker、UI、既存CSV形式を変更していない。
- 実データや原本値をRepositoryへ追加していない。

## 12. 自動試験

Phase 3S-2試験では次を確認した。

- UTF-8 BOM / CP932、delimiter、header row
- JAN直接入力、既存canonical ID参照
- 商品コードの版付き変換、欠損、曖昧性
- FACTORY / WAREHOUSEの分離とlocation有効期間
- 賞味期限3形式、Decimal、小数、3桁区切り、CASE
- timezone正規化、複数snapshot日時の拒否
- 行列数不一致、重複行、固定quarantine reason
- quarantine・例外・`repr`へraw値を出さないこと
- parser・validator・参照resolverのmapping version不一致拒否
- bucket集約、原本数量、正規化数量、照合不一致

## 13. 未実装

- CSV原本archiveと既存`source_files`からのservice接続
- snapshot job、lease、heartbeat、retry、idempotency
- quarantine / reconciliation / snapshotの同一transaction保存
- APPROVED / REJECTED decisionの追記
- SQLite / PostgreSQL storeのPhase 3S-2結果保存
- API、Worker、UI
- 実業務location master、product mapping、工場・倉庫CSVでのpreflight
- PDF parser
- 生産予定、Projection、Risk、Shipment Recommendation

## 14. Phase 3S-3への引継ぎ

次のsliceでは、今回の純粋変換結果をservice / store / Workerへ接続する。

1. `inventory_snapshot_jobs`の登録、claim、lease、heartbeat、再試行
2. 原本SHA-256、mapping、location master、product mappingのversion固定
3. parse / validation結果のquarantine・reconciliation保存
4. quarantine 0件、数量一致、bucket存在を満たす場合だけ正式snapshotを作成
5. 条件不成立時はREJECTED decisionを追記し、部分snapshotを残さない
6. SQLite / PostgreSQLで同じtransaction境界とsnapshot identityを検証
7. raw rowや例外本文をlog・DB・API errorへ保存しない

APIと画面は3S-4、PDF adapterは3S-5、実データpreflightと受入資料は3S-6で扱う。
