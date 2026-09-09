# Phase 1G 原本取込台帳

Phase 1Gは原本CSVを変換する前に、受領したbyte列と処理判断を追跡できる入口を追加する。`POST /api/imports`はサーバー管理下の入力rootからの相対pathを受け取り202を返す。HTTP requestではファイルを展開せず、`kiban-import-worker`がjobを取得する。`GET /api/imports/{id}`はjob集計とファイル台帳を返す。

Workerは単一ファイル、フォルダ、ZIPを扱う。入力root外へのpath、ZIPの絶対path・`..`、大文字小文字を無視した同名衝突、設定上限を超えるファイル数・単体容量・展開後総容量を拒否する。ZIPは容量情報を読み込み前に検査する。

各原本はSHA-256で識別し、archive rootのhash pathへbyte列を変更せず保存する。同一hashは`DUPLICATE`として再保存・二重処理しない。同じ論理pathで異なるhashは`CORRECTION_CANDIDATE`とし、以前の原本IDを保持する。自動で最新版を採用しない。

文字コードはBOM付きUTF-8、UTF-8、CP932を置換なしで判定する。判定不能なファイルは`QUARANTINED`としてerrorを残し、同じjob内の正常ファイルは継続する。この段階では列名を推測せず、行の正規化や数量集計を行わない。

Composeでは`KIBAN_IMPORT_DIR`をread-only入力、`KIBAN_RAW_ARCHIVE_DIR`を不変原本の保存先として取込Workerへmountする。実データはGitと配布ZIPに含めない。
