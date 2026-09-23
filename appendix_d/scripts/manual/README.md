# 操作マニュアル動画の更新

担当者画面を変更したときに、実画面から動画素材を再生成するための補助scriptです。

1. APIと担当者画面を起動する。
2. 個人情報や業務データを含まない人工CSVを用意する。
3. Playwrightを利用できるNode.jsで`capture_easy_manual.cjs`を実行する。
4. Pillowと`imageio-ffmpeg`を利用できるPythonで`render_easy_manual.py`を実行する。
5. 音声を付ける場合は、生成した字幕版MP4とナレーション音声をffmpegで結合する。

撮影scriptは接続コード`preview-token`を使用するローカルpreview専用である。本番環境、本番接続コード、実データを撮影へ使用しない。

動画を更新したら、冒頭、各操作、受付完了、終了画面を抽出して目視確認し、音声streamと再生時間も確認する。
