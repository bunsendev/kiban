# Phase 1U 取扱期間と欠測判定画面

Phase 1Uは、Phase 1Iの取扱期間とPhase 1Jの日次buildを、FastAPIと同一originの専用画面`/ui/readiness`へ接続する。実データ受入の前に、期間の根拠、予定ファイルの到着状況、商品×center×日付の判定を一つの画面で確認する。

## 画面への接続

開発環境ではAPIを起動して`http://127.0.0.1:58000/ui/readiness`を開く。比較・採用画面`/ui`、Lifecycle画面`/ui/lifecycle`と相互に移動できる。

Bearer tokenはJavaScript moduleのメモリ内だけに保持し、URL、cookie、`localStorage`、`sessionStorage`へ保存しない。切断時にメモリ上のtokenを破棄する。

## 表示と操作

- canonical商品数、取扱期間数、日次build数、選択buildの要確認行数
- 商品×centerの取扱期間、確度、期間版、承認者、根拠
- 日次buildのschedule、JAN mapping、取扱期間、selection、`as_of`、snapshot
- `OBSERVED`、`CONFIRMED_ZERO`、`MISSING`、`NOT_HANDLED`、`CLOSED`、`PARTIAL_OR_INVALID`の件数
- 欠測・不正理由別の件数
- center×対象日のファイル完全性、0確定可否、不足・不正path
- 状態・商品・centerで検索できる日次行

APPROVE利用者は取扱期間を登録できる。承認者はフォームから受け取らず、認証済みsubjectをAPIが記録する。同じ商品・center・期間版の重複、商品参照、日付順、状態は既存のPhase 1I serviceが検証する。画面の権限制御は誤操作を減らす表示制御であり、認可の根拠はAPI側にある。

## 読み取りAPI

既存APIに次を追加する。

- `GET /api/daily-builds`：新しいbuildから順に一覧表示する。
- `GET /api/daily-builds/{id}/readiness`：ファイル完全性、6状態、理由をDBで集計する。
- `GET /api/daily-builds/{id}/value-page`：状態・商品・centerの任意条件とoffset/limitで日次行を取得する。limitは1〜500件とする。

既存の`GET /api/daily-builds/{id}/values`は互換性のため維持する。集計とページングは`daily/readiness_store.py`へ分離し、SQLiteとPostgreSQLが同じ処理を使用する。buildの存在、Bearer認証、READ権限、検索条件はサーバーで検証する。

## モジュール境界

| ファイル | 責務 |
|---|---|
| `readiness.html` | semantic HTML、取扱期間フォーム、表示領域 |
| `readiness.css` | データ準備画面固有layout |
| `readiness_api.js` | 取扱期間・日次build APIのrequest組立て |
| `readiness_render.js` | DOM生成、状態・理由・完全性の描画 |
| `readiness_app.js` | state、権限、event、再読込、ページング |
| `daily/readiness_store.py` | build一覧、DB集計、条件検索 |

既存の`api.js`はtokenと共通HTTP境界、`format.js`は状態名と表示形式、`styles.css`は共通デザインを担当する。動的値は`textContent`で挿入する。

## 実データ受入への使い方

1. canonical商品を確認し、商品×centerの取扱期間、確度、版、根拠を登録する。
2. 予定ファイル、採用済みnormalization、JAN版、取扱期間版、選定系列を指定して日次buildを実行する。
3. 画面でファイル完全性と6状態を確認し、`MISSING`と`PARTIAL_OR_INVALID`の理由を解消する。
4. `NOT_HANDLED`が意図した取扱期間外か確認し、誤りがあれば新しい期間版で修正する。
5. 日次buildを再作成し、Phase 1Kの3〜5品目受入caseへ渡す。

欠測、期間外、部分・不正を0へ変換しない。`CONFIRMED_ZERO`だけが出荷0として扱える。

## 未実施事項

この画面は実データを自動受入しない。3〜5品目の実データ日次build、Phase 1Kの技術判定と業務判断、全3年の重要品目選定、将来trialは別途実行する必要がある。
