# 发布一个测试版到公开的发布仓库（只放安装包，源码仓库保持私有）。
# 用法（先 build.ps1 打好安装包，再写好 packaging\release-notes\<版本>.md）：
#   powershell -ExecutionPolicy Bypass -File packaging\release.ps1
# 注意：这会把安装包**公开**发到 GitHub。每次发布前都要先得到用户同意。
# 发布为 Pre-release（测试版），说明里自动附上 SHA-256，程序内更新靠它核对安装包。

$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

$repo = "The-Dark-Iceberg/always-with-you-releases"
$version = (uv run python -c "import awy; print(awy.__version__)").Trim()
$exe = "packaging\output\AlwaysWithYou-Setup-$version.exe"
$notes = "packaging\release-notes\$version.md"

if (-not (Test-Path $exe)) { throw "没找到安装包 $exe，先运行 packaging\build.ps1" }
if (-not (Test-Path $notes)) { throw "没找到更新说明 $notes，先写好再发布" }
if (gh release view "v$version" --repo $repo 2>$null) { throw "v$version 已经发布过了。改版本号（src\awy\__init__.py 和 pyproject.toml）再发。" }

$sha = (Get-FileHash $exe -Algorithm SHA256).Hash.ToLower()
$tmp = New-TemporaryFile
(Get-Content $notes -Raw -Encoding UTF8) + "`n`n---`nSHA256: $sha`n" | Set-Content $tmp -Encoding UTF8

Write-Host "== 发布 v$version 到 $repo（测试版 / Pre-release）"
Write-Host "   安装包：$exe"
Write-Host "   SHA256：$sha"
gh release create "v$version" $exe --repo $repo --prerelease --title "v$version（测试版 / Test build）" --notes-file $tmp
Remove-Item $tmp
Write-Host "== 完成"
