# Phase 1X 原本取込・正規化画面

Phase 1Xは、Phase 1Gの原本取込台帳とPhase 1Hの正規化・数量照合をFastAPIと同一originの専用画面`/ui/intake`へ接続する。原本を上書きせず、取込から訂正版採用、正規化、隔離確認までの証跡を一つの作業順で扱う。

## 画面への接続

開発環境ではAPIを起動して`http://127.0.0.1:58000/ui/intake`を開く。データ準備、重要品目選定、実データ受入、比較・採用、Lifecycleの各画面へ移動できる。

Bearer tokenは共通JavaScript moduleのメモリ内だけに保持し、URL、cookie、`localStorage`、`sessionStorage`へ保存しない。切断時にtokenと読込済み台帳を画面状態から破棄する。

## 原本取込

ANALYZE利用者は、サーバーで設定した入力rootからの相対pathを指定して取込jobを登録する。ブラウザーから原本をアップロードする機能ではない。独立した`kiban-ingestion-worker`が原本を読み、SHA-256、encoding、size、logical pathを記録し、次の状態へ分類する。

- `ACCEPTED`: 初回の採用可能な原本。
- `DUPLICATE`: 同じchecksumを持つ既存原本の重複。
- `CORRECTION_CANDIDATE`: 同じlogical pathで内容が異なる訂正版候補。
- `QUARANTINED`: encodingなどの検証で隔離された原本。

画面は重複元・訂正元のIDとエラーを表示する。原本本文は表示しない。

## 訂正版の採用

APPROVE利用者は、採用可能な原本または訂正版候補を、decision versionと理由付きで採用する。判断者は認証済みsubjectからAPIが確定する。同じlogical pathとdecision versionは再利用できず、過去の採用履歴を上書きしない。

画面の選択肢は操作ミスを減らすために絞るが、原本状態、logical path、版、権限はサーバー台帳が再検証する。訂正版候補は明示採用されるまで正規化できない。

## 列mappingと正規化

ANALYZE利用者は、日付、JAN、商品名、数量、単位、center、行区分、availability mode、ファイル方式、日付形式、許可単位を列mappingとして登録する。centerは列名か固定値のどちらか一方を使う。`OBSERVED`では利用可能時刻列を必須とし、`ASSUMED`では出荷日翌日0時の既存契約を使う。mappingは内容アドレス方式で不変に保存する。

採用中原本とmappingを指定して正規化jobを登録すると、独立した`kiban-normalization-worker`が処理する。HTTP request内ではCSVを解析しない。画面の更新でWorker結果を再取得する。

## 隔離と数量照合

正規化詳細は、全行数、採用行数、隔離行数、処理エラーに加え、次の数量を表示する。

- parseable quantity
- accepted quantity
- quarantined quantity
- unexplained quantity

正規化行は`ACCEPTED`または`QUARANTINED`で絞り込み、100件ずつ取得する。APIは`limit`を1〜500、`offset`を0以上に制限する。画面は行番号、日付、center、raw JAN、raw商品名、数量、単位、利用可能時刻、隔離理由を表示する。欠測や隔離を0へ変換しない。

## 追加API

| Method | Path | permission | 用途 |
|---|---|---|---|
| GET | `/api/imports` | READ | 取込job一覧と状態別件数 |
| GET | `/api/mappings` | READ | 不変な列mapping一覧 |
| GET | `/api/normalizations` | READ | 正規化job一覧と行件数 |
| GET | `/api/normalizations/{id}/summary` | READ | job系譜と数量照合 |
| GET | `/api/normalizations/{id}/row-page` | READ | 状態条件付き正規化行ページ |

既存のPOST APIと詳細APIは互換性のため維持する。動的値はDOMへ`textContent`で設定し、画面操作後はサーバー台帳を再読込する。

## モジュール境界

| ファイル | 責務 |
|---|---|
| `intake.html` | semantic HTML、登録form、台帳・詳細領域 |
| `intake.css` | 原本取込・正規化画面固有layout |
| `intake_api.js` | 一覧・詳細・操作APIのrequest組立て |
| `intake_forms.js` | 列mapping入力の契約変換 |
| `intake_render.js` | 原本系譜、採用履歴、数量照合、行ページのDOM生成 |
| `intake_app.js` | state、権限、event、検索、ページ移動、再読込 |

共通の`api.js`はtokenとHTTP、`format.js`は状態・数値表示、`styles.css`は全画面共通デザインを担当する。

## 実行順

1. 入力rootへ原本を配置し、`/ui/intake`で相対pathの取込jobを登録する。
2. ingestion Workerを実行し、checksum、encoding、重複・訂正・隔離状態を確認する。
3. 訂正版候補を使用する場合は、版と理由付きで採用する。
4. 列mappingを登録し、採用中原本から正規化jobを登録する。
5. normalization Workerを実行し、隔離理由と数量照合を確認する。
6. `/ui/readiness`で取扱期間、予定完全性、6種類の日次状態へ進む。

## 未実施事項

リポジトリには実データを置かない。本実装では人工fixtureとPostgreSQL台帳で画面、API、権限、ページングを検証する。実業務原本の取込、数量照合、実データ受入は未実施であり、人工データの成功で置き換えない。
