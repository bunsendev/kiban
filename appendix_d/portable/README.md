# Windows Portable P1 技術PoC

Docker、WSL、PC側Python、PostgreSQLを使わず、人工CSVから**既存の `builtin-baseline`** の7日先予測を実行する独立したPoCです。正式なField Pilotや業務データ取込の代替ではありません。

Windows x64のビルドPCではPython 3.12とPyInstallerをビルド時だけ使います。`python -m portable.build_windows` で `dist/BunsenPortablePoC` を作ります。配布先では展開後 `App/BunsenPortable.exe` をダブルクリックします。実際の配布物はコード署名と対象PCでの許可確認が必要です。

人工データは `Sample/synthetic_shipments.csv`。画面の［付属の人工CSVで試す］を押すか、このファイルを選択して［予測を開始］を押します。結果は `Data/Results`、入力コピーは `Data/Input`、実行台帳は `Data/State/runs.sqlite3`、診断ログは `Data/Logs` に残ります。画面には保存済み履歴が表示されます。アプリ更新時には `App` のみを差し替え、`Data` は保持します。

最小のCSV契約は `ds,unique_id,y`（UTF-8、日付 `YYYY-MM-DD`、数量は0以上）。7日以上の系列が必要です。出荷数量の欠損はP1では拒否し、0は有効です。商品マスタ、JAN確定、単位換算、正式比較、現場データは扱いません。

開発確認は `python -m pytest tests/portable -q`。WindowsのPyInstaller onedirで同梱するため、対象PCへのPythonインストールは必要ありません。`Data` に書けない、あるいは許可ポリシーでEXEが拒否された場合は画面のエラーコードと `Data/Logs` を管理者に渡します。Windows保護機能を無効にする手順はありません。
