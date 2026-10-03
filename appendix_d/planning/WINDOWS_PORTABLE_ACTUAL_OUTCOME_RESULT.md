# Windows Portable 後日実績・判断比較 実装結果

## 目的

Windows Portable の SHADOW 出荷試算について、System の予測・推奨、担当者判断、後日判明した実績を同じ `JAN × 倉庫 × 業務日` で比較できるようにした。現場確認の結果を設定へ自動反映せず、改善判断に使える監査可能な事実として追記保存する。

## 操作

1. 手順9で推奨出荷量を試算する。
2. 手順10で担当者判断を保存する。
3. 手順11の「この試算用の実績CSVを保存」を押す。
4. CSVへ確認できた値を入力する。各行に最低1項目が必要で、空欄は未取得、文字列 `0` は確認済みゼロとして扱う。
5. 実績データ版と実績判明日時を入力し、確認欄を選択して保存する。
6. 画面で System、担当者、実績、需要予測誤差、欠品、期限切れ、倉庫間移動を確認する。

## データ契約

既存の `field_actuals` と `field_learning` 契約を再利用する。CSV列は次の固定順である。

```text
case_id,expected_revision,unit,actual_shipped_quantity,actual_demand_quantity,stockout_quantity,expired_quantity,interwarehouse_transfer_quantity
```

- `unit` は V1 の正式単位 `CASE`。
- 業務日は推奨試算の計算日。
- System需要予測は到着予定時点までの累積需要。
- 実需要も同じ到着予定時点までの累積値を入力する。
- 実出荷は当該推奨に対応する実績を入力する。
- 訂正はテンプレートを再取得し、増加した `expected_revision` で追記する。
- 同一原本の再送は同じ結果へ収束し、古い版からの上書きは拒否する。

## 比較表示

- 需要予測の MAE、WAPE、Bias は実需要がある行だけで計算する。
- 欠品、期限切れ、倉庫間移動は合計と取得件数を併記する。
- 取得が0件の指標は `0` ではなく未取得として表示する。
- System推奨、担当者判断、実出荷の差を行ごとに保持する。
- 比較結果だけから因果関係、モデル採用、policy変更を自動決定しない。

## 安全性と監査

- SHADOW modeを固定し、正式な出荷指示へ昇格しない。
- Reference caseと実績eventは既存のcontent hash、revision、known_at、recorded_atを持つ追記型台帳へ保存する。
- 推奨結果と日次サマリーのSHA対応を検証し、別試算のcase IDを拒否する。
- APIはlocalhost、Origin、CSP等の既存Portable境界内で動く。
- CSV原本はDBへ保存せず、SHA-256と構造化された実績eventを保存する。

## テスト範囲

- UIとJavaScript配信
- 実績未取得時のNULL表示
- テンプレート発行と20ケースの取込
- 空欄と確認済みゼロの区別
- KPI取得件数
- 同一原本の冪等再送
- 既存の正式予測、Decision入力、推奨試算、担当者判断との一連接続

実データ、認証情報、現場固有の原本はRepositoryへcommitしない。
