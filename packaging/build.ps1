# 打包：生成 dist\AlwaysWithYou\AlwaysWithYou.exe，再（如果装了 Inno Setup）生成安装包。
# 用法（在项目根目录）：powershell -ExecutionPolicy Bypass -File packaging\build.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$version = (uv run python -c "import awy; print(awy.__version__)").Trim()
Write-Host "== 版本 $version"

Write-Host "== 运行测试"
uv run pytest -q
if ($LASTEXITCODE -ne 0) { throw "测试没通过，停止打包" }

Write-Host "== 生成图标"
uv run python packaging\make_icon.py packaging\output\app.ico

Write-Host "== PyInstaller 打包"
uv run pyinstaller --noconfirm --clean --distpath dist --workpath build packaging\awy.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 失败" }

$iscc = @(
  "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
  "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
  "C:\Program Files\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) {
  Write-Host "== 没找到 Inno Setup，只生成了 dist\AlwaysWithYou\ 文件夹（可直接运行里面的 AlwaysWithYou.exe）"
  exit 0
}
Write-Host "== Inno Setup 生成安装包"
& $iscc "/DAppVersion=$version" packaging\installer.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup 失败" }
Write-Host "== 完成：packaging\output\AlwaysWithYou-Setup-$version.exe"
