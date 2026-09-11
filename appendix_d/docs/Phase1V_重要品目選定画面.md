# Phase 1V 重要品目候補・選定画面

Phase 1Vは、Phase 1Lの候補算出と選定版をFastAPIと同一originの専用画面`/ui/selection`へ接続する。実データ3〜5品目の受入と全3年20〜50品目の比較に先立ち、選定根拠を指標と上流日次buildへ追跡できる状態で保存する。

## 画面への接続

開発環境ではAPIを起動して`http://127.0.0.1:58000/ui/selection`を開く。データ準備画面`/ui/readiness`、比較・採用画面`/ui`、Lifecycle画面`/ui/lifecycle`と相互に移動できる。

Bearer tokenはJavaScript moduleのメモリ内だけに保持し、URL、cookie、`localStorage`、`sessionStorage`へ保存しない。切断時にメモリ上のtokenを破棄する。

## 候補算出job

ANALYZE利用者は、成功済み日次build、candidate version、業務指定商品、欠損率上限、安定品CV上限、間欠品0率下限、算出目的を指定して候補jobを登録する。依頼者はフォームから受け取らず、認証済みsubjectをAPIが記録する。

候補算出はHTTP request内で行わない。登録後に独立した`kiban-selection-worker`が処理し、画面の更新操作で完了状態と候補を再取得する。QUEUED、RUNNING、FAILEDでは候補が空でもjobとエラーを確認できる。

成功したjobでは次を表示する。

- 数量と同一job内の数量構成比
- 利用可能値だけから求めた変動係数と出荷0率
- `MISSING`と`PARTIAL_OR_INVALID`を欠損とする欠損率
- 利用可能日数と取扱対象日数
- `STABLE`、`INTERMITTENT`、`JAN_CHANGED`、`BUSINESS_DESIGNATED`分類
- 対象center、選定可否、選定不可理由

`CLOSED`と`NOT_HANDLED`は欠損率の分母へ含めず、欠測を0へ変換しない。

## 選定版の確定

APPROVE利用者は選定可能な候補を選び、候補に含まれるcenterの部分集合と品目別理由、版全体の根拠を記録する。INITIALは3〜5品目、FULLは20〜50品目を必要とする。担当者は認証済みsubjectから確定する。

画面は品目数、centerの空指定、理由の空指定を保存前に検査する。最終的にはPhase 1Lのdomainとstoreが次を再検証する。

- 候補jobが完了済みであること
- 品目が候補結果に存在し、品質条件を満たすこと
- centerが候補の対象範囲内であること
- scope別の品目数と品目・centerの重複がないこと
- 同じ`selection_version`を別内容で上書きしないこと

確定済み選定版は選定日時、scope、担当者、根拠、candidate job、品目・center・理由を一覧表示する。変更時は新しい版を作り、旧版を残す。

## 追加API

既存APIに一覧取得を追加する。

- `GET /api/selection-candidate-jobs`：新しい候補jobから順に取得する。
- `GET /api/selections`：新しい選定版から順に取得する。

既存の個別取得、候補取得、job作成、選定版作成APIは維持する。一覧処理は`selection/read_store.py`へ分離し、SQLiteとPostgreSQLで同じ処理を使用する。

## モジュール境界

| ファイル | 責務 |
|---|---|
| `selection.html` | semantic HTML、job・選定フォーム、表示領域 |
| `selection.css` | 重要品目選定画面固有layout |
| `selection_api.js` | 候補job・選定版APIのrequest組立て |
| `selection_render.js` | 候補指標、選定ドラフト、履歴のDOM生成 |
| `selection_app.js` | state、権限、event、再読込、ドラフト管理 |
| `selection/read_store.py` | 候補jobと選定版の一覧読み取り |

既存の`api.js`はtokenと共通HTTP境界、`format.js`は数値・割合・状態の表示、`styles.css`は共通デザインを担当する。動的値は`textContent`で挿入する。

## 実データ受入への使い方

1. `/ui/readiness`で取扱期間、予定ファイル完全性、日次6状態を確認する。
2. 全候補を含む成功済み日次buildから候補jobを登録し、selection Workerを実行する。
3. INITIALでは安定品、間欠品、JAN変更品を可能な範囲で含む3〜5品目を確定する。
4. 確定した品目・centerを使って日次buildを再発行し、[Phase 1W専用画面](Phase1W_実データ受入画面.md)からPhase 1Kの実データ受入caseを作成する。
5. 全3年の候補母集団ではFULLとして20〜50品目を確定し、新しいExperiment IDを発行する。

## 未実施事項

この画面の追加だけでは実データ選定または受入は完了しない。リポジトリには実データを含めず、実データ日次build、候補Workerの実行、担当者による選定、元数量照合、Phase 1Kの技術判定と業務判断は実データ環境で行う。
