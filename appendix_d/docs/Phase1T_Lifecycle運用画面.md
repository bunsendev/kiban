# Phase 1T Lifecycle運用画面

Phase 1Tは、Phase 1Sで追加した月次再学習とモデル切替の操作を、FastAPIと同一originの専用画面`/ui/lifecycle`へ接続する。画面は操作後に台帳を再読込し、championやrevisionをブラウザーだけで更新しない。

## 画面への接続

開発環境ではAPIを起動して`http://127.0.0.1:58000/ui/lifecycle`を開く。比較・採用画面`/ui`とLifecycle画面は相互リンクする。

Bearer tokenはJavaScript moduleのメモリ内だけに保持し、URL、cookie、`localStorage`、`sessionStorage`へ保存しない。切断時にメモリ上のtokenを破棄する。

## 表示する証跡

- Lifecycle計画数、待機中cycle数、昇格可能cycle数、trial予測記録数
- plan version、採用判断、月次Experiment、trial期間、schedule、昇格基準
- 現在championとrevision
- 全月次cycleの状態、challenger、改善率
- 全champion eventの承認者、理由、時刻
- trial予測の事前記録と30日評価履歴

状態APIは現在championに加えて`champion_events`を返す。rollback候補はfallbackと過去eventのchampionから作り、現在championを除外する。最終可否はLifecycle serviceが再検証する。

## 操作と権限

| 操作 | 権限 | サーバー検証 |
|---|---|---|
| 計画作成 | APPROVE | ADOPTED判断、月次Experiment、selection、成功run |
| scheduler実行 | ANALYZE | timezone付き期限、trial期間、月単位の冪等性 |
| cycle完了・失敗 | ANALYZE | run終端状態、比較、planとの一致 |
| challenger昇格 | APPROVE | READY、WAPE・失敗率gate、champion revision |
| rollback | APPROVE | fallback・過去champion、champion revision |
| trial予測記録 | ANALYZE | 成功origin、現champion条件、最初の実績利用前 |
| trial評価 | APPROVE | 30日以上、全対象日coverage、FUTURE_TRIAL比較 |

監査主体はフォーム入力を使わず、APIが認証済みsubjectから確定する。画面の権限制御は誤操作を減らす表示制御であり、認可の根拠はAPI側にある。

## 月次運用手順

1. `/ui`で実データ比較と採用判断を確定する。
2. `MONTHLY_EXPANDING` Experimentを登録する。
3. `/ui/lifecycle`で採用判断とExperimentを結ぶ計画を作成する。
4. schedulerが作成した待機cycleへ、完了済みchallenger runと比較IDを登録する。
5. `READY`になったcycleをAPPROVE利用者が理由付きで昇格する。
6. 問題時はfallbackまたは過去championへrevision付きでrollbackする。
7. 日々の成功予測を実績利用可能前に記録し、30日以上経過後にFUTURE_TRIAL比較で評価する。

Schedulerはsnapshot、Experiment、runを推測して作成しない。当該締切までの実績を持つ不変snapshotを作成してから、担当処理が既存APIとWorkerでrunを完了させる。

## モジュール境界

| ファイル | 責務 |
|---|---|
| `lifecycle.html` | semantic HTML、フォーム、表示領域 |
| `lifecycle.css` | Lifecycle固有layout |
| `lifecycle_api.js` | Lifecycle APIのrequest組立て |
| `lifecycle_render.js` | DOM生成、台帳と選択肢の描画 |
| `lifecycle_app.js` | state、権限、event、再読込 |

既存の`api.js`はtokenと共通HTTP境界、`format.js`は表示形式、`styles.css`は共通デザインを担当する。HTMLへデータを文字列連結せず、動的値は`textContent`で挿入する。

## 未実施事項

この画面の追加だけでは実データtrialは完了しない。3〜5品目の実データ受入、全3年の重要品目選定、実データrunと採用判断を作成し、連続30暦日以上の予測記録を蓄積する必要がある。
