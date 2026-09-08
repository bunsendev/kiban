# Phase 1E 実装計画

## ゴール

run作成・状態確認・キャンセル・同条件再開の最小HTTP APIと、HTTP外で起点予測を実行する独立WorkerプロセスをPhase 1DのRunStoreへ接続する。

## 範囲

1. FastAPIの厳密なrequest/response schemaとBearer認証。
2. HTTPに依存しないRunService。
3. RunStoreのrun snapshot・実行可能run列挙。
4. import可能なOriginExecutorを利用する独立Worker CLI。
5. API、状態遷移、競合、エラー応答、別Pythonプロセスのテスト。
6. API/Workerを含むDockerfile・Compose、運用文書、配布検証。

## モジュール境界

`api/schemas.py`はHTTP型、`api/service.py`はユースケース、`api/app.py`はroute・認証・status code、`api/factory.py`は環境構成、`worker_process.py`はプロセスloopだけを担当する。予測ロジックやProviderをrouteへ入れない。

## 完了条件

POST/GET/cancel/resume、422/401/404/409、同条件再開、Workerのrun取得、別プロセス完了、複数Worker中のRUNNING維持を検証する。全pytest、ruff、demo、scale、artifact復元、wheel、配布checksumを通しDraft PRを作る。

## 対象外

実験作成・データupload API、Web UI、任意コードupload、分散queue、権限role、TLS終端、本番secret管理、追加OSS。
