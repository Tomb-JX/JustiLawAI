# 批量识别图片（Windows 自带 OCR，Windows.Media.Ocr）。写法沿用 astrbot-ops/pc/gapfill/gapfill/win/vision_lib.ps1。
# 只能用 Windows PowerShell 5.1 运行（PowerShell 7 加载不了 WinRT 类型）；本文件须保存为带 BOM 的 UTF-8。
# 输入：环境变量 OCR_LIST 指向一个 UTF-8 文本文件，每行一个图片路径
# 输出：环境变量 OCR_OUT 指向的 JSONL 文件，每行 {"path":..., "lang":..., "lines":[...], "error":...}
$ErrorActionPreference = "Continue"
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
  $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
function Await($op, [Type]$t) { $task = $asTask.MakeGenericMethod($t).Invoke($null, @($op)); [void]$task.Wait(-1); $task.Result }
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.SoftwareBitmap, Windows.Graphics.Imaging, ContentType = WindowsRuntime]
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
$lang = $engine.RecognizerLanguage.LanguageTag
$paths = [System.IO.File]::ReadAllLines($env:OCR_LIST, [System.Text.Encoding]::UTF8)
$out = New-Object System.IO.StreamWriter($env:OCR_OUT, $false, (New-Object System.Text.UTF8Encoding($false)))
foreach ($p in $paths) {
  if (-not $p) { continue }
  $rec = [ordered]@{ path = $p; lang = $lang; lines = @(); error = "" }
  try {
    $fs = [System.IO.File]::OpenRead($p)
    $ras = [System.IO.WindowsRuntimeStreamExtensions]::AsRandomAccessStream($fs)
    $dec = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($ras)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $sb = Await ($dec.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    $res = Await ($engine.RecognizeAsync($sb)) ([Windows.Media.Ocr.OcrResult])
    $fs.Dispose()
    $rec.lines = @($res.Lines | ForEach-Object { $_.Text -replace ' ', '' })
  } catch { $rec.error = $_.Exception.Message }
  $out.WriteLine(($rec | ConvertTo-Json -Compress -Depth 3))
  $out.Flush()
}
$out.Dispose()
