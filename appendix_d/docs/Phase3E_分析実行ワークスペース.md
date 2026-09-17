# Phase 3E 分析実行ワークスペース

## 目的

現場担当者がAPI要求を手作業で組み立てず、保存済みdataset snapshotから予測runを登録し、
進捗確認、比較結果の作成までを一つの案内に沿って進める。画面は`/ui/analysis`で提供し、
比較後の指標確認、CSV発行、採用判断は既存の`/ui`へ引き継ぐ。

## 操作の流れ

1. API tokenまたはOIDCで接続する。
2. dataset snapshot、Provider、モデルを選び、実験条件を保存する。
3. 保存済み実験条件の「この条件で実行登録」を押す。
4. 対応するProvider専用Workerがrunを処理するまで待つ。
5. 完了したrunを一つ以上選び、評価方法と目的を入力して比較結果を作る。
6. 「比較結果・採用画面を開く」から指標、系譜、資源・費用、採用条件を確認する。

画面は`QUEUED`または`RUNNING`のrunがある間、5秒間隔で再読込する。`QUEUED`が続く場合は
runに表示されたProvider IDと、同じProvider専用Workerの起動状態を照合する。別Providerの
Workerが代行することはない。

## メタデータ駆動の実験作成

`ProviderMetadata.experiment_defaults`は次の実験既定値を宣言する。

- `preprocessing_version`
- Provider固有`params`
- `interval_levels`
- `seed`
- `resource_profile`
- `training_policy`

画面は`GET /api/providers`のProvider、モデル、能力、既定値だけから選択肢と要求を作る。
Provider IDごとの条件分岐を画面へ置かない。新しいProviderは実装、Registry登録、メタデータ、
専用Worker、適合試験を追加すれば同じ画面へ現れる。

区間予測に未対応のProviderではPOINTだけを使う。`OBSERVED` snapshotでbuiltin baselineを使う
場合も、時点再現済み区間残差が未実装のためPOINTだけを使う。

## 一覧API

画面用に次のREAD APIを追加した。内容アドレス方式と不変性は変更しない。

- `GET /api/snapshots?limit=1..200`
- `GET /api/experiments?snapshot_id=<任意>&limit=1..200`

SQLiteとPostgreSQLは同じ`CatalogStore`一覧契約を実装し、識別子順で決定的に返す。

## 比較の安全条件

画面で選択できるのは`SUCCEEDED`、`PARTIAL`、`FAILED`の終端runだけである。さらに次を要求する。

- 選択runが同じdataset snapshotを参照する。
- Provider ID、モデル、`params`、`interval_levels`、`preprocessing_version`が完全一致する
  Provider適合記録がある。
- 適合記録IDとtruth snapshot IDを画面ではなく保存済み台帳から組み立てる。

比較APIは同じ条件を再検証し、run台帳とchecksum検証済みsnapshotから指標を再計算する。
固定ランキング不適格な適合記録は比較自体を妨げないが、正式集合へは含めない。runが1件なら
単独評価として保存し、優勝とは表示しない。

## 権限とブラウザー境界

一覧参照はREAD、実験、run、比較の作成はANALYZEを要求する。tokenは共通API moduleのメモリ内
だけに保持し、local storage、session storage、URL、cookieへ保存しない。静的assetは既存の
CSP、`no-store`、`nosniff`、`no-referrer`を継承する。

## 受入条件

- 全管理画面から分析実行画面へ移動できる。
- snapshotと実験の一覧が最大200件で取得でき、snapshotで実験を絞り込める。
- Provider既定値から有効な実験要求を作り、runを登録できる。
- run状態、成功origin、失敗件数、Provider、モデルを確認できる。
- 異なるsnapshotのrunを同じ比較へ選べない。
- 実験条件と一致しない適合記録を比較要求へ使用しない。
- API通信、状態管理、DOM描画、styleが独立moduleである。
- Python、JavaScript構文、DOM参照、token非永続化を自動試験する。
