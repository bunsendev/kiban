# Phase 1Y 実装計画

## ゴール

成功済み正規化jobからJAN名寄せ候補を生成し、候補根拠、canonical product、版付き判断、JAN有効期間を一つの専用画面で追跡・操作できるようにする。名称一致だけでは商品を統合せず、HTTP、Worker、API、入力変換、描画、画面状態の責務を分離する。

## 実装範囲

1. READ利用者向けに名寄せjobの一覧APIを追加し、状態、条件、入力正規化job、候補件数を返す。
2. `/ui/matching`に名寄せjob、候補、canonical product、JAN有効期間の一覧と詳細をまとめる。
3. 名寄せjob、canonical product、版付き判断、JAN有効期間の登録を既存APIへ接続する。
4. 左右JANの商品名、期間、center別数量、類似度、候補理由と、判断履歴を表示する。
5. HTML、API client、入力変換、描画、画面制御、固有styleを別moduleに分割する。
6. SQLite/PostgreSQL、API認可、JavaScript、Docker配信、wheel、配布checksumを検証し、日本語PRを作成する。

## 完了条件

- READ利用者は名寄せjob、候補根拠、判断履歴、canonical product、JAN有効期間を参照できる。
- ANALYZE利用者は成功済みかつ現在採用中の正規化jobから名寄せjobを登録できる。
- APPROVE利用者はcanonical product、4種類の版付き判断、JAN有効期間を理由付きで登録できる。
- 候補生成は独立Workerに残し、HTTPはjob登録と台帳参照だけを行う。
- 正規化jobの状態・採用原本、判断と商品IDの組合せ、版、期間重複、権限をサーバーが最終検証する。
- 動的値を安全に描画し、tokenをブラウザー保存領域へ残さない。
- 実データ、原本、資格情報をGitと配布ZIPへ含めない。
- pytest、ruff、JavaScript検査、実画面、Docker API、配布checksumがすべて成功する。
