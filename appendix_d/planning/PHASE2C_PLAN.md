# Phase 2C 実装計画

## ゴール

実業務原本をPhase 1Xへ投入する前に、data rootとPostgreSQLがPhase 1X〜1Kの処理境界を満たすか一回のCLIで検査し、秘密値や原本情報を含まない不変な技術証跡を残せるようにする。

## 実装範囲

1. 取込入力、原本archive、snapshot、受入report、プリフライトreportの5 rootを明示する。
2. 全rootの存在、directory、読取、symlink、相互重複、application root外を検査する。
3. 取込入力は実効read-only、残る4 rootは実効read-writeであることを一時probeで確認する。
4. PostgreSQL 17への接続、Phase 1X〜1Kで必要な23 relation、SELECT・INSERT・UPDATE権限を検査する。
5. filesystem、database、判定、保存、CLIを別moduleにする。
6. 開発・本番Composeに一回実行のpreflight serviceを追加し、本番DSNはsecret fileだけから読む。
7. 10項目の結果を内容アドレス方式のJSONへ保存し、仕様、テスト、配布checksum、日本語PRを更新する。

## 完了条件

- 原本本文、原本名、data rootのlocal path、database/user名、DSN、credentialをレポートへ保存しない。
- symlink、root重複、application内data root、権限不一致、DB接続・版・schema・権限不足は`BLOCKED`になる。
- 全10項目を満たす場合だけ`READY_FOR_DATA`になり、同じ内容の証跡を上書きしない。
- input rootへのwrite probeが成功してしまう構成を許可しない。
- pytest、ruff、実PostgreSQL、実Docker mount、開発・本番Compose、wheel、配布checksumが成功する。
- `READY_FOR_DATA`を実データ受入、予測精度、業務判断、本番復旧の完了として扱わない。
