# Phase 1R 実装計画

## ゴール

Phase 1Qのrole別認可を外部IdPと本番運用へ接続する。署名・issuer・audience・期限を検証するJWT/OIDC認証、停止せずに更新できるcredential、構造化監査log、readinessと低cardinality指標、checksum付きPostgreSQL backup/restore、CaddyによるTLS終端を一つの運用契約として整備する。

## モジュール境界

- `api/authentication.py`: 認証共通型、固定token、credential file rotation、role認可。
- `api/oidc.py`: JWKS鍵選択、JWT claim検証、IdP role変換。
- `api/http_security.py`: Host・HTTPS・response header境界。
- `api/observability.py`: 構造化監査log、request指標、liveness/readiness。
- `operations/database.py`: PostgreSQL custom archive、manifest、checksum、復元安全条件。
- `deploy/`: TLS reverse proxyと本番Compose。秘密値はDocker secretから読む。

## 実装範囲

1. `KIBAN_AUTH_MODE=token|oidc`で認証方式を明示し、既存development tokenを維持する。
2. OIDC access tokenの署名、許可algorithm、issuer、audience、`sub`、`iat`、`exp`を検証する。
3. JWKSの`kid`更新とcredential JSON fileのatomic置換によりrotation・失効を再起動なしで反映する。
4. 認証済み変更操作をsubject、role、route、status、request ID付きJSON logへ出力し、token・body・queryを記録しない。
5. 公開liveness `/health`、依存確認 `/ready`、READ権限付きPrometheus text `/metrics`を分離する。
6. PostgreSQL custom-format backupへSHA-256 manifestを付け、検証後だけ対象database名の明示一致を条件にrestoreする。
7. Caddyのautomatic HTTPSと内部API proxyを本番Composeへ追加し、API portを外部公開しない。
8. DSN・credentialを`*_FILE`から読み、秘密値を環境変数やrepositoryへ直接置かない本番例を追加する。

## 完了条件

- OIDCの正しいJWTだけがsubjectとroleへ変換され、署名・issuer・audience・期限・role不正を401で拒否する。
- credential fileの追加・削除・不正更新を検知し、不正時はfail closedかつreadinessが失敗する。
- 監査logとmetricsにcredential、Authorization、request body、queryが含まれない。
- readinessが認証・PostgreSQL・必要directoryを個別に判定する。
- backupのchecksum改変、対象database不一致、manifest traversalをrestore前に拒否する。
- pytest、ruff、JavaScript、Docker構成、wheel、配布checksumが合格する。

## 対象外

IdP tenant自体の作成、ユーザー招待・MFA policy、DNS変更、公開証明書の実取得、監視製品への送信、backup保管先のクラウド設定、実データのrestore実行、災害復旧訓練。
