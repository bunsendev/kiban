# Windows Portable P1 技術PoC

Docker、WSL、PC側Python、PostgreSQLを使わず、人工CSVから**既存の `builtin-baseline`** の7日先予測を実行する独立したPoCです。正式なField Pilotや業務データ取込の代替ではありません。

Windows x64のビルドPCではPython 3.12とPyInstallerをビルド時だけ使います。`python -m portable.build_windows` で `dist/BunsenPortablePoC` を作ります。配布先では展開後 `App/BunsenPortable.exe` をダブルクリックします。実際の配布物はコード署名と対象PCでの許可確認が必要です。

画面の先頭では、在庫・出荷CSVを含む100 MB以下のZIPを分析できます。13桁JAN、非負数量、賞味期限を検査し、「自動確定」「確認待ち」「隔離」へ分類します。自動確定した出荷は拠点×JAN×日へ集約し、直近35日が揃う拠点では28日学習・7日評価のBaseline参考バックテストを実行できます。12桁JAN、賞味期限欠損、不正な商品コードは勝手に補正しません。結果は過去データの参考評価であり、正式比較、現在予測、出荷指示ではありません。

人工データは `Sample/synthetic_shipments.csv`。画面の「付属の人工CSVによる技術確認」を開き、［付属の人工CSVで試す］を押すこともできます。結果は `Data/Results`、入力コピーは `Data/Input`、分析結果は `Data/Analysis`、予測用日次集計は `Data/Prepared`、実行台帳は `Data/State/runs.sqlite3`、診断ログは `Data/Logs` に残ります。画面には保存済み履歴が表示されます。アプリ更新時には `App` のみを差し替え、`Data` は保持します。

人工CSVの最小契約は `ds,unique_id,y`（UTF-8、日付 `YYYY-MM-DD`、数量は0以上）。7日以上の系列が必要です。出荷数量の欠損は拒否し、0は有効です。業務ZIP分析は商品マスタの正式採用、単位換算、現在在庫、正式比較を行いません。

開発確認は `python -m pytest tests/portable -q`。WindowsのPyInstaller onedirで同梱するため、対象PCへのPythonインストールは必要ありません。`Data` に書けない、あるいは許可ポリシーでEXEが拒否された場合は画面のエラーコードと `Data/Logs` を管理者に渡します。Windows保護機能を無効にする手順はありません。
