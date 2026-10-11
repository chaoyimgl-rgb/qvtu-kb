# run_kb.ps1 —— 一键导出课表（单文件版，支持两种登录方式）
# 用法: 右键"使用 PowerShell 运行"，或 pwsh -File run_kb.ps1
$dir = $PSScriptRoot

Write-Host "登录方式："
Write-Host "  [1] 教务账号密码（直连，推荐）"
Write-Host "  [2] 超星账号密码（hall 免登链路，可拿直达链接）"
$choice = Read-Host "请选择 (默认 1)"

function Read-Secret($prompt) {
    $sec = Read-Host $prompt -AsSecureString
    [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))
}

if ($choice -eq "2") {
    $env:QVTU_USER = Read-Host "超星账号(手机号)"
    $env:QVTU_PASS = Read-Secret "超星密码"
    $mode = "hall"
} else {
    $env:QVTU_JW_USER = Read-Host "教务账号(学号)"
    $env:QVTU_JW_PASS = Read-Secret "教务密码"
    $mode = "jw"
}

try {
    python (Join-Path $dir "qvtu_kb.py") --mode $mode
} finally {
    Remove-Item Env:QVTU_USER, Env:QVTU_PASS, Env:QVTU_JW_USER, Env:QVTU_JW_PASS -ErrorAction SilentlyContinue
}

Write-Host "`n输出目录: $dir（课表_*.csv / .ics / _wakeup*.csv / 课表链接.txt）" -ForegroundColor Green
Read-Host "按回车退出" | Out-Null
