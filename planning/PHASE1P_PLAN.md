# Phase 1P 実装計画

## ゴール

Phase 1K・1N・1Oの受入、比較、CSV、採用判断を、同一画面で確認・実行できる管理画面へ接続する。画面は既存FastAPIと同じoriginから配信し、Bearer tokenをJavaScriptのメモリ内だけで扱う。業務データと判断は既存API・不変台帳を唯一の保存先とする。

## モジュール境界

`ui/routes.py`は静的画面とsecurity header、`ui/static/api.js`はBearer API通信、`format.js`は表示形式、`render.js`はDOM描画、`app.js`は画面状態と操作フロー、`styles.css`はresponsiveな視覚設計を担当する。比較・受入・採用の業務判定をブラウザーへ複製しない。

## 実装範囲

1. `/ui`へ日本語の比較・採用ワークスペースを追加する。
2. token入力後に比較、受入case、CSV export、採用判断の件数と一覧を取得する。
3. 比較を選ぶとofficial状態、run別WAPE・成功率、採用準備情報を表示する。
4. 選択した比較からbaselineを選び、版・依頼者を指定してCSVを発行・downloadする。
5. 対応する実データ受入case、採用run、fallback、対象品目・center、試験期間、判断者・理由を確認してADOPTEDまたはREJECTEDを記録する。
6. 受入case一覧APIと比較別adoption context APIを追加し、画面に業務判定ロジックを持たせない。
7. loading、空、認証失敗、API失敗、成功状態を日本語で示し、desktop/mobileとキーボード操作に対応する。
8. 静的assetをwheel・Docker・配布ZIPへ含め、API/UI契約をpytestで検証する。

## 完了条件

- `/ui`を開いてtokenを入力すると、比較からCSV発行または採用判断まで進められる。
- tokenを永続保存せず、全データ操作をBearer認証付き既存APIへ送る。
- ADOPTEDの候補はserverが返す正式run・受入条件を使用し、最終保存時もPhase 1O serviceが再検証する。
- 静的ファイルが責務別に分かれ、Content Security Policyと`no-store`を設定する。
- PostgreSQL実DBを含むpytest、ruff、JavaScript構文、Docker、wheel、配布checksumが合格する。

## 対象外

role別認可、SSO、電子署名、グラフの画像出力、スマートフォン専用業務フロー、実データ受入・本番採用の代行、本番通知・監視。
