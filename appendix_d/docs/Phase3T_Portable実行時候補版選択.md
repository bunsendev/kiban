# Portable実行時候補版選択

## 目的

承認済みの変更案をPilotで検証するとき、正式予測Runが実際に使った版を再現可能な証跡として残します。担当者が画面で承認しただけでは候補版を使いません。固定したPilot Scope、現在も有効な承認、Gateで確認したmanifest、配置済みmanifestの内容がすべて一致した場合だけ候補版を選びます。

この機能はSHADOW運用です。正式な出荷指示や現場全体の設定を自動変更しません。

## 実行時の判定

正式予測Runの登録時に、Inventory Snapshot jobからPilot Scope版を読み出し、Scopeごとに次を判定します。

| 条件 | 結果 |
|---|---|
| 有効な適用計画がない | `BASELINE_SELECTED` |
| 有効な適用計画が1件で、manifestと設定が一致 | `CANDIDATE_SELECTED` |
| 適用計画が複数、承認失効、証跡改変、manifest不在・重複・hash不一致 | `BLOCKED` |
| 1つのRunに異なる実行設定が混在 | `BLOCKED` |

対象外Scopeは常にBaselineです。候補版を暗黙に広げません。候補版ScopeとBaseline Scopeを同じRunで処理する必要がある場合は、Scopeを分けた別Runとして実行します。

## 候補manifest

管理者またはUpdaterが、Portableの `Data/State/RuntimeCandidates` にJSONを配置します。現場担当者が手作業で変更するファイルではありません。

```json
{
  "candidate_version": "candidate-model-v1",
  "format": "bunsen-portable-runtime-candidate-v1",
  "proposal_id": "field-formal-change-...",
  "runtime_configuration": {
    "model_name": "seasonal_naive_7",
    "params": {},
    "preprocessing_version": "portable-daily-state-v1",
    "provider_id": "builtin-baseline",
    "resource_profile": "cpu-small",
    "seed": 7,
    "version": "candidate-model-v1"
  }
}
```

ファイルそのもののSHA-256を、手順15のPilot開始Gateへ入力します。PowerShellでは次で確認できます。

```powershell
(Get-FileHash -Algorithm SHA256 -LiteralPath '.\Data\State\RuntimeCandidates\candidate-model-v1.json').Hash.ToLowerInvariant()
```

キー順、空白、改行の変更でもファイルhashは変わります。Gate後にmanifestを編集せず、新しい候補版として再発行してください。

## 現在実行できる候補設定

現在のPortable Workerが実行できるのは、組込Baseline adapterの固定契約だけです。候補版はこの契約内で版を識別できます。Provider、model、前処理、seed、資源profile、paramsのどれかが未対応なら `RUNTIME_ADAPTER_UNSUPPORTED` で停止します。任意コードや未確認モデルをmanifestだけで起動することはありません。

## 証跡

`field_runtime_assignment_resolutions`へ次を追記します。

- 実行キーとPilot Scope版
- Baseline、候補版、停止の判定
- 選択版と実行設定、そのSHA-256
- 適用計画ID、revision、正式変更案ID
- 候補manifest SHA-256
- 判定理由、担当者、known_at、recorded_at
- 証跡全体のcontent SHA-256

担当者画面の手順16で配置済み候補と選択履歴を確認できます。Production受渡し記録にも同じ解決結果を保存します。保存済み証跡または受渡し記録が変更された場合は表示・実行を拒否します。

## 主な停止理由

| reason_code | 対応 |
|---|---|
| `MULTIPLE_ACTIVE_ASSIGNMENTS` | 同じScopeの有効な適用計画を1件に整理する |
| `GATE_MANIFEST_HASH_MISSING` | manifest SHAを含む新しい適用計画を作る |
| `CANDIDATE_MANIFEST_NOT_UNIQUE` | 同じ候補版を示すmanifestを1件にする |
| `CANDIDATE_MANIFEST_HASH_MISMATCH` | Gateで確認したファイルを復元するか、新版として再承認する |
| `CANDIDATE_MANIFEST_CONTRACT_MISMATCH` | 正式変更案と同じ候補版・設定でmanifestを再発行する |
| `RUNTIME_ADAPTER_UNSUPPORTED` | 対応adapterを実装・試験してから新しい候補版を申請する |
| `MIXED_RUNTIME_CONFIGURATION_UNSUPPORTED` | 異なる設定をScope別のRunへ分ける |
| `APPLICATION_INTEGRITY_UNVERIFIED` | 適用計画台帳の保全状態を管理者が確認する |

旧版のGate記録にはmanifest SHAがありません。既存記録を上書きせず、新しい正式変更案・適用計画として作り直します。
