# Field Pilot Unified Inbox 実装・受入結果

日付: 2026-09-28 JST
対象: Windows現場PC、SHADOW / READ ONLY

## 今回の実装

- デスクトップの「ブンセン データ投入」から単一フォルダーへCSV/PDFを入れる。起動時、サイズ・更新時刻を2回観測し、排他オープンできた原本だけをSHA-256付きでstageする。投入元原本は削除・移動しない。
- Python側でstageのchecksumを再照合し、内容アドレス方式のArchiveへ保管。管理者が承認した版付きschema fingerprint、必須列、サンプル値からCSVを分類する。PDFは別adapterの人間確認待ち。未知schemaや変更headerは正式入力にしない。
- 同じpolicy版でSHA一致は重複、同じ種別・拠点・業務日で異なるSHAは訂正候補として記録し、既存の確認済み入力を自動置換しない。policy改訂時は同じ原本を再分類できる。台帳には原本名やrow値を保存しない。
- 必須入力集合は管理者設定の`inbox-policy.json`で版管理する。現場画面に未投入・受付済み・確認待ち・確認済みと件数を表示する。必要データがVALIDでない日はShadow結果を表示しない。
- WindowsセットアップはInboxとショートカットを作り、起動ごとにstageと分類を実行する。専用APIはread-onlyのまま。

## 受入表

| 項目 | 判定 | 根拠・制限 |
| --- | --- | --- |
| 混在CSV・PDF、未知schema、header変更 | PASS（人工入力） | schema一致CSVはRECEIVED、PDF・変更headerはREVIEW_REQUIRED、未知はUNKNOWNを台帳記録。 |
| コピー途中 | 部分PASS（Windows単体） | サイズ・mtimeの複数観測と排他オープンを実装。同一サイズ・mtimeの訂正検知はPowerShell 5.1で試験済み。実際の巨大ファイルをコピー中の並行試験は未実施。 |
| SHA重複、訂正候補 | PASS（人工入力） | 重複は再取込せず、異なるSHAの訂正候補はREADYを解除。 |
| 必須不足、再起動・二重scan | PASS（人工入力） | 必須不足は予測表示を遮断。同一stage再処理なし。 |
| 正式mapping検証、在庫snapshot、出荷正規化 | **未接続** | 現場ファイルの確定schema・mapping版・日次必須集合が未承認。RECEIVEDはVALIDへ自動昇格しない。 |
| 予測run、14日Projection、FEFO自動更新 | **未接続** | 既存のShadow表示は承認済みrun・在庫を読むが、今回の投入が自動で新規計算を起動しない。 |
| PDF抽出・確認adapter | **未実装** | PDFは原本保管と人間確認待ちまで。抽出値を正式在庫として採用しない。 |
| 現場PCでの実データ一連受入 | **未実施** | 実原本・mapping・policy確定後に要確認。実データをRepositoryへ入れない。 |

人工入力の全体回帰はWindowsで704件成功、20件skip、Linux専用計測と配布ハッシュ照合の2件を除外した。追加後の対象10件、配布照合の単独試験、`ruff check .`、PowerShell構文は成功。Windowsインストーラの再導入・専用Docker起動は成功し、投入先ショートカットの実在、画面の`DATA_NOT_READY`、Inboxの`SETUP_REQUIRED`、POST 405を確認した。現場policyは未設定である。

## GO / NO-GO

**NO-GO（投入→自動分析→結果までの現場利用）。** 一つの投入先、安全な原本stage、分類、重複・訂正管理、必須状態表示は実装した。正式取込と予測起動は未接続であり、受付済みは確認済みではない。現場担当者は従来業務判断を継続し、表示はShadow参考情報に限る。

## 現場持参前に必要な確認

1. 管理担当者が実CSV種類、header、文字コード、日付列、拠点列、CASE数量、日次必須集合を確定し、版付きpolicyを作る。ファイル名だけで識別しない。
2. 既存の出荷mapping・倉庫在庫mapping・Pilot scope・identity bridgeとの整合を取り、正式import callbackを種類ごとに接続する。工場在庫・生産予定は正式契約を別途確定する。
3. 予測Workerの実行条件、14日ProjectionとFEFOの更新順・失敗時停止・再実行冪等性を実データで検証する。
4. PDFの抽出・原本照合・人間確認を独立adapterとして設計・受入する。
5. 現場PCでZIP導入、コピー途中、再起動、二重起動、全必須充足、異常入力、Shadow数値照合を実施してからGOを判定する。
