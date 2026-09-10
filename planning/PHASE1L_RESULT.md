# Phase 1L 実装結果

## 達成したゴール

成功済み日次buildを重要品目候補の母集団として固定し、欠損と0を分離した品目統計量、JAN変更、業務指定、対象centerを再現可能に算出できるようにした。候補算出と担当者の確定操作を分離し、初期3〜5品目または拡大20〜50品目を理由付きの不変な`selection_version`として保存する契約を追加した。

## 実装

- 日次build、候補算出版、品質・分類閾値、業務指定、依頼者、目的を内容アドレス方式の候補jobへ固定した。
- `OBSERVED`と`CONFIRMED_ZERO`だけで数量、数量構成比、変動係数、出荷0率を計算した。
- 取扱対象状態だけを分母にして`MISSING`と`PARTIAL_OR_INVALID`の欠損率を計算し、欠損を0へ変換しないようにした。
- buildのJAN mapping版からJAN変更を検出し、安定、間欠、JAN変更、業務指定の分類tagを保存した。
- 品質条件を満たさない品目も理由付きで候補に残し、確定選定版への登録は拒否した。
- 選定品目ごとの対象center・理由、版全体の担当者・理由を保存し、同じ`selection_version`の上書きを拒否した。
- SQLite/PostgreSQL台帳、Bearer認証付きAPI、独立Worker、Docker Composeを追加した。

## 検証

- pytest 325件を実行し、全件合格した。
- ruffと`git diff --check`が合格した。
- PostgreSQL 17実DBで候補job、3品目統計、初期選定版、選定itemを結合確認した。
- DockerのAPIと選定Workerを別コンテナで実行し、候補作成、Worker完了、3候補取得、選定版作成を確認した。
- 人工系列で欠損日を0として変動係数・出荷0率へ混入しないことを確認した。
- demo、100系列規模試験、artifact別process復元、wheel内容、配布ZIP checksumを確認した。

## 未対応事項

実データは配置されていないため、実データ3〜5品目のPhase 1K受入、全3年の候補母集団build、20〜50品目の業務確定は未実施である。選定画面、選定版からの日次build再発行、2つ目のOSS、月次再学習、本番role/TLS/監視は後続とする。
