# Phase 1L 重要品目候補と選定版

## 目的

成功済み日次buildを候補母集団として、数量、数量構成比、変動係数、出荷0率、欠損率、JAN変更有無、業務指定を同じ条件で算出する。担当者が対象センターと品目別理由を確認した選定を`selection_version`で凍結し、後から上書きしない。

候補算出は判断材料を作る処理であり、品目を自動確定しない。予測結果を見た後に対象を変更する場合は、新しい`selection_version`を作り、後続では新しい`experiment_id`を発行する。元の版と結果は残す。

## 候補算出契約

候補算出jobは次を内容アドレス方式で固定する。

| 項目 | 内容 |
|---|---|
| `candidate_version` | 候補算出方針の業務版 |
| `daily_build_id` | 全候補商品・対象センター・分析期間・上流版を持つ成功済み日次build |
| `business_product_ids` | 担当者が明示した業務指定品目。自動推定しない |
| `max_missing_rate` | 選定可能とする欠損率上限 |
| `stable_cv_max` | `STABLE`分類の変動係数上限 |
| `intermittent_zero_rate_min` | `INTERMITTENT`分類の出荷0率下限 |
| `requested_by` / `purpose` | 依頼者と算出目的 |

日次buildのTRAIN開始からTEST終了までが分析期間になる。全3年で選定する場合は、この期間に全3年を指定し、`selected_series`には候補母集団の全商品×centerを含める。候補算出jobは不変なbuild IDを参照するため、分析期間、JAN mapping版、取扱期間版、休業版、availability modeへ追跡できる。

## 統計量と欠損規則

品目ごとに商品×center×日の値を集約し、対象center一覧も保存する。

| 指標 | 算出規則 |
|---|---|
| 数量 | `OBSERVED`と`CONFIRMED_ZERO`の`y`の合計 |
| 数量構成比 | 同じjobの全品目数量合計に対する比率。全体数量0なら`NULL` |
| 変動係数 | 利用可能値だけの母標準偏差÷平均。平均0以下なら`NULL` |
| 出荷0率 | 利用可能値のうち0である比率 |
| 欠損率 | `OBSERVED`、`CONFIRMED_ZERO`、`MISSING`、`PARTIAL_OR_INVALID`を分母とし、後二者を欠損として数える |
| JAN変更 | buildの`mapping_version`内で同一canonical productに複数JANがあるか |

`CLOSED`と`NOT_HANDLED`は欠損率の分母へ含めない。`MISSING`と`PARTIAL_OR_INVALID`を0へ変換せず、変動係数と出荷0率から除外する。利用可能値がない品目、取扱対象値がない品目、欠損率上限を超える品目は候補一覧へ理由付きで残すが、選定版には登録できない。

候補には次の分類tagを付ける。

- `STABLE`: 変動係数が`stable_cv_max`以下。
- `INTERMITTENT`: 出荷0率が`intermittent_zero_rate_min`以上。
- `JAN_CHANGED`: JAN変更あり。
- `BUSINESS_DESIGNATED`: 業務指定あり。

表示順位は、業務指定、数量降順、欠損率昇順、商品IDの順で決定する。順位は選定の自動判断ではない。

## 確定選定版

`INITIAL`は3〜5品目、`FULL`は20〜50品目を登録する。各品目には、候補で確認できる対象centerの部分集合と空でない選定理由が必要である。版全体には`selected_by`と`rationale`を保存する。

同じ`selection_version`で内容を変更できない。変更時は新しい版名を使う。選定版は候補jobを介して分析期間と上流データ版へ追跡できる。初期3〜5品目は、候補に存在する範囲で安定品、間欠品、JAN変更品を含めることを担当者が確認する。

## APIとWorker

Bearer認証付きAPIは次を提供する。

- `POST /api/selection-candidate-jobs`
- `GET /api/selection-candidate-jobs/{candidate_job_id}`
- `GET /api/selection-candidate-jobs/{candidate_job_id}/candidates`
- `POST /api/selections`
- `GET /api/selections/{selection_id}`
- `GET /api/selections/{selection_id}/items`

候補作成例は次のとおり。

```json
{
  "candidate_version": "three-year-candidates-v1",
  "daily_build_id": "daily-...",
  "business_product_ids": ["product-priority-a"],
  "max_missing_rate": 0.01,
  "stable_cv_max": 0.3,
  "intermittent_zero_rate_min": 0.5,
  "requested_by": "operator@example.jp",
  "purpose": "全3年の重要品目候補確認"
}
```

候補算出はHTTP request内で行わない。

```powershell
kiban-selection-worker `
  --postgres-dsn postgresql://kiban:***@127.0.0.1:55432/kiban
```

Docker Composeでは次を使う。

```powershell
docker compose --profile worker up -d --build selection-worker
```

候補成功後、担当者は候補APIの指標、分類、`center_ids`を確認し、`POST /api/selections`で確定する。

## 現在の制約

リポジトリには実データが配置されていないため、匿名3品目とPostgreSQL実DBで算出・確定手順を確認した。実データ全3年の候補算出、20〜50品目の業務確定、選定画面、選定版からの日次build再発行は未実施である。APIは画面実装が利用する不変な候補・選定契約を提供する。
