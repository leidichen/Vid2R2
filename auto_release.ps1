param (
    [Parameter(Mandatory=$true, HelpMessage="请输入发布的新版本号，例如: 1.2.5")]
    [string]$Version
)

# 确保版本号没有前缀 v
$Version = $Version.TrimStart("v")

Write-Host "=============================" -ForegroundColor Cyan
Write-Host "🔥 准备发布自动构建版本: $Version" -ForegroundColor Cyan
Write-Host "=============================" -ForegroundColor Cyan

# 1. 替换 minimal_uploader.py 中的版本号
Write-Host "正在更新 minimal_uploader.py 界面底部版本号..."
$uploaderFile = "minimal_uploader.py"
(Get-Content $uploaderFile) -replace 'APP_VERSION\s*=\s*".*"', "APP_VERSION = `"$Version`"" | Set-Content $uploaderFile

# 2. 替换 version_info.txt
Write-Host "正在更新 EXE 文件属性版本号..."
$versionFile = "version_info.txt"
$VerTuple = $Version.Replace(".", ", ")
(Get-Content $versionFile) -replace 'filevers=\(\d+, \d+, \d+, 0\)', "filevers=($VerTuple, 0)" | Set-Content $versionFile
(Get-Content $versionFile) -replace 'prodvers=\(\d+, \d+, \d+, 0\)', "prodvers=($VerTuple, 0)" | Set-Content $versionFile
(Get-Content $versionFile) -replace "StringStruct\(u'FileVersion', u'.*'\)", "StringStruct(u'FileVersion', u'$Version')" | Set-Content $versionFile
(Get-Content $versionFile) -replace "StringStruct\(u'ProductVersion', u'.*'\)", "StringStruct(u'ProductVersion', u'$Version')" | Set-Content $versionFile

Write-Host "文件版本替换完成！准备提交 Git 并推送到远程..." -ForegroundColor Green

# 3. 提交、打标签并推送
git add .
git commit -m "Auto release update to v$Version"
git tag "v$Version"
git push origin main
git push origin "v$Version"

Write-Host "=============================" -ForegroundColor Cyan
Write-Host "✅ 发布指令已成功送达 GitHub！" -ForegroundColor Cyan
Write-Host "请前往 GitHub 等待 2~3 分钟即可获得新鲜的 EXE 文件。" -ForegroundColor Cyan
Write-Host "=============================" -ForegroundColor Cyan
Pause
