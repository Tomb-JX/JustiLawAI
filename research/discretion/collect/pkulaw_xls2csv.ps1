<#
.SYNOPSIS
  北大法宝「目录列表」.xls（BIFF8 二进制，Python 无 xlrd 读不了）→ UTF-8 CSV。
  用本机 Excel COM 完成；多工作表逐个导出为 <OutDir>\catalog_1.csv、catalog_2.csv…

用法（任意目录）：
  powershell -NoProfile -ExecutionPolicy Bypass -File pkulaw_xls2csv.ps1 `
      -Xls "D:\…\inbox\pkulaw\R1\【北大法宝】目录列表.xls" -OutDir "D:\…\pkulaw\R1"

说明：生成的 CSV 直接喂 pkulaw_ingest.py catalog（含表头两行与版权页脚，脚本自己截断）。
#>
param(
  [Parameter(Mandatory = $true)][string]$Xls,
  [Parameter(Mandatory = $true)][string]$OutDir
)
$ErrorActionPreference = "Stop"
if (-not (Test-Path $Xls)) { throw "找不到文件：$Xls" }
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$excel = New-Object -ComObject Excel.Application
$excel.Visible = $false
$excel.DisplayAlerts = $false
try {
  $wb = $excel.Workbooks.Open((Resolve-Path $Xls).Path, 0, $true)   # ReadOnly
  $i = 0
  foreach ($ws in $wb.Worksheets) {
    $i++
    $used = $ws.UsedRange
    $target = Join-Path (Resolve-Path $OutDir).Path ("catalog_{0}.csv" -f $i)
    Write-Output ("工作表 {0}：'{1}' {2} 行 × {3} 列 → {4}" -f $i, $ws.Name, $used.Rows.Count, $used.Columns.Count, $target)
    $ws.Copy()
    $new = $excel.ActiveWorkbook
    $new.SaveAs($target, 62)   # 62 = xlCSVUTF8（中文不乱码）
    $new.Close($false)
  }
  $wb.Close($false)
} finally {
  $excel.Quit()
  [System.Runtime.InteropServices.Marshal]::ReleaseComObject($excel) | Out-Null
}
