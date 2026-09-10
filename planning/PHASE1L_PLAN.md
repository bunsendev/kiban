# Phase 1L 実装計画

## ゴール

成功済み日次buildを母集団として重要品目候補の統計量を再現可能に算出し、担当者が対象センターと理由を確認して確定した選定を、不変な`selection_version`として管理する。

## 範囲

1. 日次build、候補算出版、品質・分類閾値、業務指定を凍結する内容アドレス方式の候補算出job。
2. 数量、数量構成比、変動係数、出荷0率、欠損率、JAN変更有無、業務指定、対象センターを品目単位で算出する。
3. `OBSERVED`と`CONFIRMED_ZERO`だけを数量・変動係数・出荷0率に使い、欠損を0へ変換しない。
4. `MISSING`と`PARTIAL_OR_INVALID`を取扱対象日の欠損率へ反映し、`CLOSED`と`NOT_HANDLED`を分母から除外する。
5. 初期3〜5品目または拡大20〜50品目を、対象センター・品目別理由・担当者・全体理由付きで確定する。
6. 同じ`selection_version`の上書きを拒否し、変更時は新しい版を発行する。
7. SQLite/PostgreSQL台帳、Bearer認証付きAPI、独立Worker、Docker Composeを追加する。
8. 匿名fixture、別process、PostgreSQL実DB、配布物を検証する。

## モジュール境界

`selection/contracts.py`は永続契約、`selection/domain.py`は入力検証と内容アドレス化、`selection/metrics.py`は副作用のない統計量、`selection/classification.py`は分類、`selection/store.py`と`selection/postgres_store.py`は台帳、`selection/processor.py`は候補処理順、`selection_worker.py`はprocess loopを担当する。HTTP schemaとrouteも専用moduleへ分ける。

## 完了条件

- 欠損を0とせず、利用可能値だけで変動係数と出荷0率を再現できる。
- 数量構成比は同じ候補jobの全品目数量を分母にする。
- JAN版に複数JANがある品目をJAN変更ありとして記録する。
- 業務指定は入力で明示された品目だけに付与し、自動推定しない。
- 品質閾値を超えた品目、候補外品目、候補外センターを選定できない。
- 初期版3〜5、拡大版20〜50、品目重複、空の理由を検証する。
- 選定版は候補job経由で分析期間と上流版へ追跡でき、既存版を上書きしない。
- pytest、ruff、PostgreSQL実DB、別process、Docker、wheel、配布checksumを確認する。

## 対象外

実データそのもののGit管理、候補の自動確定、予測結果を見た後の同一選定版変更、選定画面、2つ目のOSS、月次再学習、本番role/TLS/監視。
