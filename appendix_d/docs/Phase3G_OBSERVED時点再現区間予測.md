# Phase 3G OBSERVED時点再現区間予測

## 目的

実測の`available_at`を持つdataset snapshotでも、過去の予測起点へ後日到着した実績や訂正値を
遡及させず、builtin baselineの経験残差による予測区間を利用できるようにする。人工的な
`ASSUMED`到着時刻と実測時刻を同じ評価として混ぜるものではない。

## 時点再現規則

対象日を`target_date`、horizonを`h`とすると、historical originは
`target_date - h日`である。残差計算に使う履歴値は、その起点の翌日00:00 JSTまでに
`available_at`が到来した値だけとする。

残差の正解値には、学習終了日の翌日00:00 JSTまでに到着したTRAIN実績だけを使う。
この最終締切を超えた実績は欠測として扱い、区間幅へ混入させない。行自体は削除しない。

区間はTRAIN内の有効な残差がhorizonごとに10件以上ある場合だけ出力する。不足時は従来どおり
POINTを残し、評価台帳の`interval_status`を`UNAVAILABLE`とする。幅0を高信頼区間として
補完しない。

## 対応モデル

- 前週同曜日
- 28日移動平均
- 同曜日直近4回平均
- 前年同曜日

同じ欠測規則、同じ点予測式をASSUMEDとOBSERVEDで使う。全値が通常どおり翌日までに到着した
場合、OBSERVEDの残差分位はASSUMEDと浮動小数点許容差内で一致する。

## 実装境界

`available_history`はOBSERVEDの場合だけ`available_at`列をProviderへ引き渡す。
`baseline_algorithms.py`が点予測、ASSUMED残差、OBSERVED残差を担当し、Provider本体は
契約検証、model state作成、予測行生成を担当する。model artifactには残差分位だけを保存し、
原本の到着時刻や実績行を追加保存しない。既存のartifact codec版は変更しない。

分析実行画面では、Provider metadataが区間予測対応を宣言していればOBSERVED snapshotでも
区間水準を選択できる。Provider固有の判定は追加しない。

## 検証

- 過去起点では未到着だった最初の7日分を大きく訂正しても、残差分位が変わらない。
- 通常到着データでは4方式のOBSERVED残差がASSUMEDと一致する。
- OBSERVEDの固定学習runがPOINTと0.1、0.5、0.9分位を完走する。
- 4方式でmodel/context artifactを保存・復元し、予測が完全一致する。
- `available_at`欠落、timezoneなし、欠損時刻を契約違反として拒否する。

## 運用上の注意

予測区間はTRAIN残差の経験分布であり、将来の需要が指定確率で収まることを保証しない。
実データの精度、被覆率、業務効果は比較・受入画面と将来trialで別途確認する。
`available_at`の意味や記録時刻を変更した場合は、既存snapshotを上書きせず新しいsnapshotと
experimentを作成する。
