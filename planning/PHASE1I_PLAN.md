# Phase 1I 実装計画

## ゴール

正規化済み出荷行から再現可能なJAN名寄せ候補を生成し、人の承認判断、canonical product、JAN有効期間、商品×center取扱期間を監査可能な版付き台帳へ保存する。

## 範囲

1. 対象normalization IDと候補条件を固定する名寄せjobと独立Worker。
2. Unicode NFKC・空白・大小文字を統一し、規格数字を残す商品名比較。
3. 同名、名称類似、旧JAN終了と新JAN開始の近接を理由とする決定論的候補。
4. 旧新JAN、原商品名、単位、初回・最終日、併存期間、center別数量の候補表示。
5. `SAME_PRODUCT`、`DIFFERENT_PRODUCT`、`SUCCESSOR`、`UNRESOLVED`の承認履歴。
6. canonical product、JANの包含有効期間、商品×center取扱期間と競合検査。
7. SQLite/PostgreSQL schema、認証付きAPI、別プロセスE2E、Compose、文書・配布検証。

## モジュール境界

`master/contracts.py`は型、`names.py`は名称比較、`candidates.py`は候補生成、`domain.py`は承認・期間規則、`store.py`はSQLite台帳、`postgres_store.py`はPostgreSQL claim、`matching_worker.py`はprocess loopを担当する。API routeも専用moduleへ分ける。

## 完了条件

商品名一致だけではJAN mappingが作られず、承認APIを通した判断だけが履歴に残る。SAME_PRODUCTは同じcanonical product、DIFFERENT_PRODUCT/SUCCESSORは別productを要求する。同一mapping versionで同じJANの有効期間を重複できず、取扱期間も競合しない。全pytest、ruff、別プロセスE2E、demo、scale、artifact復元、wheel、checksumを確認し、日本語のDraft PRを作る。

## 対象外

規格・入数の自動抽出、JANの自動補正、候補の自動承認、日次0補完、予定ファイル完全性、dataset snapshot自動発行、実データでの閾値調整。
