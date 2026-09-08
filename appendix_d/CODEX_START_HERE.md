# Codex開始ガイド v2.9

README → docs/統合仕様_v2.9.md → docs/実装仕様書_v2.2_完全版.mdの順で読む。
これは予測・比較コアの修正完成パッケージ。基盤全体の本番完成ではない。

## 起動確認

READMEのOS別手順で依存をインストールする。

```text
python -m pytest -q
ruff check .
python demo.py --output demo_output
python make_release.py --check
```

全体の件数・結果はtest_results.txt。旧標準ランナー47件だけで完了判定しない。

## 維持する仕様

- 固定学習と月次再学習を混ぜない。現在のrunnerは固定方式。
- 確定ゼロだけ0。欠測はNaN、予測失敗は全予定の台帳に残す。
- POINTと中央値を別保存する。
- ownは自run集合、commonは全run共通、officialは完全runのみの共通集合。
- 単独精度が比較相手の追加で変わらないことを維持する。
- comparison_set_idとofficial_comparison_set_idを別々に保存する。
- 正式候補1件は単独評価。優勝という表示をしない。
- 将来変数はカレンダー内部生成かknown_atによる版選択。最終確定列を直接使わない。
- 失敗例外の記録と契約違反による停止を区別する。

## 開発順

統合仕様11章の未実装Contractを整え、原本取込・JAN名寄せ・日次整形、DB、実データ3〜5品目、2つ目のOSS、UI・Worker・再学習の順に進める。
受入前に実データ検証を行い、人工データだけで精度や業務効果を保証しない。

## 変更報告

変更ファイル、理由、契約への影響、pytest・ruff・実データ検証、未対応事項を記載する。
契約変更は仕様・コード・テストを同時更新し、テスト削除や期待値の弱体化で通さない。
