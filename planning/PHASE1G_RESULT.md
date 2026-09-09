# Phase 1G 実装結果

## 結果

原本処理の入口を`ingestion` packageとして追加した。APIは取込jobを登録し、独立Workerがサーバー管理領域のファイル・フォルダ・ZIPを検査して、原本と判断結果をSQLite/PostgreSQL台帳へ保存する。

## 安全性と監査

- 入力root外のpath、symbolic link、ZIP traversalを拒否する。
- ZIPとフォルダの同名衝突、ファイル数、単体容量、展開後総容量を読み込み前に検査する。
- UTF-8 BOM、UTF-8、CP932を置換なしで判定し、不正ファイルだけを隔離する。
- 原本byte列はSHA-256の内容アドレス方式で不変保存する。
- 同一hashは`DUPLICATE`、同一論理pathで異なる内容は`CORRECTION_CANDIDATE`として関連元を記録する。
- jobとファイル単位の状態・件数・errorをBearer認証付きAPIから取得できる。

## 構成

契約、台帳、検査・保管、Worker CLI、HTTP routeを分割した。CSV列変換やJAN判定を原本保存処理へ混在させていない。Composeでは入力を読み取り専用mount、原本archiveを別の書込みmountにした。

## 検証

全pytest、ruff、別プロセスE2E、demo、scale check、artifact復元、wheel同梱、配布checksumを確認した。PostgreSQL実DBとCompose実起動はDocker/PostgreSQLがある環境で追加確認する。

## 次段階

明示的な列mapping版を使ったshipment row正規化、数量照合、訂正採用、品質集計を実装する。その後にJAN名寄せ承認と日次観測版の確定へ進む。
