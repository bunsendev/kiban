# Windows Portable P1 最小PoC 実装・検証結果

判定日: 2026-09-30。対象: `codex/windows-portable-p1-poc`。**技術的には CONDITIONAL PASS、P1完成判定は保留**。12 Gateの全項目がPASSするまではP1完了・現場配布可能とは扱わない。使用したのはRepository内で生成した人工CSVのみで、実データは取り込んでいない。

## 1. 実装概要とArchitecture

```text
App/BunsenPortable.exe (PyInstaller onedir, Windows x64)
  ├─ Launcher: Win32 mutex、Job Object、port選択、ready監視、ブラウザー起動、終了画面
  ├─ 子process: FastAPI + uvicorn (127.0.0.1のみ)
  ├─ P1 Web UI: 人工CSV選択 → 既存Baseline → 結果・履歴・ダウンロード
  └─ Data (Appと別): Input / Results / State (SQLite) / Logs
```

現行API factory、`/ui/easy`、`/ui/pilot`、Field PilotはPostgreSQLと業務台帳に密結合しているためP1では起動しない。新規 `portable/api` は将来既存UIへ接続できる小さなJSON API境界として分離した。Baselineの予測アルゴリズムは複製せず、既存`forecast_provider.registry`と`ForecastDataset`/`ProviderConfig`/`RunContext`を使って`builtin-baseline`を直接実行する。モデルは`seasonal_naive_7`、7日先、予測区間なし。正式な比較実験や業務予測ではない。

## 2. Python配布方式・Launcher・UI

Windows 11 x64でPython 3.12.14とPyInstaller 6.22.3を**ビルドPCだけ**で使用し、`onedir`を構築した。`onefile`やIExpressは使わない。配布先はコピーして`App/BunsenPortable.exe`をダブルクリックする構成で、PC側Python、pip、Docker、WSL、PostgreSQLの導入を要求しない設計。ただしこれらが未導入のクリーンPCでの実機試験は未実施。

LauncherはDataRoot別のWin32 named mutexで二重起動を止め、PIDファイルに依存しない。APIはJob Objectの`KILL_ON_JOB_CLOSE`で所有し、Launcher異常終了時に残存させない。使用中portを避けて48150〜48180を選び、制御tokenが一致する自分のAPIのreadyを確認してブラウザーを開く。小画面の［終了］で新規受付停止→処理終了待ち→API停止→Job/lock解放を行う。API突然停止時はエラーコードを表示する。技術ログは`Data/Logs`、書込不能時の初期エラーはWindows一時フォルダーへ保存する。

画面にはファイル選択、選択状態、予測開始、処理中、成功/失敗、結果、保存場所、履歴、終了方法を表示する。HTML/JS/CSSはローカル同梱でCDNなし。CSV契約は`ds,unique_id,y`、UTF-8、7日以上、非負数量。出荷0と欠損は区別し、欠損はP1では拒否する。

## 3. Data保存・再現性・process管理

P1専用SQLiteにrun ID、開始/終了日時、入力SHA-256、アプリ版、Provider版、結果SHA-256、成功/失敗/中断、結果pathを記録する。予測結果JSONは一時ファイルから原子的に置き換え、取得時にSHA-256照合する。起動時に`RUNNING`だったrunは`INTERRUPTED`へ変更し、成功として表示しない。入力コピーと結果はAppの外側の`Data`に保存し、App差替えで消さない。同一人工CSVの2回実行では入力SHA・予測値・結果SHAが一致した。

## 4. 外部通信・Windowsセキュリティ

uvicornは`127.0.0.1`にbindし、HostとOriginもローカルに制限する。外部API、telemetry、GitHub API、自動更新、CDNはP1に含めない。ライブ試験の`netstat`でlistenは`127.0.0.1`のみを確認。Firewallで外向き通信を遮断したオフライン実機試験はまだ行っていないため「通信ゼロ」の実証は未完了。コード署名・会社端末のSmartScreen/AppLocker/WDAC許可は未確認で、保護機能の無効化を前提としない。ログにはCSV本文、数量、tokenを出さず、run IDとエラーコードを記録する。

## 5. テスト・測定

Windows上の`tests/portable`は12件成功。既存Baselineと合わせて59件成功。`ruff check portable tests/portable`は成功。凍結したEXEの別processで、初回起動→人工CSV→14予測行→SQLite/JSON保存→API再起動→履歴確認を成功。Launcher相当processを強制終了するとJob ObjectがAPIを停止し、mutexが回収されることを確認した。不正/空CSV、port競合、Data書込不可、結果改変、制御token不一致も確認。

Windows 11 x64の1台での観測値。配布フォルダーは2,328ファイル、116.5 MiB。初回API ready約5.55秒、2回目約1.05秒、2系列×28日のBaseline約0.11秒。API idle working set約100.2 MiB、予測後のpeak working set約102.8 MiB、API process CPU累積約0.83→0.88秒。Dataは1回の試験後15,906 byte。測定用強制terminateの終了時間約0.016秒で、Launcher GUIの正常終了時間ではない。測定回数が少なく、最低PC要件をこれだけで確定しない。

クリーンな`Data`を含む配布ZIPは`dist/BunsenPortablePoC-P1-ready.zip`、57,139,823 byte、SHA-256 `43D0A278526A6E3D87F65386B89F263048A455C287BEBD67CB8702B0F51276FF`。ZIP全entryのCRCを確認し、別フォルダーへ展開して凍結EXEの予測・保存・再起動smokeを通した。これは署名済み現場配布物ではない。

配布一覧更新後のRepository全体は**832 passed、20 skipped、2 failed**。失敗は既存Field Pilotの固定期待値とWindowsで走らないLinux専用RSS計測。`make_release.py`と`make_release.py --check`は899/899で一致し、`ruff check .`も成功。P1変更は既存Field Pilot/Dockerコードを編集していない。全体回帰を合格とは記載しない。

## 6. 12 Gate判定

| Gate | 条件 | 判定 | 根拠・未完了 |
| --- | --- | --- | --- |
| 1 | Dockerなし | 未判定 | EXEはDockerを呼ばないが、Docker未導入PCで未試験。 |
| 2 | WSLなし | 未判定 | WSL未導入PCで未試験。 |
| 3 | PC側Pythonなし | 未判定 | 同梱runtimeで動作したが、このPCにはビルド用Pythonがある。 |
| 4 | 担当者コマンドなし | 未判定 | GUIを実装。現場でダブルクリックからの一連操作未試験。 |
| 5 | 人工CSV→Baseline | PASS | 凍結EXEの別processで14行予測。 |
| 6 | ローカル結果保存 | PASS | JSONとSQLite履歴、SHA照合。 |
| 7 | 再起動後の結果 | PASS（アプリ再起動） | API再起動後の履歴確認。PC再起動は未試験。 |
| 8 | 終了後不要processなし | 条件付き | source Launcherの正常停止確認。凍結GUIの手操作未確認。 |
| 9 | 強制終了後復旧 | 条件付き | source Job Object/API停止とmutex回収、SQLite中断回収。凍結GUI・電源断は未確認。 |
| 10 | 外部通信なし | 未判定 | 外部通信コードはないが、Firewall遮断下のパケット検証は未実施。 |
| 11 | 127.0.0.1のみ待受 | PASS | 凍結EXEの`netstat`で確認。 |
| 12 | 既存Docker版を壊さない | 条件付き | Docker/既存APIを未変更。全体回帰2件失敗のため完全合格とはしない。 |

12 Gateが揃っていないので**P1は完了扱いにしない**。現場PCでのクリーン導入・オフライン・GUI・異常停止・再起動試験を次の受入作業とする。

### 2026-09-30 現場受入準備の追試

P0のmain取込後、P1 PRをmain基準へ変更した。担当者がテスト用CSVの場所を探さずに済むよう［付属の人工CSVで試す］を追加した。従来のファイル選択経路も維持する。人工CSVはEXE内のローカルassetから配信し、既存の`POST /api/runs`と同じ検証・Baseline・保存経路へ渡す。受入手順と12 Gateの記録表は`portable/P1_FIELD_ACCEPTANCE.md`に記載した。

PyInstaller 6.22.0でWindows x64 onedirを再ビルドし、ブラウザー画面のボタン操作から14行の結果、保存済み履歴、2回実行の同一入力SHA-256と結果SHA-256を確認した。`tests/portable`は12件成功、ruffとdiff検査も成功。再生成ZIPは`BunsenPortablePoC-P1-20260930-TEST-ONLY.zip`、56,181,318 byte、SHA-256 `7122266f41e6d96d87485c3eb8bd4f9e43c79e06e7f8508738ba1631fa70788f`。2,327 entryのCRCを確認し、別フォルダーへ展開した凍結EXEで14行予測・保存・API再起動後の履歴・127.0.0.1のみの待受を再確認した。配布manifest更新後の全体回帰は832 passed / 20 skipped / 2 failedで、失敗は既存Field Pilotの固定期待値とWindows上のLinux専用RSS計測。`make_release.py --check`は900/900一致した。

このPCではブラウザー操作ツールのファイル選択イベントを取得できなかったため、ファイル選択からの手操作は未判定。ダブルクリックからのLauncher GUI正常終了、Docker・WSL・Python未導入PC、完全オフライン、異常終了後の現場復旧も未判定である。12 Gateの判定自体は上表から変更しない。これは人工データ専用の受入候補で、現場の正式予測や配布承認を意味しない。

## 7. 発見した問題、P2、残存リスク

現行`/ui/easy`と`/ui/pilot`の再利用にはPostgreSQLを含む正式API・台帳の移植が必要。P1 SQLiteはPoCのrun履歴だけで、現行PostgreSQLをSQLiteへ置換する設計判断ではない。P2にはWindows用PostgreSQLバイナリ/初期化、既存schema migration、DB起動停止とバックアップ、Worker永続化、正式snapshot・artifact台帳、既存UI接続、障害注入、署名付き更新と復旧が必要。これらは本PRの範囲外。

現場PCのアプリ実行ポリシー、コード署名、VC runtime/DLL、Firewall、非管理者権限、長時間動作、実データ精度、OS別数値再現性、電源断後の保存、UIの操作性は未評価。したがって**P2の大規模実装開始判定は保留**し、まずこのPoCの残Gateを現場試験で閉じる。
