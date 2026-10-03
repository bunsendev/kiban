# Phase 3T 改善候補の比較検証

## 目的

週次改善レビューで`APPROVED`となった候補を、固定したcase集合で現行値と変更案に分けて比較する。比較結果はSHADOWの調査記録であり、予測モデル、特徴量、route、安全在庫、出荷単位へ自動反映しない。

## 操作

1. 手順12で改善候補を「次工程の調査対象として承認」する。
2. 手順13で承認済み候補、需要予測または推奨出荷量、Baseline版、Challenger版、仮説を選ぶ。
3. 比較計画を固定し、Challenger結果CSVテンプレートを保存する。
4. caseごとのChallenger数量を入力する。分からない値は空欄のままにする。
5. 比較runを作成し、共通比較件数、MAE、RMSE、WAPE、Bias、改善・同等・悪化caseを確認する。
6. 結果を「正式変更案の作成を推奨」または「変更を見送る」として理由付きで追記する。

## 比較契約

- 計画は候補が根拠としたcase IDを固定する。別caseの結果は受け付けない。
- 需要予測は`system_forecast_quantity`と`actual_demand_quantity`を使う。
- 推奨出荷量は`system_reference_quantity`と`actual_shipped_quantity`を使う。
- Baseline、Challenger、Actualが揃う共通caseだけで両者のKPIを計算する。
- 空欄は未取得、`0`は確認済みゼロとして扱う。
- `known_at`より後に判明したActualを過去runへ混ぜない。
- 同じ計画、CSV、結果版、実行者、基準日時は同じrunへ収束する。

## 指標の読み方

MAE、RMSE、WAPEは小さいほどActualに近い。Biasは正なら過大、負なら過小の傾向を示す。画面の差は`Challenger - Baseline`なので、MAE等の負値は改善を示す。

不足・過剰数量はActualとの差から作る代理指標であり、実際の欠品・廃棄数量ではない。欠品、期限切れ、倉庫間移動は同じcaseで取得済みの観測実績を表示する。Challengerを使った場合の反実仮想Outcomeは推測しない。

## 監査と制約

- 調査計画、比較run、判断eventはcontent hash付きの追記型台帳へ保存する。
- 比較runの判断はrevision競合を拒否する。
- 共通比較対象が0件の場合、正式変更案の作成を推奨できない。
- 推奨判断は変更仕様を作る次工程へ進む判断であり、正式設定の変更承認ではない。
- 実データ、商品名、原本path、資格情報をRepositoryへ保存しない。
