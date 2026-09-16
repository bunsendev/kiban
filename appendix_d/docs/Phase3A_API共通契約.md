# Phase 3A API共通契約

## 目的

BUNSEN-FCST-IMPL-002 v2.2の15章に合わせ、作成APIの再送を安全に収束させ、APIエラーを
`code`、`message`、`details`、`request_id`へ統一する。個別routeへ同じ処理を追加せず、
FastAPIの共通route classと例外handlerで適用する。

## Idempotency-Key

`POST /api/*`は任意の`Idempotency-Key` headerを受け付ける。1〜200文字の表示可能ASCIIを許可する。
キーを付けない既存clientの挙動は変えない。

- 初回成功時はHTTP状態と1 MiB以下の応答本文を保存し、`Idempotency-Replayed: false`を返す。
- 同じ認証token・route・キー・要求なら保存済み応答を返し、headerを`true`にする。
- 同じscopeで本文、path、query、Content-Typeが変わった場合は409にする。
- 処理中の同一要求は409にする。処理中leaseは15分で、異常終了後の再取得を許可する。
- 4xx、5xx、1 MiBを超える応答は保存せず、修正後の再送を許可する。
- scopeと要求はSHA-256で保存し、token、Idempotency-Key、要求本文を台帳へ保存しない。

本番factoryはPostgreSQLの`api_idempotency_records`を使う。SQLiteとメモリ実装はテスト、単一process、
組込み利用向けである。成功応答の保存と業務更新は別transactionのため、記録DB障害時は500となる。
業務側の一意制約と内容アドレスIDは引き続き維持する。

## エラー応答

HTTP例外、Pydantic入力検証、未知のサーバー例外を次の形式に統一する。

```json
{
  "code": "VALIDATION_ERROR",
  "message": "入力値を確認してください",
  "details": {},
  "request_id": "..."
}
```

入力検証の`details.issues`はlocation、type、messageだけを含み、入力値を反射しない。未知の例外本文も
公開しない。HTTPS・Host拒否も同じ形式を使う。`X-Request-ID`と本文の`request_id`は一致する。

## 検証

- 同一要求の再送とAPI process再作成後のreplay
- 同じキーを異なる要求へ使った場合の409
- 失敗要求がキーを占有せず、修正後に成功できること
- 認証、404、入力検証、HTTPS、Host拒否の統一形式
- PostgreSQL台帳のclaim、complete、replay

