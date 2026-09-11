# Phase 1W 実データ受入画面

Phase 1Wは、Phase 1Kの少数実品目受入をFastAPIと同一originの専用画面`/ui/acceptance`へ接続する。Phase 1Vで確定したINITIAL 3〜5品目と成功済み日次buildを受入条件へ結び付け、技術判定と担当者の業務判断を分けて扱う。

## 画面への接続

開発環境ではAPIを起動して`http://127.0.0.1:58000/ui/acceptance`を開く。データ準備画面`/ui/readiness`、重要品目選定画面`/ui/selection`、比較・採用画面`/ui`、Lifecycle画面`/ui/lifecycle`と相互に移動できる。

Bearer tokenはJavaScript moduleのメモリ内だけに保持し、URL、cookie、`localStorage`、`sessionStorage`へ保存しない。切断時にメモリ上のtokenを破棄する。

## 受入caseの作成

ANALYZE利用者は次を指定して受入caseを登録する。

- INITIAL選定版：重複のない3〜5 canonical productを画面が引き継ぐ。
- 成功済み日次build：選定版の品目・centerで再発行したbuildを選ぶ。
- acceptance version：閾値と目的を識別する業務版。
- データ区分：実データは`REAL`、匿名手順確認は`ANONYMIZED`。
- availability mode：厳密な到着時点は`OBSERVED`、仮定時点は`ASSUMED`。
- 系列別最小利用日数、欠損率上限、部分・不正率上限、受入目的。

依頼者はフォームから受け取らず、認証済みsubjectをAPIが記録する。選定版と日次buildは別々に選択できるが、Workerの`PRODUCT_SCOPE`がbuildの商品集合と選定3〜5品目の完全一致を検証する。availability modeもWorkerがbuild定義と照合する。

## 技術判定

受入caseはQUEUED、RUNNING、SUCCEEDED、FAILEDの処理状態を持つ。独立した`kiban-acceptance-worker`が処理し、画面の更新操作で状態、outcome、チェック、レポートを再取得する。SUCCEEDEDは処理完了を表し、受入結果はPASSED、FAILED、DRY_RUNのoutcomeで確認する。

画面は次の10項目を契約順に表示する。

1. 日次build成功
2. 3〜5品目の一致
3. availability modeの一致
4. snapshot接続
5. artifact checksum
6. 商品×centerの全暦日行
7. 系列別利用可能日数
8. 系列別欠損率
9. 系列別部分・不正率
10. 実データ宣言

各項目はPASSED、FAILED、NOT_EVALUATED、実測値、期待値、詳細を表示する。JSON/Markdown品質レポートは保存URIとSHA-256を表示し、実データ・レポート本体をブラウザーへ埋め込まない。

欠損率と不完全率では`NOT_HANDLED`と`CLOSED`を分母から除き、`MISSING`と`PARTIAL_OR_INVALID`を0へ変換しない。

## 業務判断

APPROVE利用者は技術判定完了後にAPPROVEDまたはREJECTEDを、decision versionと理由付きで記録する。判断者は認証済みsubjectから確定する。

APPROVEDは`REAL`かつ`PASSED`のcaseだけ選択できる。画面は条件外のAPPROVEDを無効化するが、最終認可、case状態、outcome、データ区分、重複decision versionはサーバー台帳が再検証する。REJECTEDはデータ差し戻しの証跡として残る。再判断では新しいdecision versionを使い、旧判断を上書きしない。

業務判断前に、担当者は品質レポート、原本から日次CSVまでの数量照合、取扱期間と欠測理由を確認する。技術PASSEDだけで予測精度や業務効果を承認したことにはならない。

## モジュール境界

| ファイル | 責務 |
|---|---|
| `acceptance.html` | semantic HTML、case・判断フォーム、表示領域 |
| `acceptance.css` | 実データ受入画面固有layout |
| `acceptance_api.js` | case・チェック・判断APIのrequest組立て |
| `acceptance_render.js` | 10チェック、レポート識別子、判断履歴のDOM生成 |
| `acceptance_app.js` | state、権限、event、選定版引継ぎ、再読込 |

既存の`api.js`はtokenと共通HTTP境界、`format.js`は日時・割合・状態の表示、`styles.css`は共通デザインを担当する。動的値は`textContent`で挿入する。

## 実行順

1. `/ui/readiness`で取扱期間、予定ファイル完全性、6状態を確認する。
2. `/ui/selection`でINITIAL 3〜5品目を版付きで確定する。
3. 選定品目・centerを持つ日次buildを再発行する。
4. `/ui/acceptance`でREALの受入caseを登録する。
5. `kiban-acceptance-worker`を実行し、10チェックとレポートchecksumを確認する。
6. 元数量照合後に理由付きの業務判断を記録する。
7. PASSEDかつ最新APPROVEDのcaseを比較・採用判断へ使用する。

## 未実施事項

リポジトリには実データがないため、本実装では既存の匿名fixtureとPostgreSQL実DBで画面・契約を検証する。実データcaseの作成、Worker実行、元数量照合、業務判断は未実施であり、人工データの成功で置き換えない。
