# Phase 1I JAN名寄せと取扱期間

Phase 1Iは、現在採用中の原本から成功した正規化jobだけを入力にし、異なるJAN間の名寄せ候補を再現可能に生成する。APIは対象normalization ID、候補policy版、名称類似度、切替用類似度、許容日数を内容アドレス方式のjobとして保存する。候補計算は`kiban-matching-worker`がHTTP外で実行する。

比較名はUnicode NFKC、大小文字、連続空白を統一する。内容量や規格を示す数字は削除しない。通常の名称類似、または旧JANの最終出荷と新JANの初回出荷が近い場合を候補にする。候補には左右の原JAN・代表原商品名・名称類似度・初回/最終出荷日・併存日数・切替空白日数・単位・center別数量・候補理由を保存する。同じ入力とpolicyからは同じjob IDと候補IDを生成する。

候補は判断材料であり、名称一致だけでJAN対応表を作らない。業務承認者は`SAME_PRODUCT`、`DIFFERENT_PRODUCT`、`SUCCESSOR`、`UNRESOLVED`のいずれかを選び、承認者、理由、日時、mapping versionを不変履歴として保存する。SAME_PRODUCTは左右に同じcanonical productを、DIFFERENT_PRODUCTとSUCCESSORは別のproductを要求する。UNRESOLVEDはproductを指定しない。SUCCESSORは関連を記録する判断であり、数量系列の単純結合を意味しない。

canonical productはJAN変更に依存しない商品IDで、作成者と理由を保持する。JAN対応表は開始日と終了日をともに含む。終了未定はNULLとする。同じJAN・mapping versionの期間重複を拒否する。SQLiteは`BEGIN IMMEDIATE`、PostgreSQLはJAN・版単位のtransaction advisory lockで同時登録を直列化してから重複を検査する。

商品×center取扱期間も開始日と終了日を含み、確定値`CONFIRMED`と根拠付き暫定値`TENTATIVE`を保存する。同じ商品・center・period versionの期間重複を拒否する。期間外を日次データで`NOT_HANDLED`として扱う処理は後続段階で行う。初回/最終出荷日は候補表示に使うだけで、自動的に発売日・終売日とは断定しない。

認証付きAPIは次を提供する。

- `POST /api/matching/jobs`、`GET /api/matching/jobs/{id}`、`GET /api/matching/candidates`
- `POST /api/products`、`GET /api/products`
- `POST /api/matching/decisions`、`GET /api/matching/decisions`
- `POST /api/jan-mappings`、`GET /api/jan-mappings`
- `POST /api/handling-periods`、`GET /api/handling-periods`

この段階では規格・内容量・入数の自動抽出、JAN補正、自動承認、日次0補完、予定ファイル完全性、dataset snapshot自動発行を行わない。
