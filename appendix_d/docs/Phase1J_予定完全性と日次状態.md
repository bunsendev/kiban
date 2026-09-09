# Phase 1J 予定完全性と日次状態

Phase 1Jは、予定された論理ファイルの到着状況と上流の確定版から、商品×center×暦日の日次状態を決定し、予測実験で使う不変dataset snapshotを発行する。HTTPは定義とjobを台帳へ登録するだけで、集計とファイル出力は`kiban-daily-worker`が行う。

## 予定ファイルと完全性

予定ファイル定義は、版名、有効期間、論理path、center、ファイル種別、対象日の両端包含範囲、ファイルに商品行がないとき0を確定できるかを固定する。定義は正規化JSONのSHA-256で内容アドレス化し、登録後に書き換えない。1つのファイルが複数日を覆う場合も`target_start`と`target_end`を明記する。

完全性はcenter×対象日で判定する。予定0件、未到着、締切時点で未利用のファイルは`MISSING`、一部到着、隔離行、centerや対象範囲の不整合は`PARTIAL_OR_INVALID`、必要な全論理ファイルが採用中原本の成功済みnormalizationで正常な場合だけ`COMPLETE`とする。件数一致だけでは完全としない。`zero_confirmable`は完全かつ予定1件以上で、対象ファイルの`absence_means_zero`がすべてtrueの場合だけ成立する。

`ASSUMED`では複数日ファイル全体を対象終了日の翌日00:00 JSTに利用可能になったと仮定する。`OBSERVED`では正規化行のtimezone付き`available_at`を使い、空ファイルまたは行時刻が揃わないファイルだけ原本取込時刻を利用する。buildの`as_of`を超える内容は状態判定に使わない。

## 日次状態

全暦日を圧縮せず、選定した商品×centerごとに次を保存する。

| 状態 | `y` | 条件と扱い |
|---|---:|---|
| `OBSERVED` | 実数量 | 取扱期間内かつファイル完全。休業日出荷も消さず矛盾理由を付ける |
| `CONFIRMED_ZERO` | 0 | 取扱期間内、全ファイル完全、0確定権限あり、該当商品行なし |
| `MISSING` | NULL | 未到着、予定0件、または0確定権限なし |
| `NOT_HANDLED` | NULL | 商品×center取扱期間外 |
| `CLOSED` | 0 | build時点で利用可能な確認済み休業日。baseline入力では欠測として除外 |
| `PARTIAL_OR_INVALID` | NULL | 部分到着、隔離行、範囲不整合、取扱期間外の出荷 |

休業日はcenter、日付、closure version、`available_at`、承認者、理由、登録時刻を不変保存する。`available_at <= as_of`の休業だけを使用する。休業日に出荷があれば`OBSERVED`と数量を維持し、`SHIPMENT_ON_CLOSED_DAY`を記録する。

## buildとsnapshot

日次buildはschedule ID、normalization ID集合、JAN mapping version、取扱期間version、任意のclosure version、`as_of`、選定版と系列、TRAIN/TEST期間、予測条件、availability modeを凍結する。予定期間の被覆、選定center、採用中原本、normalization成功、logical path、availability mode、JAN版、取扱期間版、休業版をenqueue前に検査する。

Workerは日次値を`unique_id,canonical_product_id,center_id,ds,y,daily_state,available_at,raw_quantity,issue`の順でUTF-8 CSVへ決定的に出力する。ファイル名は内容SHA-256で、catalog snapshotのprovenanceに全上流版と日次build IDを保存する。同じ定義と入力から同じbuild ID、CSV checksum、snapshot IDが得られる。

## APIと起動

すべてBearer認証が必要である。

- `POST /api/file-schedules`、`GET /api/file-schedules/{id}`
- `POST /api/closed-days`、`GET /api/closed-days?closure_version=...`
- `POST /api/daily-builds`、`GET /api/daily-builds/{id}`
- `GET /api/daily-builds/{id}/completeness`、`GET /api/daily-builds/{id}/values`

PostgreSQLとAPIを起動した後、日次Workerだけを追加起動できる。

```powershell
docker compose up -d --build postgres api
docker compose --profile worker up -d --build daily-worker
docker compose logs -f daily-worker
```

`KIBAN_SNAPSHOT_DIR`を指定しない場合、hostの`./snapshot_input`へ日次CSVを保存する。APIと予測Workerは同じディレクトリを読取り専用で参照する。CLIで直接起動する場合は`kiban-daily-worker --postgres-dsn <DSN> --output-root <DIR>`を使う。

## この段階に含まないもの

予定規則からのファイル名自動展開、未解決JANの自動補正、休業日の自動推定、重要品目の自動選定画面、実データ3〜5品目の業務受入、2つ目のOSS、月次再学習は後続段階で扱う。
