# Phase 1Q 認証・認可とセキュリティ境界

## 目的

共有Bearer tokenだけに依存していたAPIを、認証主体とroleを持つ複数credentialへ拡張する。APIはendpointごとに必要permissionを検査し、担当者を表す監査項目はrequest bodyではなく認証済みsubjectから確定する。本番modeではcredential、Host、HTTPS、共通security headerの最低条件も強制する。

## roleとpermission

| role | permission | 主な用途 |
|---|---|---|
| `VIEWER` | `READ`, `EXPORT` | 台帳・比較の閲覧、比較CSVの発行と取得 |
| `ANALYST` | `READ`, `ANALYZE`, `EXPORT` | 原本取込、正規化、日次build、run、適合試験、比較 |
| `APPROVER` | `READ`, `APPROVE`, `EXPORT` | 原本採用、名寄せ、選定、受入、採用判断 |
| `ADMIN` | すべて | 管理者による全操作 |

GETは原則`READ`、分析・生成jobは`ANALYZE`、人による確定判断は`APPROVE`、比較CSVの発行は`EXPORT`を要求する。不足時は`403`、credentialがないか不正な場合は`WWW-Authenticate: Bearer`を伴う`401`を返す。`GET /api/session`は現在のsubject、role、permissionを返し、管理画面はこの値から操作可否を表示する。

## development設定

従来の単一tokenはローカル開発専用の`ADMIN`として維持する。

```dotenv
KIBAN_API_TOKEN=replace-with-local-development-token
KIBAN_API_SUBJECT=local-admin
KIBAN_DEPLOYMENT_MODE=development
KIBAN_ALLOWED_HOSTS=127.0.0.1,localhost,api
```

Docker Composeの既定値もdevelopment用であり、本番credentialとして使わない。

## production設定

productionでは`KIBAN_API_TOKEN`を拒否し、32文字以上のtoken、subject、1件以上のroleを持つ`KIBAN_API_CREDENTIALS`を使用する。credentialは100件以下とし、未知のrole、重複token、余分なJSON項目を拒否する。tokenは起動時にSHA-256 digestへ変換し、照合器には平文を保持しない。

```dotenv
KIBAN_DEPLOYMENT_MODE=production
KIBAN_ALLOWED_HOSTS=kiban.example.jp
KIBAN_API_CREDENTIALS=[{"token":"replace-with-at-least-32-characters","subject":"operator@example.jp","roles":["ANALYST"]},{"token":"another-token-with-at-least-32-characters","subject":"approver@example.jp","roles":["APPROVER"]}]
```

`KIBAN_ALLOWED_HOSTS`は必須で、`*`は使用できない。`/api`と`/ui`への平文HTTPは`426`で拒否する。TLSをreverse proxyで終端する場合は、ASGI側で信頼するproxyを限定し、転送されたschemeがHTTPSとして復元されるように構成する。productionではOpenAPI、Swagger UI、ReDocを公開しない。

## 監査主体

`requested_by`、`decided_by`、`approved_by`、`selected_by`、`created_by`、`executed_by`は互換性のためrequest schemaに残すが、入力値は監査主体として採用しない。API routeが認証済みsubjectで必ず上書きしてからserviceへ渡す。これにより、利用者が別人の識別子をbodyへ指定しても台帳にはcredentialのsubjectが記録される。

## HTTP境界

API responseには`Cache-Control: no-store`、`X-Request-ID`、`X-Content-Type-Options: nosniff`、`Referrer-Policy: no-referrer`、`X-Frame-Options: DENY`、`Permissions-Policy`、同一origin分離headerを付ける。productionのHTTPS responseにはHSTSも付ける。管理画面固有のContent Security PolicyはPhase 1Pの静的配信で維持する。

## モジュール境界

| ファイル | 責務 |
|---|---|
| `api/security.py` | role、permission、credential照合、監査主体、HTTP security境界 |
| `api/factory.py` | 環境変数の読込みと安全でない本番設定の拒否 |
| `api/*_routes.py` | endpointごとのpermission宣言と認証主体の受渡し |
| `ui/static/api.js` | 接続時のsession取得 |
| `ui/static/app.js` | subject表示とpermissionに基づく操作可否 |

業務serviceとstoreはtokenを扱わず、既存の不変台帳と検証規則を維持する。

## 対象外

外部IdPのBearer JWT検証、JWKS・credential file rotation、TLS終端、監査log、readiness・metrics、DB backup/restoreはPhase 1Rで追加した。管理画面のAuthorization Code/PKCE login、token発行API、権限管理DB、秘密管理製品のAPI接続、電子署名は後続開発とする。
