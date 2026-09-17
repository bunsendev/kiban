# Phase 3K Windows予測OSS分析ランチャー

## 目的

PC操作に不慣れな担当者がコマンドを入力せず、データ準備から複数OSSモデルの比較結果作成までに
必要なローカルserviceを起動できるようにする。起動処理は専用PowerShell moduleへ分離し、既存の
軽量なデータ検証用ランチャーを変更しない。

## 標準分析の起動

配布フォルダーの「予測OSS分析を起動.cmd」またはセットアップで作られたデスクトップの
「予測OSS分析を起動」をダブルクリックする。次の処理を自動で行う。

1. Docker Desktopを起動する。90秒で応答しない場合はruntime socketだけを退避して一度再起動する。
2. 未起動の場合だけ、CPU 4 thread、RAM 8 GB、現在の空きRAM 3 GB、disk空き15 GBを確認する。
3. PostgreSQL、API、データ準備Workerを起動する。
4. Baseline、StatsForecast AutoETS、MLForecast Ridgeの予測Workerを起動する。
5. Provider適合試験Workerと比較キャンペーン自動完了Workerを起動する。
6. API readiness、必要な全service、3 Providerのheartbeatを最大240秒確認する。
7. 接続情報をメモ帳で表示し、選択済みローカルportの`/ui/analysis`を開く。

すでに標準構成が起動している場合は、サービスが使用中の空きRAMで誤判定しないよう資源検査と
再構築を省略し、稼働確認後に分析画面を開く。初回と更新時には短時間のstorage初期化serviceが
予測artifact・作業volumeを非root Workerから書き込める所有者へ設定する。

初回はDocker imageを構築するため数分かかる。2回目以降はbuild cacheを使用する。接続codeは
`.env`と`.kiban/接続情報.txt`だけに保存し、コンソール、状態確認、診断textへ出力しない。
既定port 58000がWindowsや別アプリに予約されている場合は48100〜48120から利用可能なportを選び、
`.env`の`KIBAN_HTTP_PORT`へ固定する。Compose、readiness、状態確認、ブラウザーは同じ値を使う。

Dockerの予期しない終了でruntime socketが残った場合は、Engine停止を確認して
`%LOCALAPPDATA%\Docker\run`と`%LOCALAPPDATA%\docker-secrets-engine`だけを日時付きフォルダーへ
退避する。volume、image、VHDXは移動しない。Docker以外のWSL distributionが動作中の場合は
自動復旧を中止し、利用中のWSL作業を終了するよう案内する。

## TimesFMの追加

TimesFMは標準構成と同時に常時起動しない。「TimesFM分析を追加起動」をダブルクリックすると、
標準構成にTimesFM予測Workerと専用適合試験Workerを追加する。CPU・diskの標準条件に加えて、
RAM総量15 GB以上、実行時の空きRAM 6 GB以上を要求する。条件を満たさない場合はデータやvolumeを
変更せず停止し、他アプリを閉じて再実行するよう表示する。固定checkpointは
`timesfm_checkpoint/model.safetensors`へ事前配置する。

## 分析操作

1. snapshotがない場合はデータ準備・検証画面から原本検証、取込、正規化、名寄せ、日次化を進める。
2. 分析実行画面でdataset snapshotと2〜12モデル、主評価期間またはhorizonを選ぶ。
3. 「選択したモデルをまとめて開始」を押す。
4. 以後は適合試験、予測run、比較結果作成が独立Workerで進む。
5. 「比較結果作成済み」から対象結果を開き、担当者が採用可否を判断する。

原本の業務判断、名寄せ承認、重要品目選定、モデル採用は自動決定しない。失敗時はキャンペーン
カードの理由、状態確認の不足service、Provider状態を確認する。

## 停止・状態確認

「予測基盤を停止」は標準構成とTimesFMの全管理serviceを停止する。PostgreSQL volume、アップロード、
snapshot、比較結果は削除しない。「状態確認」はAPI状態、標準分析の不足service、TimesFM起動有無、
ProviderごとのONLINE・WORKING・待機run・実行中runを表示する。

## 実装境界

- `Kiban.Local.psm1`: Docker、Compose、資格情報、共通ディレクトリ、ショートカット。
- `Kiban.Analysis.psm1`: PC資源、分析service集合、起動、service・heartbeat確認、分析画面。
- `analysis-start.ps1`: 担当者へ5段階の進捗と安全な失敗案内を表示する薄い入口。
- `.cmd`: PowerShell execution policyを配布scriptだけに限定して起動する薄いwrapper。
