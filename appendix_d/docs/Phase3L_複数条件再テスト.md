# Phase 3L 複数条件再テスト

## 目的

OSSモデルの順位が、評価期間、対象品目、origin間隔、予測幅の違いで変わるかを同じ画面で確認する。
保存済みdataset snapshotを再利用し、同じモデル集合を2〜12件のsnapshotへ一括登録する。snapshot、
実験、run、Provider適合記録、比較結果の既存契約は変更せず、条件を上書きしない。

## 画面操作

1. `/ui/analysis`を開き、API tokenで接続する。
2. 「比較セットをまとめて開始する」で1件以上のデータセットを選択する。
3. 比較するモデルを2〜12件選択する。
4. 主評価期間、または共通して評価できるhorizonを指定する。
5. 比較目的を入力し、「選択したモデルをまとめて開始」を押す。
6. 各データセットに1件ずつ比較キャンペーンが作られる。Workerが適合試験、予測run、自動比較を
   順次処理する。
7. 完了後、「複数条件の比較結果」でテスト期間、評価幅、モデル、順位、WAPE、Bias率、成功率を
   横断確認する。

データセットが1件の場合は従来の単一キャンペーンAPIを使う。複数の場合だけ一括APIを使うため、
従来の操作と保存形式を維持する。

## API

### 一括登録

`POST /api/comparison-campaign-batches`は`ANALYZE`権限を要求する。

- `request_key`: 操作単位の再送キー
- `snapshot_ids`: 重複のない2〜12件の保存済みsnapshot ID
- `models`: 重複のない2〜12件のProvider・モデル
- `purpose`: 比較目的
- `mode`: `primary`または`horizon`
- `horizon`: `horizon`指定時だけ必須
- `policy_version`: 評価方針版

同じ要求の再送は同じキャンペーンと決定的run IDへ収束する。同じ`request_key`でsnapshotの順序や
内容を変えた要求は拒否する。登録前にすべてのsnapshotの存在を確認し、存在しないsnapshotを含む
要求ではキャンペーンを作成しない。

### 横断結果

`GET /api/comparison-campaign-results?limit=50`は`READ`権限を要求する。自動比較が`SUCCEEDED`の
キャンペーンだけを返す。指標は保存済み比較結果の`official_common_metrics`を使用し、クライアント
から渡された数値を使用しない。WAPE昇順で条件内順位を付ける。正式比較対象外のrunはAPI上で
識別でき、画面の横断表には表示しない。

## 変更可能なテスト要素

- dataset snapshotで固定する対象品目、学習期間、テスト期間
- `origin_interval_days`、`max_horizon`、`primary_horizon_max`
- 比較するProvider・モデル集合
- 主評価期間または指定horizon
- 比較目的と評価方針版

前処理版、seed、資源profile、学習方式などProvider固有条件を変える場合は、個別の実験条件として
新規登録する。一括登録はProvider metadataの既定値を使い、異なる実験条件を暗黙に混在させない。

## 判定上の注意

1回の順位だけで採用を決めない。複数期間と業務上必要な予測幅を含め、WAPE、Bias率、成功率、
資源・費用を確認する。横断表は技術比較の補助であり、実データ受入や担当者の採用判断を自動承認
しない。元データ、絶対path、認証情報は横断APIや配布物へ含めない。

