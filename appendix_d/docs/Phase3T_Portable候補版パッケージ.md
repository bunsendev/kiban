# Portable候補版パッケージ

## 目的

手順14で別担当者が承認した予測モデル変更案を、手作業でmanifestへ転記せず、Portableの固定Workerで実行可能な候補版として発行します。発行時に人工データでProviderを起動し、設定、Provider版、資源上限、smoke test結果、rollback先を1つのmanifestへ固定します。

この機能は限定したPilot Scopeで使うSHADOW候補版の準備です。正式設定への昇格、出荷指示、未承認設定の実行は行いません。

## 操作

1. 手順14で予測モデル変更案を作成し、別担当者が実装承認します。
2. 手順15-1で承認済み変更案と、対応済みの固定候補設定を選びます。
3. 発行担当者、確認日、承認済み変更案の再確認を入力します。
4. ［候補版パッケージを発行］を押します。
5. `PASSED`、予測点数14件、manifest SHA-256、資源上限を確認します。
6. 手順15-2で、この候補版を使うPilot適用計画を作成します。
7. 開始Gateでは発行済みmanifestのSHA-256が自動設定されます。smoke testとrollback条件を評価します。
8. 手順16で正式予測Runを登録し、実際に選ばれたruntime versionを確認します。

## 実行できる固定候補

| model | 用途 | 最低履歴 |
|---|---|---:|
| `seasonal_naive_7` | 7日前の同じ曜日を利用 | 7日 |
| `moving_average_28` | 直近28日の平均を利用 | 28日 |
| `same_weekday_mean_4` | 過去4週の同じ曜日の平均を利用 | 28日 |
| `seasonal_naive_364` | 364日前の同じ曜日を利用 | 364日 |

設定は組込Baseline Providerの公開契約と完全一致するものだけを許可します。任意のPython、任意のコマンド、未知のパラメータは候補版へ入りません。

## 発行時smoke test

人工の2系列・400日を使い、実際のProvider registryから対象Providerを取得して次を実行します。

1. 入力検証
2. fit
3. contextの復元確認
4. 7日予測
5. 2系列×7日＝14点のPOINT予測、有限値、重複なしを確認
6. 入力・出力・設定からsmoke結果hashを生成

これは配線と実行契約の検査です。実データに対する精度合格を意味しません。

## 資源境界

- profile: `cpu-small`
- 最大系列数: 50
- 最大履歴: 400日
- 最大予測期間: 28日
- 最大thread数: 1
- 外部通信: 禁止

候補版を選んだ正式予測Runは、Dataset SnapshotやRunを作成する前にこの上限を確認します。

## 保存と改変検知

- manifest: `Data/State/RuntimeCandidates/<candidate_version>.json`
- 発行証跡: `Data/State/RuntimeCandidatePackages/<package_id>.json`
- 実行時選択: `Data/State/runtime.sqlite3`
- Production受渡し: `Data/State/production-handoff.sqlite3`

package IDは内容から生成します。同じ候補版名へ異なる内容を再発行できません。承認revision、設定hash、Provider版、資源上限、rollback先、smoke結果がmanifestと一致しない場合は実行前に停止します。従来のv1 manifestは読み取り互換を維持します。

## 停止条件

- 未承認、承認失効、または予測モデル以外の変更案
- 候補版とrollback先が同じ
- 未対応Provider、model、設定
- smoke test不合格
- 同じ候補版名に異なる内容が存在
- manifestまたは発行証跡の改変
- Pilot Scope、承認revision、設定hashの不一致
- 系列数、履歴、予測期間などの資源上限超過

新しいOSSモデルを追加するときは、専用Worker、設定codec、依存ライブラリ、ライセンス、資源profile、外部通信を使わない決定的smoke testを先に実装します。
