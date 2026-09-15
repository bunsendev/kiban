# Phase 2L クライアントCSVアップロード検証

## 目的

ローカル開発環境の利用者が、サーバーのフォルダーを直接操作せずに `/ui/intake` からCSVをアップロードし、列の対応付け、分析、結果確認までを一続きで試せるようにする。

## 運用フロー

1. Docker Desktopを起動する。
2. PowerShellでサービスを起動し、状態とAPIを確認する。
3. UIでCSV、またはCSVをまとめたZIPをアップロードし、列の対応付けを選んで分析する。
4. 合格または要確認の判定と件数を記録する。
5. 作業終了時はサービスだけを停止し、次回は同じ台帳から再開する。

## 1. 起動前確認

次のソフトウェアが利用できることをPowerShellで確認する。

```powershell
git --version
docker version
docker compose version
```

`docker version`にClientとServerの両方が表示されればDocker Engineへ接続できている。Serverが表示されない場合はDocker Desktopの起動完了を待って再実行する。

## 2. サービス起動

PowerShellでリポジトリの `appendix_d` フォルダーへ移動し、次を実行する。

```powershell
cd "C:\Users\zept0\OneDrive\ドキュメント\ChatGPT\New project\appendix_d"
docker compose --profile worker up -d --build postgres api mapping-dry-run-worker
docker compose ps
```

正常な状態は次のとおり。

| service | 正常な表示 |
|---|---|
| `postgres` | `Up ... (healthy)` |
| `api` | `Up` |
| `mapping-dry-run-worker` | `Up` |

続けてAPIを確認する。

```powershell
Invoke-RestMethod http://127.0.0.1:58000/health
Invoke-RestMethod http://127.0.0.1:58000/ready
```

`/health`が `status = ok`、`/ready`が `status = ready` になり、各checkが `True` ならUI操作へ進む。

## 3. 試験データ準備

試験CSVは100 MB以下、拡張子 `.csv`、UTF-8または厳密に判定できる対応文字コードで用意する。複数ファイルは100 MB以下のZIPへまとめて選択できる。ZIPはCSVだけを格納し、5,000ファイル、展開後2 GB、1ファイル100 MBを上限とする。合格確認に使える最小例は次のとおり。

```csv
出荷日,JANコード,商品名称,出荷数量,数量単位,物流拠点,明細種別
2026/09/15,0012345678901,動作確認商品,5,個,C1,SHIPMENT
```

Excelで作成する場合は、保存形式に「CSV UTF-8（コンマ区切り）」を選ぶ。JANコードの先頭0を保持するため、JAN列は文字列として扱う。

## 4. UI操作

ブラウザーで `http://127.0.0.1:58000/ui/intake` を開く。開発用tokenを入力して「接続」を押す。既定のローカル構成を変更していない場合は `change-me-local` を使用する。

1. 「01 CSV・ZIPをアップロード」でファイルを選び、「アップロード」を押す。ZIPの場合は検査に合格したCSVが一括登録され、登録件数が表示される。
2. 「02 CSVを選ぶ・確認する」で、アップロードしたファイルが自動選択され、サイズ、文字コード、列名が表示されることを確認する。
3. 「03 列の対応付けを選ぶ」でCSVの列名に合う対応付けを選ぶ。必要な対応付けがない場合は「新しい対応付けを作成」から追加する。
4. 必要に応じて検査する最大行数を変更し、「このCSVを検証・分析」を押す。
5. 完了後に自動表示される結果で、検査行、採用行、隔離行、9件の検査項目を確認する。

合格時は「検証に合格しました」と「このCSVは正規化へ進めます」が表示される。要確認時は隔離理由の固定codeと件数を確認し、CSVを修正して新しいファイルとして再度アップロードする。

## 5. 結果判定と記録

| 画面表示 | 判定 | 次の操作 |
|---|---|---|
| 検証に合格しました | 事前検証合格 | 検査行、採用行、隔離行、mapping ID、report SHA-256を記録する |
| 修正をおすすめします | 要確認 | 隔離理由codeと件数を記録し、CSVを修正して別ファイル名で再検証する |
| 検証を開始できない | 入力・設定不足 | 文字コード、列名、mapping、ファイルサイズを確認する |
| Worker処理が完了しない | 実行環境異常 | service状態とWorker logを確認する |

検証記録には最低限、実施日時、担当者、CSVの管理名、mapping ID、検査行数、採用行数、隔離行数、判定、隔離理由code、report SHA-256を残す。CSVの行値やtokenは記録へ転記しない。

## 6. 終了と再開

通常終了は次を使う。PostgreSQL volumeと台帳を維持するため、`--volumes`や`-v`は付けない。

```powershell
docker compose stop api mapping-dry-run-worker postgres
```

次回は次のコマンドで再開する。コードを変更していなければ `--build` は不要である。

```powershell
docker compose --profile worker up -d postgres api mapping-dry-run-worker
docker compose ps
```

## 7. 障害時の確認

最初に状態と直近100行のlogを確認する。

```powershell
docker compose ps
docker compose logs --tail 100 api
docker compose logs --tail 100 mapping-dry-run-worker
docker compose logs --tail 100 postgres
```

- `api`へ接続できない場合は、`docker compose ps`で `127.0.0.1:58000->8000` を確認する。
- `/ready`だけが失敗する場合は、応答のfalseになったcheckと対応serviceのlogを確認する。
- jobが待機中のままの場合は、`mapping-dry-run-worker`が `Up` か確認して再起動する。
- 同じCSVを修正した場合も、履歴を区別できる新しいファイル名でアップロードする。
- Docker Desktopの予期しない終了が続く場合は、[ローカル検証環境と実動受入](Phase2K_ローカル検証環境と実動受入.md)の復旧手順を使う。

```powershell
docker compose restart api mapping-dry-run-worker
```

## 8. 定期的な確認

ローカル運用開始時に `/health`、`/ready`、3 serviceの状態を確認する。コード更新後は `--build`付きで再起動し、合格用の人工CSVを1件通す。実業務CSVを試す場合は、組織の取扱規則に従い、検証結果が事前検証であることを明記する。

## 実装境界

- アップロードには `ANALYZE` 権限が必要で、未認証と権限不足を拒否する。
- 単一ファイルは安全な `.csv` 名だけを受け付け、複数ファイルは `.zip` として受け付ける。各アップロードをランダムな専用directoryへ保存し、既存ファイルを上書きしない。
- 100 MBを超えた時点でstreaming書込みを中止し、途中ファイルと空directoryを除去する。
- ZIPは展開前にCSV限定、暗号化、展開先逸脱、同名衝突、件数、個別容量、合計容量を検査する。展開中の実容量も確認し、失敗時はbatch全体を除去する。
- API応答、job、証跡にはCSV本文、行値、絶対pathを保存しない。
- 開発ComposeではAPIだけが入力rootへ書き込み、検証Workerはread-onlyで読む。
- 本番Composeの入力rootは引き続きread-onlyである。本番で外部利用者のアップロードを受ける場合は、認証、保存期間、マルウェア検査、容量管理を含む専用保管境界を別途設計する。

この機能は無更新の事前検証であり、原本取込、正規化、業務承認、実データ品質、予測精度の保証は行わない。
