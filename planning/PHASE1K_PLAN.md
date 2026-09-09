# Phase 1K 実装計画

## ゴール

実データ3〜5品目をGitへ保存せずに受け入れるため、日次build、dataset snapshot、品質閾値、技術判定、担当者の業務判断を不変な証跡として管理する。実データ未提供時は匿名データによる手順確認を`DRY_RUN`として残し、実データ受入完了とは扱わない。

## 範囲

1. 日次build、3〜5品目、利用可能時刻モード、品質閾値を凍結する内容アドレス方式の受入case。
2. build成功、snapshot接続、artifact checksum、商品範囲、全暦日行、系列別利用可能日数、欠測率、不完全率を検査する技術判定。
3. JSONとMarkdownの決定的な品質レポートをアクセス制限対象の出力領域へ発行する。
4. `REAL`と`ANONYMIZED`を区別し、匿名データの合格を`DRY_RUN`に固定する。
5. 技術判定`PASSED`の実データcaseだけを、担当者・理由・decision version付きで承認可能にする。
6. SQLite/PostgreSQL台帳、Bearer認証付きAPI、独立Worker、Docker Composeを追加する。
7. 匿名3品目fixture、別process、PostgreSQL実DB、配布物を検証する。

## モジュール境界

`acceptance/contracts.py`は永続契約、`acceptance/domain.py`は入力検証と内容アドレス化、`acceptance/checks.py`は副作用のない品質判定、`acceptance/report.py`は決定的レポート、`acceptance/store.py`と`acceptance/postgres_store.py`は台帳、`acceptance/processor.py`は処理順、`acceptance_worker.py`はprocess loopを担当する。HTTP schemaとrouteも専用moduleへ分ける。

## 完了条件

- 3品目未満、5品目超、重複品目、不正閾値を受理しない。
- 日次buildの選定品目と受入対象が完全一致する。
- 各系列に期間内の全暦日行があり、利用可能日数・欠測率・不完全率が閾値を満たすかを系列別に判定する。
- snapshotのprovenanceとCSV checksumが日次buildに一致する。
- 同じcaseと日次buildから同じチェック、JSON/Markdown checksumを再現する。
- 匿名データは全技術検査に合格しても`DRY_RUN`で、業務承認できない。
- `REAL`かつ技術判定`PASSED`のcaseだけを業務承認でき、判断履歴を上書きしない。
- pytest、ruff、PostgreSQL実DB、別process、Docker、wheel、配布checksumを確認する。

## 対象外

実データそのもののGit管理、予測精度や業務効果の保証、重要品目20〜50品目への拡大、2つ目のOSS、選定・承認UI、月次再学習、本番role/TLS/監視。
