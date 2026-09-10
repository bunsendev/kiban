# Phase 1Q 実装計画

## ゴール

単一の共有Bearer tokenを、主体とroleを持つ複数credentialへ拡張する。すべてのAPI routeでサーバー側の権限検査を行い、監査用の担当者項目はrequest bodyではなく認証主体から確定する。本番modeではHTTPSとHost制約を強制し、APIと管理画面へ共通security headerを付与する。

## モジュール境界

`api/security.py`はrole・permission・token照合・監査主体・HTTP security境界を担当し、業務routeやstoreへtokenを渡さない。`api/factory.py`は環境変数を検証してcredentialとdeployment設定を構築する。各`*_routes.py`はendpointごとに必要permissionを宣言し、業務処理は既存serviceへ委譲する。

## 実装範囲

1. `VIEWER`、`ANALYST`、`APPROVER`、`ADMIN`と`READ`、`ANALYZE`、`APPROVE`、`EXPORT`の権限表を固定する。
2. `KIBAN_API_CREDENTIALS`のJSONから複数token、主体、roleを読み込み、tokenはSHA-256 digestでメモリ保持する。
3. 全APIのGET、分析操作、承認操作、CSV発行へendpoint単位の依存関係を設定し、不足時は403を返す。
4. `requested_by`、`decided_by`、`approved_by`、`selected_by`、`created_by`、`executed_by`を認証主体で上書きする。
5. `/api/session`で現在の主体、role、permissionを返し、管理画面へ接続主体と操作可否を表示する。
6. production modeでは複数credentialとHost allowlistを必須にし、`/api`と`/ui`へのHTTPを426で拒否する。
7. APIへ`no-store`、request ID、権限制限を含む共通security headerを付け、HTTPSではHSTSを付ける。
8. 従来の`KIBAN_API_TOKEN`はローカルdevelopment専用のADMIN互換として維持する。

## 完了条件

- VIEWERは比較・CSV取得を閲覧でき、分析・承認操作を403で拒否される。
- ANALYSTは取込・snapshot・実験・run・比較を操作でき、承認操作を拒否される。
- APPROVERは名寄せ・選定・受入・採用判断を操作でき、分析操作を拒否される。
- ADMINは全操作が可能で、監査主体はbodyの詐称値ではなくcredentialのsubjectになる。
- production設定不備と平文HTTPを起動時またはrequest時に拒否する。
- pytest、ruff、JavaScript、Docker、wheel、配布checksumが合格する。

## 対象外

OIDC/OAuthログイン画面、token発行・失効API、権限管理DB、外部IdP、TLS証明書の終端、電子署名、秘密管理製品への接続。
