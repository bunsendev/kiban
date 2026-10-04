# Windows Portable P1 技術PoC

Docker、WSL、PC側Python、PostgreSQLを使わず、人工CSVから**既存の `builtin-baseline`** の7日先予測を実行する独立したPoCです。正式なField Pilotや業務データ取込の代替ではありません。

Windows x64のビルドPCではPython 3.12とPyInstallerをビルド時だけ使います。`python -m portable.build_windows` で `dist/BunsenPortablePoC` を作ります。配布先では展開後 `App/BunsenPortable.exe` をダブルクリックします。実際の配布物はコード署名と対象PCでの許可確認が必要です。

画面の先頭では、在庫・出荷CSVを含む100 MB以下のZIPを分析できます。13桁JAN、非負数量、賞味期限を検査し、「自動確定」「確認待ち」「隔離」へ分類します。自動確定した出荷は拠点×JAN×日へ集約し、直近35日が揃う拠点では28日学習・7日評価のBaseline参考バックテストを実行できます。12桁JAN、賞味期限欠損、不正な商品コードは勝手に補正しません。結果は過去データの参考評価であり、正式比較、現在予測、出荷指示ではありません。

確認待ちと隔離は画面に原因・元の値・件数を表示します。担当者は、確認済み13桁JANへの対応付け、賞味期限欠損の確認、今回の対象からの除外を選び、任意のメモとともに保存できます。判断履歴は `Data/Decisions/<analysis_id>.jsonl` へ追記し、元の分析結果を上書きしません。「同じ値を次回も使用」を選んだJAN対応付けは `Data/Decisions/rules.jsonl` に保存し、同じ値を含む次回ZIPへ自動適用します。担当者判断後の出荷集計は `Data/Prepared/<analysis_id>-reviewed.csv` に分離します。

担当者画面の手順15では、別担当者が実装承認した正式変更案を固定されたPilot Scopeで試す計画を作れます。事前backup参照・SHA-256、候補版、担当者を保存し、開始smoke test、受入基準、rollback条件を順に全件評価します。不合格では開始を止め、受入未達ではrollback完了を必須にします。これは限定範囲の利用許可と監査記録であり、候補版の配置、設定ファイルの書換え、現場全体への自動展開は行いません。詳しい手順は `docs/Phase3T_Change_Application_Gate.md` を参照してください。

手順16では、正式予測Runの登録時にPilot Scopeと有効な適用計画を照合し、実際に選ばれたBaselineまたは候補版、設定hash、判定理由を表示します。候補版は `Data/State/RuntimeCandidates` のmanifestとGateで記録したSHA-256が一致するときだけ選択されます。Scope外はBaselineのままです。複数割当、承認失効、manifest不一致、未対応設定、1つのRunへの異なる設定混在は安全に停止します。詳細は `docs/Phase3T_Portable実行時候補版選択.md` を参照してください。

最新の倉庫在庫は、画面で正式拠点コード、在庫基準時刻、`明細バラ数 = CASE`を確認した後、既存のPhase 3S正式在庫契約で再検証できます。全行がJAN、賞味期限、非負数量を満たす拠点だけ、原本ZIP・判断履歴・確認内容・変換後CSVのSHA-256を結んだパッケージを `Data/FormalInventory` に生成します。未解決行がある場合は次へ進めません。

準備済みパッケージでは、倉庫ごとに10〜20商品のJANを試験対象として明示確認し、確認者と理由を記録して［Unified Inboxへ登録］を押します。既存のUnified Inbox、正式在庫Worker、数量照合を実行し、隔離0件かつ数量一致の最新ジョブだけを画面から明示承認できます。承認済みSnapshotは正式在庫として保存されます。

全Snapshotの承認後、画面の手順6でJANを商品ID、正式倉庫コードを予測拠点として使用する対応と、「日次出荷CSVが存在するのに対象JANの行がない日は出荷0箱」というpolicyを明示確認できます。原本ZIPと担当者判断後の出荷集計をSHA-256で再検証し、最大365日の日次状態を`OBSERVED`、`CONFIRMED_ZERO`、`MISSING`、`PARTIAL_OR_INVALID`に分けて保存します。原本CSV自体がない日や不正行は0へ変換しません。28日以上の有効履歴と直近7日の完全性を満たす商品だけ既存Baseline Providerで14日予測し、条件を満たさない商品は理由付きで残します。これはPortable試験運用の参考予測であり、正式な出荷指示、補充推奨、Production側のForecast Runではありません。

出荷履歴は倉庫別の基準日で処理し、在庫Snapshot日と出荷基準日が一致しない系列は予測へ混ぜません。結果画面は商品別の7日・14日合計を表示し、日別値は展開して確認できます。

人工データは `Sample/synthetic_shipments.csv`。画面の「付属の人工CSVによる技術確認」を開き、［付属の人工CSVで試す］を押すこともできます。結果は `Data/Results`、入力コピーは `Data/Input`、分析結果は `Data/Analysis`、予測用日次集計は `Data/Prepared`、担当者判断は `Data/Decisions`、正式在庫候補と登録記録は `Data/FormalInventory`、正式出荷日次build・identity bridge・14日予測は `Data/FormalForecast`、Unified Inboxの原本は `Data/Inbox`、正式在庫・bridge台帳は `Data/State/formal-pipeline.sqlite3`、実行台帳は `Data/State/runs.sqlite3`、診断ログは `Data/Logs` に残ります。画面には保存済み履歴が表示されます。アプリ更新時には `App` のみを差し替え、`Data` は保持します。

人工CSVの最小契約は `ds,unique_id,y`（UTF-8、日付 `YYYY-MM-DD`、数量は0以上）。7日以上の系列が必要です。出荷数量の欠損は拒否し、0は有効です。業務ZIP分析だけでは商品マスタの正式採用、単位換算、正式Snapshot承認を行いません。

開発確認は `python -m pytest tests/portable -q`。WindowsのPyInstaller onedirで同梱するため、対象PCへのPythonインストールは必要ありません。`Data` に書けない、あるいは許可ポリシーでEXEが拒否された場合は画面のエラーコードと `Data/Logs` を管理者に渡します。Windows保護機能を無効にする手順はありません。
