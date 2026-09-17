# Phase 1R 本番運用基盤

## 目的

Phase 1Qのrole別認可を本番の認証・運用境界へ接続する。外部IdPが発行したJWT access token、停止を伴わないcredential更新、構造化監査log、liveness・readiness・metrics、PostgreSQL backup/restore、TLS reverse proxyを独立したモジュールとして追加する。

## 認証mode

`KIBAN_AUTH_MODE`で`token`または`oidc`を選ぶ。developmentの既定は`token`で、従来の`KIBAN_API_TOKEN`を維持する。productionのtoken modeは複数credential JSONまたはcredential fileだけを許可する。

### OIDC

```dotenv
KIBAN_AUTH_MODE=oidc
KIBAN_OIDC_ISSUER=https://id.example.jp/tenant
KIBAN_OIDC_AUDIENCE=kiban-api
KIBAN_OIDC_JWKS_URL=https://id.example.jp/tenant/.well-known/jwks.json
KIBAN_OIDC_ROLE_CLAIM=roles
KIBAN_OIDC_ROLE_MAPPING={"kiban-viewer":"VIEWER","kiban-analyst":"ANALYST","kiban-approver":"APPROVER","kiban-admin":"ADMIN"}
KIBAN_OIDC_ALGORITHMS=RS256
KIBAN_OIDC_LEEWAY_SECONDS=60
```

APIはJWT headerの`kid`からJWKS公開鍵を選び、非対称署名、`iss`、`aud`、`sub`、`iat`、`exp`を検証する。許可algorithmはRS、ES、EdDSA系だけで、共有鍵のHS系と`none`は設定時に拒否する。role claimは単一文字列または文字列配列とし、mapping後に有効なroleが1件もなければ認証失敗とする。

PyJWTの`PyJWKClient`はJWKSをcacheし、現在の鍵集合に`kid`がなければ更新して再試行する。この動作をIdPの署名鍵rotationへ利用する。仕様は[PyJWTのJWKS利用例](https://pyjwt.readthedocs.io/en/stable/usage.html#retrieve-rsa-signing-keys-from-a-jwks-endpoint)を参照する。

本Phaseが実装するのはBearer JWT検証である。管理画面からIdPへredirectするAuthorization Code/PKCE login flowは含まない。

### token file rotation

```dotenv
KIBAN_AUTH_MODE=token
KIBAN_API_CREDENTIALS_FILE=/run/secrets/api_credentials
KIBAN_CREDENTIAL_REFRESH_SECONDS=5
```

credential fileはPhase 1QのJSON配列形式で、1 byte以上64 KiB以下とする。更新は次の順で行う。

1. 旧tokenと新tokenを両方含む一時fileを作る。
2. 一時fileを同じfilesystem内でatomic renameし、設定pathを置き換える。
3. 新tokenで`GET /api/session`と`GET /ready`を確認する。
4. 新tokenだけのfileを同じ方法で置き換え、旧tokenの401を確認する。

更新後のJSONが不正、空、過大、読込不能の場合はfail closedとなり、既存tokenも401、readinessも503になる。最後の正常内容へ黙って戻さない。

## 観測と監査log

| endpoint | 認証 | 用途 |
|---|---|---|
| `GET /health` | 不要 | processがHTTPへ応答できるかを示すliveness |
| `GET /ready` | 不要 | 認証、PostgreSQL、snapshot root、report rootの依存状態 |
| `GET /metrics` | `READ` | Prometheus text形式のrequest件数、時間、処理中件数、uptime |

`/ready`は各checkの真偽だけを返し、DSN、path、例外内容を公開しない。`/metrics`のroute labelはFastAPIのroute templateを使い、IDや未知pathによる高cardinality化を防ぐ。

`kiban.audit` loggerは各requestを1行JSONでstdoutへ出す。request ID、method、route template、status、処理時間を含み、認証済みのPOST・PUT・PATCH・DELETEにはsubjectとroleを付ける。Authorization header、token、body、query string、DSNは記録しない。保存期間、転送、改ざん防止は運用側のlog基盤で設定する。

## TLS本番Compose

`deploy/compose.production.yaml`はCaddyだけを80/443で外部公開する。APIは`edge`と内部`backend`、PostgreSQLは内部`backend`だけへ接続し、API portとDB portをhostへ公開しない。Caddyへdomainを渡すとautomatic HTTPSが証明書取得・更新とHTTPからHTTPSへのredirectを行う。公開DNSと80/443到達性の要件は[Caddy Automatic HTTPS](https://caddyserver.com/docs/automatic-https)を参照する。

```powershell
cd appendix_d\deploy
Copy-Item .env.production.example .env.production
# .env.production、secrets/postgres_password、secrets/postgres_dsnを実環境に合わせる
docker compose --env-file .env.production -f compose.production.yaml config
docker compose --env-file .env.production -f compose.production.yaml up -d --build postgres api caddy
docker compose --env-file .env.production -f compose.production.yaml --profile workers up -d
```

`secrets/postgres_dsn`はURL encode済みpasswordを含む完全なPostgreSQL URI、`secrets/postgres_password`はDB初期化用passwordだけを保存する。両fileと`.env.production`はGit・配布ZIPから除外する。APIと全WorkerはDSN fileを直接読み、passwordをcommand lineへ展開しない。

CaddyからAPIへのHTTPはDockerの`edge` network内だけで、APIはCaddyが付ける転送schemeを信頼して外部requestをHTTPSとして検証する。Caddyのcertificate dataとconfigはnamed volumeへ永続化する。

## PostgreSQL backup/restore

専用imageはPostgreSQL 17の`pg_dump`・`pg_restore`とPython manifest処理だけを含む。custom formatは`pg_restore`で内容確認と選択的復元ができ、圧縮も行う。[PostgreSQL pg_dump](https://www.postgresql.org/docs/current/app-pgdump.html)もcustom formatを柔軟なarchive形式としている。

```powershell
docker compose --env-file .env.production -f compose.production.yaml --profile operations build db-operations
docker compose --env-file .env.production -f compose.production.yaml --profile operations run --rm db-operations backup --output-dir /backups
docker compose --env-file .env.production -f compose.production.yaml --profile operations run --rm db-operations verify --manifest /backups/<name>.manifest.json
docker compose --env-file .env.production -f compose.production.yaml --profile operations run --rm db-operations drill --backup-dir /backups --report-dir /recovery-reports
```

backupはowner・privilegeを除いたcustom archiveと、schema version、作成UTC、DB名、`pg_dump`版、byte数、SHA-256を持つmanifestを同じdirectoryへ作る。verifyはpath traversal、size、checksumを検査してから`pg_restore --list`を実行する。SHA-256は破損検出であり署名ではないため、archiveとmanifestの保存先自体を信頼できる権限・不変storageで保護する。

restoreは既存objectを置換するため、API・Worker停止、直前backup、別環境での復旧試験を行ったうえで実施する。

```powershell
docker compose --env-file .env.production -f compose.production.yaml stop api run-worker statsforecast-worker mlforecast-worker timesfm-worker provider-conformance-worker timesfm-conformance-worker import-worker normalization-worker matching-worker daily-worker acceptance-worker selection-worker lifecycle-scheduler
docker compose --env-file .env.production -f compose.production.yaml --profile operations run --rm db-operations restore --manifest /backups/<name>.manifest.json --confirm-database kiban
```

`--confirm-database`がDSNの復元先DB名と一致しなければ処理しない。checksumと`pg_restore --list`の確認後、`--clean --if-exists --single-transaction --exit-on-error`で復元する。`--clean`は既存objectをdropするため、挙動は[PostgreSQL pg_restore](https://www.postgresql.org/docs/current/app-pgrestore.html)も参照する。

DB外のsnapshot、report、raw archive、acceptance report、model artifactは本CLIの対象外である。各mountを同じ復旧点として別途backupし、DBの参照URI・checksumと組み合わせる。

`drill`はPhase 2Dで追加した隔離復元訓練である。内部生成の一時DBへ復元し、元DBの安定性、内容一致、一時DB削除まで検査する。実行前に書込みを停止する。詳細は[PostgreSQL隔離リカバリ訓練](Phase2D_PostgreSQL隔離リカバリ訓練.md)を参照する。

## モジュール境界

| module | 責務 |
|---|---|
| `api/authentication.py` | role、固定token、credential file rotation、認可 |
| `api/oidc.py` | JWKSとJWT claim検証、外部role mapping |
| `api/http_security.py` | Host、HTTPS、response header |
| `api/observability.py` | 監査log、liveness、readiness、metrics |
| `runtime_config.py` | Worker共通のsecret file読込み |
| `operations/db_archive.py` | DB archive、manifest、checksum、restore安全条件 |
| `operations/database.py` | DB運用CLIと従来importの互換維持 |
| `operations/recovery/` | 一時DB、streaming指紋、訓練判定、不変証跡 |
| `deploy/` | Caddy、本番Compose、DB操作image |

`api/security.py`はPhase 1Qのimport互換だけを提供し、新規責務を持たない。

## 未実施

実IdPとの疎通、公開証明書の実取得、実データ・本番構成でのrestoreと災害復旧時間の計測、監視製品への接続、log不変保管、cloud backup、管理画面のAuthorization Code/PKCE loginは環境固有作業として未実施である。
