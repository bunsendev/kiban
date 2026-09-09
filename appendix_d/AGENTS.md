# 開発ルール

CODEX_START_HERE.md → docs/統合仕様_v2.9.md → 全体仕様v2.2の順で読む。
pytestとruffを正式検証ゲートとする。check_lintは補助検査。
変更時はユーザーの既存作業を保護する。
仕様・実装・テストを同時に更新し、テスト削除で合格させない。
0と欠測、POINTと中央値、own/common/official集合を混同しない。
変更される将来変数はknown_atで時点選択し、生データの最終値を直接使わない。
配布前にtest_results.txtを更新し、make_release.py、make_release.py --checkを実行する。
実データ・資格情報はコミットしない。人工データのみで本番精度を保証しない。
Phase 1Kの匿名データ受入はDRY_RUNとし、実データ受入済みに変更しない。
受入の技術判定と担当者の業務判断を分け、判断履歴を上書きしない。
