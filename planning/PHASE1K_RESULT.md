# Phase 1K 実装結果

## 達成したゴール

成功済み日次buildを実データ3〜5品目の受入単位として凍結し、日次台帳、dataset snapshot、CSV artifact、品質閾値を再検査できるようにした。技術判定と担当者の業務判断を分離し、匿名データによる手順確認を実データ受入済みとして扱えない契約にした。

## 実装

- 受入版、日次build、3〜5品目、availability mode、系列別利用可能日数、欠測率・不完全率上限を内容アドレス方式のcaseへ固定した。
- build、品目範囲、snapshot provenance、artifact checksum、全暦日行、日次状態率を10項目で判定した。
- 日次台帳から決定的CSVを再生成し、発行済みCSVと同じSHA-256であることを確認する。台帳だけの変更も受入失敗になる。
- 同じ入力から同じJSON/Markdown品質レポートとchecksumを発行した。
- `ANONYMIZED`は全技術条件を満たしても`DRY_RUN`とし、`APPROVED`を拒否した。
- `REAL`かつ技術判定`PASSED`のcaseだけを、担当者・理由・decision version付きで承認可能にした。
- 実データ入力、原本、snapshot、品質レポートの実行時領域を配布ZIPの探索対象から除外した。
- SQLite/PostgreSQL台帳、Bearer認証付きAPI、独立Worker、Compose serviceを追加した。

## モジュール構成

永続契約、入力検証、技術チェック、レポート生成、DB行変換、SQLite/PostgreSQL台帳、processor、CLI、HTTP schema、routeを分離した。本体moduleは最大約250行で、試験もdomain、E2E、PostgreSQL、共通fixtureへ分割した。

## 検証

- pytest全313件。
- ruff全件。
- PostgreSQL 17実DBで3品目、日次台帳、snapshot、CSV、受入case、10項目の技術判定を結合確認。
- 認証付きAPIでcase作成後、別Python processのWorkerで`DRY_RUN`レポートを発行。
- 台帳改変と発行済みCSVの不一致を検出。
- 同じcaseからJSON/Markdown checksumを再現。
- DockerでAPI health、受入API 4 path・5 operation、受入Worker CLIを確認。
- wheelへの受入schema・API・Worker同梱、配布ZIPの実行時データ除外、全checksumを確認。

## 未実施と後続

実データが提供されていないため、3〜5品目の実データcase、元帳との数量照合、業務承認、予測精度・業務効果の評価は未実施である。次はアクセス制限領域へ実データを配置してPhase 1G〜1Kを実行し、その後に重要品目選定、2つ目のOSS、UI、月次再学習、本番role/TLS/監視へ進む。
