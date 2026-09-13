# Phase 2F 外部IdP接続プリフライト

## 目的

環境固有IdPへログインを試す前に、OIDC DiscoveryとJWKSを公開HTTPS endpointから取得し、Phase 1RのJWT検証とPhase 2EのAuthorization Code + PKCEログインに必要な技術条件を検査する。`READY_FOR_IDP_LOGIN`は公開metadataと公開鍵が設定に一致することだけを示し、利用者やclientの登録完了を表さない。

## 実行

本番用`.env`にPhase 1R・2EのOIDC設定と証跡保存先を設定する。

```dotenv
KIBAN_OIDC_ISSUER=https://id.example.jp/tenant
KIBAN_OIDC_AUTHORIZATION_URL=https://id.example.jp/tenant/authorize
KIBAN_OIDC_TOKEN_URL=https://id.example.jp/tenant/token
KIBAN_OIDC_JWKS_URL=https://id.example.jp/tenant/jwks
KIBAN_OIDC_ALGORITHMS=RS256
KIBAN_OIDC_PREFLIGHT_DIR=/srv/kiban/oidc-preflight
```

開発Composeでは次を実行する。

```powershell
New-Item -ItemType Directory -Force oidc_preflight_output
docker compose --profile preflight run --rm --build oidc-preflight
```

本番Composeの構成を使う場合は次を実行する。

```powershell
docker compose --env-file deploy/.env.production `
  -f deploy/compose.production.yaml --profile preflight `
  run --rm --build oidc-preflight
```

終了codeは`READY_FOR_IDP_LOGIN`が0、検査不合格が2、入力・保存などの実行失敗が1である。結果JSONは`preflight_id`、`outcome`、`report_uri`、`report_sha256`だけを標準出力へ返す。

## 判定

Discovery URLはissuerから`/.well-known/openid-configuration`を導出する。system trust storeとhostname検証を使い、リダイレクトを許可せず、既定5秒・128 KiB上限でDiscoveryとJWKSを取得する。

| 判定 | 条件 |
|---|---|
| `DISCOVERY_HTTPS_FETCH` | Discoveryを証明書検証付きHTTPSで直接取得できる |
| `DISCOVERY_ISSUER` | metadataのissuerが設定値と完全一致する |
| `DISCOVERY_ENDPOINTS_HTTPS` | authorization、token、JWKSの3 endpointが安全なHTTPS URLである |
| `AUTHORIZATION_ENDPOINT` | metadataとPhase 2E設定が完全一致する |
| `TOKEN_ENDPOINT` | metadataとPhase 2E設定が完全一致する |
| `JWKS_URI` | metadataとPhase 1R設定が完全一致する |
| `RESPONSE_TYPE_CODE` | `code`を提供する |
| `AUTHORIZATION_CODE_GRANT` | Authorization Code grantを提供する。metadataで省略された場合はOIDC既定値を適用する |
| `PKCE_S256` | PKCE `S256`を明示する |
| `SIGNING_ALGORITHM` | IdPとAPIの許可非対称署名方式に共通方式がある |
| `JWKS_HTTPS_FETCH` | JWKSを証明書検証付きHTTPSで直接取得できる |
| `JWKS_KEY_SET` | 1〜100個の公開鍵がある |
| `JWKS_COMPATIBLE_SIGNING_KEY` | 許可方式で検証に使えるRSA、ECまたはOKP署名鍵がある |
| `JWKS_UNIQUE_KEY_IDS` | 互換鍵の`kid`がすべて有効かつ重複しない |

全14項目が`PASSED`の場合だけ`READY_FOR_IDP_LOGIN`とする。応答本文、公開鍵値、接続先URL、host名、例外本文は証跡へ保存しない。設定URLはSHA-256で識別し、日時・経過時間・判定・件数・方式・制限だけを内容アドレス方式JSONへ追記する。

## モジュール境界

| module | 責務 |
|---|---|
| `oidc_preflight/contracts.py` | URL、署名方式、timeout、応答上限の入力契約 |
| `oidc_preflight/fetcher.py` | TLS検証、redirect拒否、上限付きJSON取得 |
| `oidc_preflight/validation.py` | DiscoveryとJWKSの決定的判定 |
| `oidc_preflight/report.py` | 内容アドレス方式の原子的な証跡保存 |
| `oidc_preflight/runner.py` | 取得失敗を含む判定統合 |
| `oidc_preflight/cli.py` | 引数、標準出力、終了code |

client IDの存在、redirect URI登録、audience、role claimとmapping、管理者同意、利用者割当は公開metadataから検査できない。実token発行、APIでの署名・claim検証、IdP sessionのlogout・失効連携は、環境固有IdPを使う本番受入で確認する。
