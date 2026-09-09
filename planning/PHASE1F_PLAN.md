# Phase 1F 実装計画

## ゴール

版付きdataset snapshotと実験定義をDBへ不変保存し、保存済み実験だけからrunを作る。組込baseline WorkerがPhase 1B artifactを保存・復元し、別プロセスをまたいでrunを完了できる状態にする。

## 範囲

1. snapshot・実験の内容アドレスID、schema version、condition fingerprint。
2. SQLite/PostgreSQL catalog migrationと作成・取得API。
3. サーバー側plan生成によるrun作成。任意planや実行コードは受け付けない。
4. snapshot checksum、known_at付き将来特徴量、builtin baseline executor。
5. ModelRef/ContextRefの保存・復元、予測・失敗・artifact参照・最終状態のresult API。
6. 別Workerプロセス再開E2E、互換性・認証・再現性試験、Compose・配布検証。

## モジュール境界

`catalog/`を契約・domain・永続化・ファイル検証へ分割する。`api/`はHTTP schema・ユースケース・route・構成を分離し、`executors/`が予測実行を担当する。`jobs/`は台帳・lease・結果表現に限定する。

## 完了条件

保存済み実験からだけrunが作成され、2つの別Workerプロセスが同じmodel artifactを復元して全起点を完了する。改ざんsnapshotは予測を保存せず失敗する。ruff、全pytest、demo、scale、artifact復元、wheel内容、checksumを確認しDraft PRを作る。

## 対象外

データupload、原本取込・名寄せ、role別認可、UI、分散queueサービス、TLS、本番secret管理、2方式目のOSS。
