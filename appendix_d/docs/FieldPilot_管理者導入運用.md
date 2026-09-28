# ブンセン Field Pilot 管理者導入と運用

Field Pilotは、既存のPilot scope・承認済み倉庫在庫・確定POINT予測・FEFOを**SHADOW / READ ONLY**で表示する現場PC用の配布形態である。正式な出荷指示は作らない。現場担当者はGit、Python、PowerShell、URL、DBを操作しない。

## 持参物と事前条件

- `bunsen_field_pilot_release.zip`。`appendix_d/Field Pilotセットアップ.cmd`と`SHA256SUMS.json`を含む。社内で配布ZIP自体のSHA-256も別経路で照合する。
- 64 bit Windows、WSL 2、Docker Desktop。Docker Desktopの社内利用条件を導入前に確認する。WSL有効化やDocker導入に管理者権限が必要な場合はPC管理者が実施する。
- 業務確認済みのPilot scope版、商品・倉庫対応版、確定済みforecast run ID、賞味期限policyの条件・確認者・確認時刻。実データ・設定値はRepositoryへcommitしない。
- 現場PCのディスク空き容量とDockerの起動権限。初回Docker image buildにはネットワークが必要になる場合がある。
- 現場CSVの正式schemaと日次必須集合。`Data\Config\inbox-policy.json`の初期テンプレートは未設定であり、承認済みのfingerprintと列条件を管理者が設定するまで投入はVALIDにならない。

`inbox-policy.json`には、必須種別・拠点・表示名の`required`と、schema識別子、同じ種別・拠点、header SHA-256、必須列、日付列と形式、数量列、拠点列を持つ`rules`を記載する。header SHA-256は列名配列のJSON（UnicodeをASCII escapeしない）から算出し、既存のInventoryStructureProfilerと一致させる。版変更時は`version`を更新する。原本の実列名や実値をRepositoryへ入れない。ルールが空のテンプレートは安全に`SETUP_REQUIRED`となる。

## 初回導入

1. ZIPを固定フォルダーへ展開し、`appendix_d/Field Pilotセットアップ.cmd`を管理担当者がダブルクリックする。セットアップは全配布ファイルのSHA-256を照合する。
2. アプリ本体は`%LOCALAPPDATA%\Bunsen\FieldPilot\App\<版>`、Pilot設定・入力・出力・ログは`%LOCALAPPDATA%\Bunsen\FieldPilot\Data`へ分離して配置される。DBは専用Docker volume `bunsen-field-pilot_kiban-postgres`に保存する。
   投入先は`Data\Inbox\Drop`、不変原本は`Data\Inbox\Archive`、分類台帳は`Data\Inbox\inbox.sqlite3`。改善用イベントは別ファイル`Data\Inbox\improvement-events.sqlite3`へ保存する。これらをコードのApp配下へ移さない。
3. セットアップはPC固有の接続codeとDB passwordを`Data\Config\pilot.env`へ生成する。資格情報を配布ZIP、Repository、ログ、画面へ書かない。`pilot.env`はPCの利用者以外と共有しない。
   承認型学習の管理者tokenも同じファイルに生成される。管理画面は`/ui/pilot/admin`で開き、tokenをその場で入力する。tokenはブラウザーに保存されない。共有PCでは管理者画面を開いたままにしない。
4. `Data\Config\pilot-settings.json`は初回に空のテンプレートを作る。管理担当者が業務確認済みの値だけを入力する。`minimum_remaining_days`と`attention_days`を未確認の0で埋めない。`freshness_policy.version`と`freshness_policy.max_snapshot_age_hours`も承認値を設定する。未設定では表示を止める。`product_labels`と`warehouse_labels`は現場表示名を任意で指定できる。
5. Pilotデータを既存の管理者向け取込手順で登録し、snapshotをAPPROVEDにする。対象scopeに10〜20商品×倉庫がそろい、forecast runの14日POINTが確定していることを確認する。初期データを事前に安全なバックアップから復元する方法も利用できる。原本CSVをアプリのコードフォルダーへ置かない。
6. デスクトップの「ブンセン 出荷予測」を押し、画面のデータ更新日時・対象件数・日別見通し・賞味期限別在庫を確認する。画面が`データを表示できません`の場合は現場利用を開始しない。

セットアップは既存のコード版とデータを維持する。新しい配布ZIPで同じセットアップを再実行すると、コードだけ新しい版へ切り替え、設定・DB・ログを保持する。起動は固定Docker Compose project名を使うため、多重起動で別DBを作らない。

## 日常の管理

- 起動: 現場担当者はデスクトップの「ブンセン 出荷予測」をダブルクリック。Docker、PostgreSQL、APIを必要時のみ起動し、`/ready`とPilot read modelの応答後にブラウザーを開く。参照専用であり、予測Workerは現場起動時に実行しない。
- 状態: デスクトップの「ブンセン 出荷予測の状態確認」で、サービスとデータ準備状態を確認する。詳細は`Data\Logs\pilot.log`とDocker Composeの`api`/`postgres`ログを管理者が確認する。raw在庫行や接続codeをログへ転記しない。
- データ更新: 現場担当者は「ブンセン データ投入」へCSV/PDFを置き、起動アイコンを押す。起動時に安定確認・stage・分類する。分類結果がRECEIVEDでも正式取込ではない。管理者が既存手順でmapping、snapshot、forecast runを検証・承認し、設定版を切り替える。PDFは抽出・確認adapter未接続のため正式入力にならない。
- 鮮度: 必須入力が確認済みでも、在庫snapshot日時が当日の日本時間でない、未来時刻、または承認した許容時間を超える場合、Pilot画面をブロックする。`calculated_at`だけ新しくても旧snapshotを当日結果として扱わない。
- 改善観測: 投入分類と画面表示・ブロックを別台帳へ記録する。原本行・ファイル名・自由記述は保存しない。週次の管理者集計には`python -m forecast_provider.field_pilot.improvement_cli --events-db <Data\Inbox\improvement-events.sqlite3> --end-date YYYY-MM-DD`を使う。既存の現場判断・実績台帳を含める場合は`--field-learning-db`、承認済みの`--minimum-gap-cases`、`--repeat-days`、`--threshold-version`を指定する。週次対象caseは500件を超えてもページ取得で全件集計し、`reference_case_count`と`complete`を確認する。保持期限の削除は管理者がバックアップを確認したうえで`--purge-before`にタイムゾーン付き時刻を指定する。業務KPIが未取得なら空欄を維持する。
- 学習候補: 未知CSVのheader、encoding、列ごとの推定型、先頭100行までの構造情報を候補として保存する。原本行は学習台帳へ複製しない。単なる非重要列の追加で既存の列条件と値が一致する場合のみ、担当者の確認で認識契約を有効化する。単位、JAN、数量、賞味期限、拠点に関わる変更は管理画面で正式列・CASE単位・対象拠点を確認する。管理画面には候補、承認履歴、契約版と無効化操作がある。誤りがあれば旧版を無効化して新しい候補を確認する。承認は構造認識だけで、正式取込や予測起動の承認ではない。
- 終了: デスクトップの「ブンセン 出荷予測を終了」を使う。Composeの`stop`でAPI・PostgreSQLを順に停止し、DB volumeとPilotデータは残す。
- 再起動・異常終了: PC再起動後に起動アイコンを再度押す。同じCompose projectで復帰する。起動しない場合はDocker Desktop、`pilot.env`、`pilot-settings.json`、port競合、`/ready`を確認する。
- 復旧: コード破損は配布ZIPを再展開しセットアップを再実行する。DBの復元は既存の管理者向けバックアップ/復元手順で検証してから行う。アプリ削除でDBを消さない。
- アンインストール: 管理者が`Data\Tools\field-pilot-uninstall.ps1`をPowerShellで実行する。アプリ本体と専用ショートカットを削除し、PilotデータとDocker volumeは保持する。データ廃棄は別の承認・バックアップ確認の後に行う。

## セキュリティ境界

ComposeのAPI・PostgreSQL portは`127.0.0.1`にbindする。Field PilotモードのHTTP境界は`GET/HEAD`と必要な画面・health・read model以外を拒否し、POSTによる在庫変更や出荷確定を許さない。現場画面はローカルPCの単一利用者向けで、Pilot read modelはloopback上でのみ認証code入力なしに閲覧できる。共有PCや外部公開環境では使わない。APIの管理codeはローカル設定に残るため、PCアカウントと保存先のアクセス制御を維持する。

## 受入判定

初回インストール、起動、画面、終了、PC再起動後、二重起動、データなし、DBあり、エラー、アンインストールを実Windowsで確認する。商品・倉庫・現在庫・14日Projection・期限別在庫は人工または安全なPilotデータで照合する。技術試験だけで現場業務のGO判断はしない。結果は[Field Pilot Release結果](../planning/FIELD_PILOT_RELEASE_RESULT.md)に記録する。
