# Phase 2E OIDC Authorization Code + PKCEログイン

## 目的

管理画面の手入力Bearer token互換を維持しながら、外部IdPのpublic clientからAuthorization Code Flow with PKCE（S256）でaccess tokenを取得する。全7画面が同じ`pkce.js`と`api.js`を使用する。

access tokenはJavaScript module memoryだけに保持し、URL、cookie、`localStorage`、`sessionStorage`へ保存しない。redirectをまたぐためのstate、PKCE verifier、戻り先、作成時刻だけを`sessionStorage`へ最大5分間保存し、callback処理の開始時に削除する。

## 処理

1. `/api/ui-auth/config`からauthorization URL、public client ID、scope、固定callback pathを取得する。
2. Web Cryptoでstateとverifierを生成し、verifierのSHA-256をbase64url化したchallengeを付けてIdPへ移動する。
3. `/ui/auth/callback`でstateと5分の期限を検証し、callback queryを`history.replaceState`で直ちに消去する。
4. code、verifier、同一originのredirect URIを`/api/ui-auth/exchange`へPOSTする。
5. APIが固定token endpointへform POSTし、Bearer access tokenと有効期間だけをブラウザーへ返す。refresh tokenとID tokenは返さない。
6. access tokenを共通API clientのmemoryへ設定し、署名・claim・roleを既存OIDC authenticatorで検証して画面を読込む。

APIはredirect URIをrequest originと固定pathから再構成して完全一致を要求する。authorization/token endpointはuserinfo・fragmentのないHTTPS URLに限定し、token応答を64 KiB、access tokenを16 KiB、有効期間を1日以下に制限する。code交換エラーの本文やtokenはlogへ出力しない。

## 設定

IdP側へ`https://<KIBAN_DOMAIN>/ui/auth/callback`を完全一致のredirect URIとして登録し、Authorization CodeとPKCE S256を有効にする。client secretをブラウザーや本構成へ設定しない。

```dotenv
KIBAN_OIDC_AUTHORIZATION_URL=https://id.example.jp/tenant/authorize
KIBAN_OIDC_TOKEN_URL=https://id.example.jp/tenant/token
KIBAN_OIDC_CLIENT_ID=yosoku-kiban-ui
KIBAN_OIDC_SCOPES=openid profile
```

JWT issuer、audience、JWKS、role mappingはPhase 1Rの既存設定を使用する。IdPが発行するaccess tokenはAPI audience、非対称署名、`sub`、`iat`、`exp`、割当済みroleを満たす必要がある。

## モジュール境界

| module | 責務 |
|---|---|
| `api/oidc_login.py` | public client設定、redirect URI検査、token endpoint交換 |
| `api/oidc.py` | access tokenの署名・claim・role検証 |
| `ui/static/pkce.js` | state/verifier、S256 challenge、callback、memoryへのtoken引渡し |
| `ui/static/api.js` | memory内tokenとBearer API request |

模擬IdPによる試験はprotocolと秘密情報境界の検証である。環境固有IdPとの実疎通、管理者同意、role claim設定、失効・logout連携は本番受入で確認する。
