# Phase 2M Windows現場PC自動セットアップ

## 目的

PC操作に不慣れな現場担当者が、コマンド入力をせずにローカル予測基盤を導入、起動、停止、確認できるようにする。初回だけセットアップ担当者が導入し、日常運用はデスクトップのショートカットから行う。

## 導入前に管理部門が確認すること

- 対象PCが64 bitのWindows 11または対応するWindows 10である。
- BIOS/UEFIの仮想化機能とWindows Updateが利用できる。
- 初回導入時にインターネットへ接続できる。
- WSL有効化の管理者承認とPC再起動が許可されている。
- Docker Desktopの社内利用条件とライセンスを確認済みである。
- 配布ZIPを信頼できる社内経路から取得し、`SHA256SUMS.json`を含む状態で展開している。

## 初回セットアップ

1. 配布ZIPを現場PC上の固定フォルダーへ展開する。セットアップ後にフォルダーを移動しない。
2. `appendix_d`内の「現場PCセットアップ.cmd」をダブルクリックする。
3. Windowsの確認画面が表示された場合は、導入担当者が内容を確認して許可する。
4. WSLの導入後に再起動を案内された場合はPCを再起動し、同じファイルをもう一度実行する。
5. Docker Desktopがなければ、Windows Package Managerからユーザー単位で導入する。
6. Docker Desktop、PostgreSQL、API、検証Workerを起動し、readiness合格まで自動確認する。
7. 完了すると接続情報をメモ帳で表示し、操作画面をブラウザーで開く。

セットアップは最初に`SHA256SUMS.json`と全配布ファイルを照合する。不足または変更を検出した場合は導入を開始せず、ZIPの再取得・再展開を案内する。

接続codeはPCごとに暗号学的乱数で生成し、`.env`と`.kiban/接続情報.txt`へ保存する。両方ともGitと配布ZIPの更新対象外である。接続codeをメール、チャット、検証記録へ貼り付けない。

## 担当者の日常操作

セットアップによってデスクトップへ次のショートカットを作成する。

| ショートカット | 操作 |
|---|---|
| 予測基盤を起動 | Dockerと3 serviceを起動し、接続情報と操作画面を開く |
| 予測OSS分析を起動 | データ準備、Baseline、AutoETS、Ridge、適合試験、自動比較のserviceを起動する |
| TimesFM分析を追加起動 | PC資源を確認し、標準構成へTimesFM専用Workerを追加する |
| 予測基盤を停止 | 台帳とアップロード済みデータを残してserviceを停止する |
| 予測基盤の状態確認 | service、liveness、readinessを日本語で表示する |

診断が必要な場合は配布フォルダーの「障害情報取得.cmd」を実行する。デスクトップへ診断textを作成するが、接続code、CSV本文、行値、環境変数、container logは収集しない。

## 自動化の境界

- WSLのWindows機能有効化では管理者承認が必要になる。
- WSL導入後のWindows再起動は自動実行せず、利用者へ案内する。
- Docker Desktopの利用条件は組織が導入前に確認する。scriptが組織に代わって契約判断を行わない。
- Microsoft Storeまたはwingetが組織policyで禁止されているPCは、IT管理者がWSLとDocker Desktopを事前配布する。
- BIOS/UEFIの仮想化無効、空き容量不足、proxyやendpoint securityによる通信遮断はIT管理者が対応する。
- アンインストールやvolume削除は誤操作の影響が大きいため、担当者向け自動操作へ含めない。

CSV検証の操作は[クライアントCSVアップロード検証](Phase2L_クライアントCSVアップロード検証.md)を参照する。
予測OSS分析の起動条件と操作は[Windows予測OSS分析ランチャー](Phase3K_Windows予測OSS分析ランチャー.md)を参照する。
