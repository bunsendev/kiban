# Phase 2K ローカル検証環境と実動受入

## 目的

Docker Desktop、PostgreSQL、API、マッピング検証Worker、`/ui/intake`を一続きで確認する。受入CLIは管理対象CSVから新しい検証jobと証跡を作るが、原本取込、正規化、業務承認は行わない。

## 通常起動

PowerShellでリポジトリへ移動し、次を実行する。

```powershell
docker version
docker compose --profile worker up -d --build postgres api mapping-dry-run-worker
docker compose ps
```

`postgres`が`healthy`、`api`と`mapping-dry-run-worker`が`Up`になったら、`http://127.0.0.1:58000/ui/intake`を開く。

## Docker Desktopがsocketエラーで起動しない場合

予期しない終了の後に`%LOCALAPPDATA%\Docker\run\*.sock`または`%LOCALAPPDATA%\docker-secrets-engine\engine.sock`で起動が止まる場合は、factory resetやデータ削除の前にruntime socketだけを退避する。`docker-desktop-data`のVHDX、volume、imageは移動しない。

```powershell
Get-Process -Name 'Docker Desktop','com.docker.backend' -ErrorAction SilentlyContinue | Stop-Process -Force
wsl --shutdown

$stamp = Get-Date -Format yyyyMMddHHmmss
if (Test-Path "$env:LOCALAPPDATA\Docker\run") {
  Move-Item -LiteralPath "$env:LOCALAPPDATA\Docker\run" -Destination "$env:LOCALAPPDATA\Docker\run.stale-$stamp"
}
New-Item -ItemType Directory -Path "$env:LOCALAPPDATA\Docker\run" -Force | Out-Null
if (Test-Path "$env:LOCALAPPDATA\docker-secrets-engine") {
  Move-Item -LiteralPath "$env:LOCALAPPDATA\docker-secrets-engine" -Destination "$env:LOCALAPPDATA\docker-secrets-engine.stale-$stamp"
}

Start-Process -FilePath 'C:\Program Files\Docker\Docker\resources\com.docker.backend.exe' -ArgumentList '-with-frontend=false' -WindowStyle Hidden
```

`docker version`でServer情報が返った後にDocker Desktopを起動する。退避フォルダーは安定稼働と必要データを確認するまで保持する。復旧しない場合は診断情報を採取し、[Docker Desktopのバックアップと復元](https://docs.docker.com/desktop/settings-and-maintenance/backup-and-restore/)に従ってデータを保護してから再インストールを検討する。

## API実動受入

tokenをcommand lineへ書かず、process環境変数から渡す。

```powershell
$env:KIBAN_API_TOKEN = '開発環境のtoken'
kiban-local-validation-acceptance `
  --source-path phase2i_sample.csv `
  --mapping-id map-f64c19be5b7c2a30a94a0a2be22f6773f566a2bc4e926b37f7d930490e6062af
Remove-Item Env:KIBAN_API_TOKEN
```

CLIは次を順番に検査し、全件合格時だけexit code 0と`status: PASSED`のJSONを返す。

1. livenessとreadiness
2. CSVが入力rootの安全な候補に存在すること
3. 不変mappingが存在すること
4. job登録とWorker完了
5. `READY_FOR_NORMALIZATION`
6. 固定9検査の全件合格

出力にはtoken、CSV本文、絶対path、列値を含めない。

## UI受入

1. `/ui/intake`へtokenで接続する。
2. 「CSVを選ぶ」で`phase2i_sample.csv`を選ぶ。
3. CSVのヘッダーに合う列の対応付けを選ぶ。
4. 「このCSVを検証」を押す。
5. Worker完了後、結果へ自動で移動することを確認する。初回更新より先にWorkerが完了した場合も同じ動作になる。
6. 「検証に合格しました」「このCSVは正規化へ進めます」と9件の「合格」を確認する。

## 2026-09-14 実測

- Docker Desktop 4.90.0、Engine 29.7.2、PostgreSQL 17.11
- `/health`: `ok`、`/ready`: `ready`、全readiness check合格
- API job `fee06eba-0d6d-4ed8-8c6a-dd20cbc33b58`: 1行採用、隔離0、9検査合格
- UI job `b06ce8aa-04f3-4f3a-bf41-ac3aae7cb207`: 1行採用、隔離0、`READY_FOR_NORMALIZATION`

人工CSVによる受入であり、実データ品質、予測精度、業務承認を示すものではない。
