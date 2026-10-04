# Windows Portable 正式変更案・別承認 実装結果

## 完成した流れ

手順13で正式変更案の作成を推奨した比較runを、手順14の入力候補として表示する。担当者は変更対象、現行設定、変更後設定、適用範囲、受入基準、rollback条件、rollback先版を入力し、不変な正式変更案として保存できる。

保存後は案の作成者とは別の担当者が、実装案として承認または却下を理由付きで追記する。承認後も適用状態は`NOT_APPLIED`であり、モデルやpolicyは変わらない。

## モジュール境界

- `field_learning/formal_change_domain.py`: 不変な提案と判断event
- `field_learning/formal_change_store.py`: SQLite/PostgreSQL追記台帳
- `portable/api/formal_changes.py`: 元run、別承認、整合性の検査
- `portable/api/formal_change_routes.py`: HTTP境界
- `portable/api/static/formal-changes.js`: 手順14の入力・表示

## 安全境界

元runの最新判断が`RECOMMEND_FORMAL_CHANGE`でなければ提案できない。提案後に元判断が更新された場合も承認を拒否する。比較対象と変更種別の不正な組み合わせ、自己承認、revision競合、保存内容の改変を拒否する。

承認は実装工程への入口であり、正式設定の適用ではない。自動適用の処理、設定ファイル更新、モデル昇格、policy発行は追加していない。

## 次工程

`APPROVED_FOR_IMPLEMENTATION`の提案から限定的な変更版を作り、Pilot Scopeで受入基準を評価する。適用前backup、適用者、適用時刻、smoke test、rollback実行と結果を別の監査eventにし、受入未達では適用を禁止する。
