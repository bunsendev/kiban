# Portable pilot.11 APIキー暗号化保存

2026-10-05。Windows DPAPIのCurrentUserでAPIキーを保存。保存先はLOCALAPPDATA/Bunsen/Portable/Credentials/openai.dpapi。配布物と業務Dataの外に置く。

画面で保存・変更・確認付き削除。入力欄は保存後に空にする。取得APIは保存状態のみを返す。別PC・別Windowsユーザーは個別設定する。保存はAPI認証成功を意味しない。

## 検証
- Portable + AI回帰: 79成功、1件は起動中アプリが固定テストポート48150を使用して失敗。自分が起動した旧アプリを停止後、当該1件を再実行して成功。
- DPAPI実暗号化、変更、破損、削除、外部Origin拒否、資格情報非公開、保存キーによる提案呼出の3テスト成功。
- ruff check .、JavaScript構文検査成功。
- 配布ZIP展開版: 人工3商品・任意名CSV36件の取込、予測、数量修正、CSV出力、feedback、再起動復元成功。
- 実キーを画面から保存。別プロセスの配布版でsaved/availableともtrue。実API接続はHTTP401（認証失敗）。キーの再確認が必要で、接続成功とは扱わない。
- ZIP CRCおよびmanifest全2502ファイルSHA一致。Dataと資格情報は配布ZIPに含まない。

配布ZIP: dist/BunsenPortable-0.6.0-pilot.11.zip
サイズ: 56336023 bytes
SHA256: f935f2bea9007c647aac1d4cbf456ed382d4ba5591bddba510794848e369a8ba

既存業務データの変更、実データのAI送信は行っていない。AIテストは人工CSVの列名のみ。
