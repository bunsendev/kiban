# Phase 1I 実装結果

## 結果

正規化済み出荷行からJAN名寄せ候補を生成し、業務承認、canonical product、JAN有効期間、商品×center取扱期間を版付きで保存する経路を追加した。APIはjobと台帳を操作し、候補計算は独立Workerで行う。

## 候補契約

- 対象normalization IDとpolicy条件を内容アドレス方式で固定。
- 現在採用中の原本に属する成功済みnormalizationだけを入力に許可。
- NFKC・大小文字・空白を統一し、規格数字は維持。
- 名称類似と出荷期間の切替近接から決定論的な候補IDを生成。
- 原JAN、原商品名、初回/最終日、併存・空白日数、単位、center別数量、理由を監査表示用に保存。
- 候補生成だけではJAN mappingを作成しない。

## 承認と有効期間

- `SAME_PRODUCT`、`DIFFERENT_PRODUCT`、`SUCCESSOR`、`UNRESOLVED`の意味を検証。
- 承認者・理由・日時・mapping versionを候補判断へ保存し、同じ候補と版の上書きを禁止。
- canonical product作成者と理由を記録。
- JAN有効期間と商品×center取扱期間は両端包含とし、同じ版の重複を拒否。
- SQLiteの書込transactionとPostgreSQLのadvisory lockで同時登録時の競合を防止。

## モジュール構成

型、名称比較、候補生成、業務規則、SQLite台帳、PostgreSQL台帳、processor、Worker CLI、API routeを分割した。各ファイルの責務を限定し、候補policyや承認項目の追加を局所化した。

## 検証

名称正規化、候補の再現性と根拠、mapping非自動生成、4判断、承認監査、包含期間境界、重複拒否、訂正版選択後の旧原本抑止をpytestで確認した。APIでjob作成後に別PythonプロセスWorkerを起動するE2Eを追加した。最終件数と配布検証は`appendix_d/test_results.txt`に記録する。

## 次の候補

取扱期間と予定ファイル完全性を使い、`OBSERVED`、`CONFIRMED_ZERO`、`MISSING`、`NOT_HANDLED`を区別する日次状態確定を実装する。その後、版を凍結したdataset snapshot自動発行へ接続する。
