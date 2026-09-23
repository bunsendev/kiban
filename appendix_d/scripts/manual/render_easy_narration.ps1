param(
    [Parameter(Mandatory = $true)]
    [string]$OutputPath
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Speech

$resolvedOutput = [System.IO.Path]::GetFullPath($OutputPath)
$outputDirectory = [System.IO.Path]::GetDirectoryName($resolvedOutput)
[System.IO.Directory]::CreateDirectory($outputDirectory) | Out-Null

$synthesizer = [System.Speech.Synthesis.SpeechSynthesizer]::new()
try {
    $japaneseVoice = $synthesizer.GetInstalledVoices() |
        Where-Object { $_.Enabled -and $_.VoiceInfo.Culture.Name -eq "ja-JP" } |
        Select-Object -First 1
    if ($null -eq $japaneseVoice) {
        throw "日本語のWindows音声が見つかりません。日本語音声を追加してから再実行してください。"
    }
    $synthesizer.SelectVoice($japaneseVoice.VoiceInfo.Name)
    $synthesizer.Rate = 3
    $synthesizer.Volume = 100
    $synthesizer.SetOutputToWaveFile($resolvedOutput)
    $ssml = @"
<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="ja-JP">
  <p>かんたん予測の、ファイル選択から分析結果の読み方までを説明します。</p>
  <break time="1800ms"/>
  <p>ステップ1。起動後に案内されたURLを開き、接続画面を確認します。</p>
  <break time="1600ms"/>
  <p>ステップ2。セットアップ時に渡された接続コードを入力し、接続するを押します。</p>
  <break time="1200ms"/>
  <p>ステップ3。ここを押してファイルを選択、を押し、CSVまたはZIPを選びます。</p>
  <break time="1700ms"/>
  <p>ステップ4。選択中のデータに表示された、ファイル名と容量を確認します。</p>
  <break time="1300ms"/>
  <p>ステップ5。準備できました、と表示されたら、データを分析するを押します。</p>
  <break time="1500ms"/>
  <p>ステップ6。受付番号と、結果を確認しています、の表示が出ます。画面を閉じず、そのまま待ちます。</p>
  <break time="900ms"/>
  <p>ステップ7。結果は、最初に色と見出しを確認します。緑は次へ進めます。黄色は一部を確認します。赤はデータを修正して、やり直します。</p>
  <break time="1300ms"/>
  <p>ステップ8。中央の件数を左から読みます。確認した件数、利用できる件数、確認が必要な件数です。確認が必要、がゼロなら、確認した範囲はすべて利用できます。</p>
  <break time="1000ms"/>
  <p>ステップ9。結果の読み方に、確認や修正が必要な項目が表示されます。緑で確認事項がなければ、次の予測実行へ進めます。</p>
  <break time="600ms"/>
  <p>この画面は、データが予測処理に使える形式かを確認した結果です。予測値や予測精度の結果ではありません。黄色、赤、またはエラーの場合は、受付番号と表示内容を管理担当者へ連絡してください。</p>
</speak>
"@
    $synthesizer.SpeakSsml($ssml)
}
finally {
    $synthesizer.Dispose()
}

Write-Output $resolvedOutput
