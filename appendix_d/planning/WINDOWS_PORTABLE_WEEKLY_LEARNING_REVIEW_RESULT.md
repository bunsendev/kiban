# Windows Portable 週次改善レビュー 実装結果

## 完成した流れ

手順11までに保存したSHADOW推奨、担当者判断、後日実績を、手順12でPilot Scope版を固定して7日単位に集計できる。集計結果は上書きせず、内容アドレス方式の週次版として保存する。過去版は一覧から再表示できる。

Portableの担当者判断台帳を既存`field_learning`のreference caseへrevision順で同期した。これによりSystem参考値、Operator判断、Actualを同じ`JAN × 倉庫 × 業務日`で再利用できる。別内容、欠落revision、SHA不整合は拒否する。

## 表示する指標

- System / Operator、Forecast / Actual需要、Operator / Actual出荷の比較可能件数
- Actualあり・未取得件数
- 需要予測MAE、RMSE、WAPE、Biasと前週差
- 担当者判断数、修正数・修正率、絶対修正数量、理由別件数
- 欠品、期限切れ、倉庫間移動の数量、発生日数、取得件数

欠測は0へ変換しない。分母0、取得0件、前週未算出の指標は`null`を維持する。

## 改善候補と判断

担当者理由、欠品、期限切れ、倉庫間移動、実績未取得を候補種別へ集約する。明示した最小根拠件数を満たす候補だけを保存する。候補は根拠case数、影響数量、理由、case IDを持つ。

担当者は候補を`APPROVED`または`REJECTED`として理由付きで追記できる。revision競合と履歴改変を拒否する。`APPROVED`は別工程で調査する判断であり、モデル、特徴量、route、lead time、安全在庫、出荷単位を変更しない。

## モジュール境界

- `forecast_provider/field_learning/weekly.py`: 時点付き週次集計と候補観測
- `forecast_provider/field_learning/weekly_domain.py`: 不変な週次版・候補・判断event
- `forecast_provider/field_learning/weekly_store.py`: SQLite/PostgreSQL追記台帳
- `portable/api/learning_reviews.py`: Portable入力検証、整合性検証、read model
- `portable/api/learning_review_routes.py`: HTTP境界
- `portable/api/static/learning-reviews.js`: 手順12の操作と表示

## 残る境界

- 候補承認後の調査計画、設定変更案、検証run、正式な変更承認は別工程。
- 候補の因果関係と期待改善量は自動推定しない。
- 週次集計は保存済みの後日実績だけを使い、未投入の現場事実を推測しない。
- 実データと資格情報はRepositoryへcommitしない。
