# ブンセン 予測OSS比較基盤 — 修正完成パッケージ v2.9

v2.8レビューの指摘を反映した予測・比較コアです。
コード、全体仕様、統合仕様、開始ガイド、テスト、人工データデモ、検証記録を同梱しています。
原本CSV取込、JAN名寄せ、DB/API/UI、実OSSアダプター、本番運用は後続開発です。

## 最初に読む

1. CODEX_START_HERE.md
2. docs/統合仕様_v2.9.md（現行契約を一つに統合）
3. docs/実装仕様書_v2.2_完全版.md（基盤全体の要件とフェーズ図）

本文の版とコードの版は別管理です。旧差分文書を読み重ねる必要はありません。

## v2.9修正

- own_metricsを自run自身だけの評価へ修正。
- 正式比較集合を完全runだけから作成。不完全run追加による縮小を防止。
- official_comparison_set_idを追加。正式候補・キー集合を識別。
- 完全run1件は単独評価、2件以上で正式ランキング可能とする。
- カレンダー変数は内部生成、変更される将来変数はknown_at以前の最新版を選ぶ。
- 旧検証記録を更新し、重複コード・内包ZIPを含まない配布に整理。

## Windows PowerShell

Python 3.12で検証。ZIPを展開しappendix_dフォルダで実行します。

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\python.exe demo.py --output demo_output
.\.venv\Scripts\python.exe make_release.py --check
```

## macOS / Linux

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
.venv/bin/python demo.py --output demo_output
.venv/bin/python make_release.py --check
```

全テストの実行はpytest。従来の `python tests/test_builtin_baseline.py` は47件のみなので全件確認を代替しません。
ruffが利用できない場合のcheck_lint.pyは限定的な補助検査であり、正式出荷ではruffも必須です。
100系列規模確認は `python scale_check.py`。デモは人工データ3系列・3年を使用し、実データ精度ではありません。
初回依存インストール以外にAPIキー・ネットワーク接続は不要です。

## 出力

Phase 1BはModelRef/ContextRefをローカルへ保存し、別プロセスで復元するAPIを追加します。
`python artifact_demo.py verify --output artifact_output`で再fitなしの予測一致を確認できます。
形式・使い方・制約は[保存と復元](docs/Phase1B_保存と復元.md)を参照してください。
既定のartifact_outputはGit/配布ZIPから除外します。業務Workerの再開機能は未実装です。

デモは予測CSV、失敗照合台帳CSV、15日累計CSV、比較JSONを作成します。
比較JSONではown/common/officialを区別し、各件数と集合IDを確認してください。

## 配布・更新

test_results.txtはこの版の実測記録です。依存はrequirementsファイル、実行環境は記録を参照。
変更後はテスト・ruffを実行し、検証記録を更新してから `python make_release.py` で再配布します。
最後に `python make_release.py --check` で照合します。ZIPは親フォルダに生成されます。

## Run API / Worker

API依存は`pip install -e ".[api,postgres]"`で追加する。`KIBAN_POSTGRES_DSN`と`KIBAN_API_TOKEN`を設定し、`uvicorn forecast_provider.api.factory:from_environment --factory`で起動する。Workerはデプロイ済みOriginExecutorを指定して`kiban-worker --postgres-dsn <DSN> --executor package.module:execute --worker-id <ID>`で別プロセスとして起動する。
ソース編集後、ハッシュ再生成前の配布整合テスト失敗は想定内ですが、その状態で出荷しないでください。

旧版のModelRef/stateは再利用せずfitから実行します。v2.8の生データ将来列はknown_at付き版へ移行します。
元の提出ZIPは変更していません。既存プロジェクトへ導入する際は作業ブランチで差分を確認してください。
