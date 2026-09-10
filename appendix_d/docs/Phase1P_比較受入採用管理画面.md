# Phase 1P 比較・受入・採用管理画面

## 目的

Phase 1K・1N・1Oで保存した受入、比較、CSV、採用判断を、担当者が一つの画面で確認して操作できるようにする。画面はFastAPIと同じoriginの`/ui`から配信し、業務判断と整合性検証は既存APIと不変台帳へ集約する。

## 起動

APIを通常どおり起動し、ブラウザーで`http://127.0.0.1:58000/ui`を開く。Docker Composeを使う場合は次のとおり。

```powershell
docker compose up -d --build postgres api
```

画面上部へ設定したBearer tokenを入力する。接続後は認証subjectとroleを表示し、permissionのない操作を無効にする。tokenはJavaScriptのメモリ内だけで保持し、`localStorage`、`sessionStorage`、URL、業務台帳へ保存しない。更新すると再入力が必要になる。

## 操作フロー

1. 比較一覧から目的または比較IDで対象を選ぶ。
2. 正式比較の成立、run別の成功率・own/common/official WAPE、snapshot・selectionの系譜を確認する。
3. 対応する受入caseについて、技術判定とデータ種別を確認して業務判断を保存する。
4. baseline runとexport versionを指定して比較CSVを発行・取得する。
5. 採用時は実データ受入case、正式run、fallback、対象品目・center、試験期間、理由を指定する。却下時も版、対象、理由を記録する。

依頼者・判断者は入力欄で指定せず、APIが認証済みsubjectから確定する。

画面に表示された採用可否は案内である。保存時にはPhase 1Oのserviceが正式比較、run、実データ受入、最新APPROVED、日次build、selection、品目・centerを再検証する。

## API追加

- `GET /api/acceptance-cases`: 受入caseを作成日時の降順で返す。
- `GET /api/comparisons/{comparison_id}/adoption-context`: comparisonの正式run、snapshot上の対象品目・center、同じ日次buildに属する受入caseと最新判断を返す。

いずれも既存APIと同じBearer認証を必須とする。adoption contextはsnapshotのURIとSHA-256を検証して対象を復元するため、改変・不整合時は`409`となる。

## モジュール境界

| ファイル | 責務 |
|---|---|
| `ui/routes.py` | 同一originの静的配信とsecurity header |
| `ui/static/api.js` | Bearer API通信とCSV download |
| `ui/static/format.js` | 日時、数値、状態の表示変換 |
| `ui/static/render.js` | DOM生成とフォーム候補設定 |
| `ui/static/app.js` | メモリ上の画面状態、イベント、操作フロー |
| `ui/static/styles.css` | desktop/mobileのresponsive layout |

HTMLへ業務データを埋め込まず、DOM生成には`textContent`を使う。インラインscript・styleは使用せず、`default-src 'self'`、`frame-ancestors 'none'`、`object-src 'none'`を含むContent Security Policy、`no-store`、`nosniff`、`no-referrer`をHTMLとassetへ付ける。

## 配布

静的assetはwheelのpackage dataとして同梱する。Docker imageも同じwheel/sourceから配信するため、別のfrontend buildやNode.js runtimeは不要である。

## 対象外

SSO、電子署名、通知、本番TLS終端、グラフ画像出力、実データでの受入・採用判断そのものは本Phaseに含めない。role別認可と監査主体の固定はPhase 1Qで追加した。
