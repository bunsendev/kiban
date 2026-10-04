# Phase 3T Windows Portable Pilot完了Gate

## 目的

手順15-3で固定したPilot評価と最新の担当者判断を、既存の受入またはrollback履歴へ失わず引き渡す。評価後に別画面で根拠を転記する運用をなくし、古い判断や別の候補版による誤った状態遷移を防ぐ。

## 受入へ進める条件

- Pilot適用計画が`PILOT_ACTIVE`である。
- 評価Gateが全基準に合格している。
- 最新の担当者判断が`FORWARD_TO_ACCEPTANCE`である。
- 画面に表示された受入基準とrollback条件を担当者が全件確認する。
- 評価判断revisionと適用計画revisionが再読込時の値から変わっていない。

条件を満たしても自動受入は行わない。担当者が各基準の合否と根拠を入力し、監査記録として保存した時点で、既存の状態遷移規則により`ACCEPTED`または`ROLLBACK_REQUIRED`となる。

## rollbackへ進める条件

- Pilot適用計画が`PILOT_ACTIVE`または`ROLLBACK_REQUIRED`である。
- 最新の担当者判断が`REQUEST_ROLLBACK`である。または、同じ評価証跡を使った受入結果が`ROLLBACK_REQUIRED`である。
- 固定済みrollback先版と事前backupを使用する。
- 旧設定への復帰、アプリとAPIの再起動、既存データ参照を担当者が確認する。

検査の全件合格とbackup復元確認後にだけ`ROLLED_BACK`となる。復旧操作そのものは自動実行しない。

## 監査証跡

受入またはrollbackイベントには次を`pilot_evaluation_reference`として保存し、イベント全体のSHA-256へ含める。

- 評価ID、評価SHA-256、評価revision、評価基準版、合否
- Runtime週次評価IDとSHA-256
- 判断ID、判断SHA-256、判断revision、判断内容
- Pilot適用計画IDと遷移直前revision

評価判断の読込と適用状態遷移はPortable単一プロセス内の共通lockで直列化する。評価Gate作成後は旧受入・rollback APIからの直接遷移を拒否し、手順15-3の証跡付き経路を使用する。評価Gateが存在しない既存データには従来経路を残す。

## 画面操作

1. 手順15-3で評価Gateを固定し、担当者判断を保存する。
2. 同じ欄に表示される手順15-4を確認する。
3. 正式採用審査へ送る場合は、受入基準とrollback条件の全件に根拠を入力する。
4. Baselineへ戻す場合は、実際の復元後に3つの復旧検査と根拠を入力する。
5. 保存後、Pilot適用履歴の最終状態を確認する。

「観測を継続」「Pilotを停止」の判断からは状態遷移フォームを表示しない。Pilot停止の実作業は現行の管理手順で行い、必要なら判断を`REQUEST_ROLLBACK`として改めて記録する。
