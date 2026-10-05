# Windows Portable インストール仕様確認・実機検証結果

確認日: 2026-10-05。対象: `origin/main` commit `ea6fb0ad2334967e56954a7d299085c2bd50f8a2` を基準にしたWindows Portable版。

## 判定

**技術配布物はPASS、現場配布は条件付き。** 現場PC側へPython、Docker、WSL、PostgreSQLをインストールせず、ZIP展開と最上位の起動ファイルのダブルクリックで起動できる構成を確認した。凍結EXE、正式取込用SQL、Web画面、人工データを同梱し、業務データと資格情報は含めない。

一方、生成EXEのAuthenticode状態は`NotSigned`である。現場PCのSmartScreen、AppLocker、WDACまたは端末保護製品が署名なしEXEを拒否する場合、技術的に正常なZIPでも起動できない。既存のEd25519更新署名鍵はRelease manifest検証用であり、Windows EXEのAuthenticode署名には使用できない。現場配布GOには、組織の許可登録または信頼されたコード署名証明書による署名が必要である。

## 発見して修正した問題

1. Portableビルド用PyInstallerが依存ファイルに定義されておらず、クリーンなビルド環境で再現できなかった。
2. 開発環境に入っているTorch、TimesFM、TensorFlow等をPyInstallerが検出し、Portable版に不要な比較モデル依存まで収集していた。
3. 初回の凍結EXE試験で`forecast_provider/inventory_foundation/schema.sql`が同梱されず、起動直後に終了する問題を再現した。
4. 配布フォルダーは生成できたが、担当者へ渡すZIP、SHA-256、全ファイルmanifestを一回で生成できなかった。
5. 起動対象が`App/BunsenPortable.exe`で深く、同梱案内も人工データ専用時点のままだった。

修正後は固定したビルド依存を追加し、不要モデルを除外、`forecast_provider`のSQL等のpackage dataを明示収集した。ビルドは版付きフォルダー、ZIP、ZIP SHA-256、`PACKAGE-MANIFEST.json`、最上位の`ブンセン予測を起動.cmd`を生成する。

## 実測

- OS: Windows 11 x64
- Python: 3.12.14（ビルドPCだけ）
- PyInstaller: 6.16.0
- 配布候補: `BunsenPortable-0.6.0-pilot.2.zip`
- ZIP: 56,059,034 byte
- ZIP SHA-256: `39e92b1de100b0906cca6b355ae5b90a1dafb561039a8e33ec16f9e01f376d34`
- 展開後: 127,009,495 byte
- manifest: 2,483ファイル、SHA-256不一致0件
- ZIP CRC: PASS
- 初回ready: 1.53秒
- 再起動ready: 1.55秒
- 人工2系列×7日予測: 0.078秒、14行
- 結果SHA-256: 再実行で一致
- 保存・再起動後履歴: PASS
- listen: `127.0.0.1`のみ
- idle working set: 約115 MB
- 予測後peak working set: 約117 MB
- Portableテスト: 39 passed
- Authenticode: `NotSigned`

試験は生成ZIPを別の一時フォルダーへ展開した凍結EXEに対して実施した。ソースPython経由の代替試験ではない。

## 現場で渡すもの

開発側が生成する次の2ファイルを同じ場所へ置く。

1. `BunsenPortable-<version>.zip`
2. `BunsenPortable-<version>.zip.sha256.txt`

担当者はZIPをPC内へ［すべて展開］し、最上位の`ブンセン予測を起動.cmd`をダブルクリックする。USBまたはZIPの中から直接起動しない。アプリ更新時は既存`Data`を保持し、`App`だけを検証済み版へ切り替える。

## 現場配布前の残Gate

1. Authenticode署名または現場管理者によるpublisher/hash/path許可を確定する。
2. Docker、WSL、Python未導入の現場相当PCで、ZIP展開から画面表示まで確認する。
3. 非管理者ユーザーで`Data`書込、業務ZIP分析、中断再開、正常終了を確認する。
4. PC再起動後の履歴保持、外向き通信遮断時の利用、端末保護製品のスキャン時間を確認する。
5. 現場業務データの受入は技術インストールと分け、未確定JAN、数量単位、route、安全在庫を担当者判断として記録する。
