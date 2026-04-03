<#
.SYNOPSIS
    Vid2R2 打包脚本
.DESCRIPTION
    自动清理旧文件，并使用 PyInstaller 根据 .spec 文件打包 EXE。
#>

$ErrorActionPreference = "Stop"
$appName = "Vid2R2"
$scriptPath = $PSScriptRoot
$specFile = Join-Path $scriptPath "$appName.spec"

Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "       Vid2R2 Build Script" -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan

# 1. 清理旧的构建文件
Write-Host "[1/3] Cleaning old build files..." -ForegroundColor Cyan
if (Test-Path (Join-Path $scriptPath "build")) { Remove-Item (Join-Path $scriptPath "build") -Recurse -Force }
# Note: Keep dist folder but specify we'll overwrite the target
Write-Host "Cleaned build folders." -ForegroundColor Gray

# 2. 运行 PyInstaller
Write-Host "`n[2/3] Running PyInstaller..." -ForegroundColor Cyan
if (-not (Test-Path $specFile)) {
    Write-Error "Error: $appName.spec not found in $scriptPath"
    exit 1
}

# 使用当前虚拟环境中的 PyInstaller
$pyinstaller = "python -m PyInstaller"
Invoke-Expression "$pyinstaller $specFile --clean --noconfirm"

if ($LASTEXITCODE -ne 0) {
    Write-Error "PyInstaller failed with exit code $LASTEXITCODE"
    exit 1
}

Write-Host "==========================================" -ForegroundColor Cyan
