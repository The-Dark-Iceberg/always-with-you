# 打包手机端 AwyRead（不用 Gradle、不用任何第三方库，直接调官方 SDK 里的工具）。
# 签名钥匙放在 %USERPROFILE%\.awy\awyread-signing.p12（不在仓库里，也不在 build 里，删 build 不会丢）。
# 钥匙换了就没法覆盖安装旧版本（只能先卸载，授权要重新给），所以这个文件要保管好。
param(
    [string]$AndroidSdk = 'D:\android\sdk',
    [string]$AndroidStudio = 'D:\android\android studio',
    [string]$Keystore = (Join-Path $env:USERPROFILE '.awy\awyread-signing.p12')
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression, System.IO.Compression.FileSystem   # Windows 自带的 PowerShell 5.1 不会自动加载

function Invoke-Tool([string]$Executable) {
    & $Executable @args
    if ($LASTEXITCODE -ne 0) {
        throw "Build tool failed with exit code ${LASTEXITCODE}: $Executable"
    }
}

# The Windows SDK tools need relative, ASCII paths inside the project.
$source = 'app\src\main'
$build = 'build'
$work = Join-Path $build ('work-' + [guid]::NewGuid().ToString('N'))
$sdkJar = Join-Path $AndroidSdk 'platforms\android-37.0\android.jar'
$tools = Join-Path $AndroidSdk 'build-tools\36.0.0'
$javaBin = Join-Path $AndroidStudio 'jbr\bin'
$kotlinLib = Join-Path $AndroidStudio 'plugins\Kotlin\kotlinc\lib'
$stdlib = Join-Path $kotlinLib 'kotlin-stdlib.jar'
$java = Join-Path $javaBin 'java.exe'
$javac = Join-Path $javaBin 'javac.exe'
$keytool = Join-Path $javaBin 'keytool.exe'
$aapt = Join-Path $tools 'aapt2.exe'
$zipalign = Join-Path $tools 'zipalign.exe'
$d8 = Join-Path $AndroidStudio 'plugins\android\lib\r8.jar'
$signer = Join-Path $tools 'lib\apksigner.jar'

foreach ($file in @($sdkJar, $java, $javac, $keytool, $stdlib, $aapt, $zipalign, $d8, $signer)) {
    if (-not (Test-Path -LiteralPath $file -PathType Leaf)) {
        throw "Missing Android build dependency: $file"
    }
}

$generated = Join-Path $work 'generated'
$classes = Join-Path $work 'classes'
$dex = Join-Path $work 'dex'
Push-Location -LiteralPath $PSScriptRoot

try {
    $null = New-Item -ItemType Directory -Path @($generated, $classes, $dex) -Force
    $resources = Join-Path $work 'res.zip'
    $unaligned = Join-Path $work 'unaligned.apk'
    $aligned = Join-Path $work 'aligned.apk'
    $signed = Join-Path $work 'AwyRead.apk'
    $manifest = Join-Path $source 'AndroidManifest.xml'
    $workDirectory = (Resolve-Path -LiteralPath $work).Path
    $program = Join-Path $workDirectory 'program.jar'

    Invoke-Tool $aapt compile --dir (Join-Path $source 'res') -o $resources
    $linkArgs = @('link', '-I', $sdkJar, '--manifest', $manifest, '--java', $generated,
        '--min-sdk-version', '34', '--target-sdk-version', '35', '-o', $unaligned, $resources)
    $assets = Join-Path $source 'assets'
    if (Test-Path -LiteralPath $assets -PathType Container) {
        $linkArgs += @('-A', $assets)   # 字体等（字体文件不进仓库，见 android/README.md）
    }
    Invoke-Tool $aapt @linkArgs

    $resourceClass = Join-Path $generated 'io\awy\read\R.java'
    Invoke-Tool $javac --release 17 -encoding UTF-8 -d $classes $resourceClass
    $kotlinSources = Get-ChildItem -LiteralPath (Join-Path $source 'kotlin') -Filter '*.kt' -Recurse |
        ForEach-Object { $_.FullName }
    Invoke-Tool $java -cp (Join-Path $kotlinLib '*') org.jetbrains.kotlin.cli.jvm.K2JVMCompiler `
        -no-stdlib -no-reflect -jvm-target 17 -classpath "$sdkJar;$stdlib;$classes" -d $classes @kotlinSources
    [IO.Compression.ZipFile]::CreateFromDirectory((Resolve-Path -LiteralPath $classes).Path, $program)
    Invoke-Tool $java -cp $d8 com.android.tools.r8.D8 --release --min-api 34 --lib $sdkJar `
        --output (Resolve-Path -LiteralPath $dex).Path $program $stdlib

    $archive = [IO.Compression.ZipFile]::Open((Resolve-Path -LiteralPath $unaligned).Path, 'Update')
    try {
        foreach ($dexFile in (Get-ChildItem -LiteralPath $dex -Filter '*.dex')) {
            $null = [IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive, $dexFile.FullName, $dexFile.Name)
        }
    } finally {
        $archive.Dispose()
    }
    Invoke-Tool $zipalign -f -P 16 4 $unaligned $aligned

    if (-not (Test-Path -LiteralPath $Keystore -PathType Leaf)) {
        Write-Warning "没找到签名钥匙 $Keystore，将新建一把。新钥匙签的包不能覆盖安装旧钥匙签的版本。"
        $null = New-Item -ItemType Directory -Path (Split-Path -Parent $Keystore) -Force
        Invoke-Tool $keytool -genkeypair -keystore $Keystore -storetype PKCS12 -storepass android `
            -alias awyread -keyalg RSA -keysize 2048 -validity 10000 -dname 'CN=AwyRead Local Debug'
    }
    $signedPath = Join-Path $workDirectory 'AwyRead.apk'
    Invoke-Tool $java -jar $signer sign --ks $Keystore --ks-key-alias awyread --ks-pass pass:android `
        --v4-signing-enabled false --out $signedPath (Resolve-Path -LiteralPath $aligned).Path
    Invoke-Tool $java -jar $signer verify --verbose $signedPath
    Invoke-Tool $zipalign -c -P 16 4 $signed

    $output = Join-Path $build 'AwyRead.apk'
    Move-Item -LiteralPath $signed -Destination $output -Force
    Write-Output (Join-Path $PSScriptRoot $output)
} finally {
    try {
        if (Test-Path -LiteralPath $work -PathType Container) {
            $resolvedBuild = (Resolve-Path -LiteralPath $build).Path
            $resolvedWork = (Resolve-Path -LiteralPath $work).Path
            if ((Split-Path -Parent $resolvedWork) -eq $resolvedBuild -and (Split-Path -Leaf $resolvedWork) -match '^work-[0-9a-f]{32}$') {
                Remove-Item -LiteralPath $resolvedWork -Recurse -Force
            }
        }
    } finally {
        Pop-Location
    }
}
