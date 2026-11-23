# 手机端 AwyRead

把手机上的一天带回电脑：读系统健康数据（Health Connect：步数、热量、心率、睡眠）和应用使用时长，
后台每小时读一次，和电脑连同一个 Wi-Fi 时加密传给电脑上的 AlwaysWithYou。设计和安全见
`docs/decisions/README.md` 决定 0014、`docs/SECURITY.md`。

- 不用 Gradle、不用任何第三方库，只用安卓系统自带的接口。最低安卓 14（API 34）。
- 界面是铅笔手绘风格，和电脑端同一套颜色和画法（`Sketch.kt` 对照 `ui/js/sketch.js`）。

## 代码

```
app/src/main/
  AndroidManifest.xml      权限都在这里，每项都有注释说明用途
  kotlin/io/awy/read/
    MainActivity.kt        外框：顶栏（自己的头像和名字、小黑猫「关于」、「+」功能选择）、底栏五个页面、检查更新
    Pages.kt               五个页面：主页（今天概览）/ 配对传输 / 健康 / 应用 / 设置
    Dialogs.kt             铅笔风的对话框和日历（不用系统自带的，风格不搭）
    Ui.kt  Sketch.kt       铅笔手绘的部件和画法、纸面背景、字体、弹出菜单、头像
    Icons.kt               手绘图标（和电脑端 sketch.js 同一套笔画）
    HealthReader.kt        按天显示健康数据（界面用）
    HealthExport.kt        按小时汇总步数和心率、读睡眠（上传用）
    UsageReader.kt         应用使用时长：把系统的前台 / 亮屏事件拼成一段段使用
    Sync.kt                读新数据 → 待上传队列（去重）→ 上传；后台定时任务 SyncJob
    PcLink.kt              找电脑、配对、加密上传（和电脑端 src/awy/phone.py 一一对应）
```

## 打包

需要 Android Studio（带的 JDK、Kotlin、r8）和 SDK（platform 37、build-tools 36），默认在 `D:\android`。

```powershell
powershell -ExecutionPolicy Bypass -File android\build.ps1
```

生成 `android\build\AwyRead.apk`。

**签名钥匙**在 `%USERPROFILE%\.awy\awyread-signing.p12`（不进仓库）。手机上装的版本是用它签的，新版本才能直接覆盖安装、
授权和配对都还在。这个文件丢了就只能先卸载旧版（授权和配对要重来），所以要备份好。没有这个文件时脚本会新建一把并提醒。

**图标**：`packaging\make_icon.py` 从 `assets\icon-source.png` 生成，手机用 `res\mipmap-xxxhdpi\ic_launcher_fg.png`（白底在 `mipmap-anydpi-v26\ic_launcher.xml`）。

**字体**（可选）：把霞鹜文楷屏幕阅读版（LXGW WenKai Screen，SIL OFL 1.1 授权）的 ttf 放成
`app/src/main/assets/wenkai.ttf`、授权文件 `ui/fonts/OFL.txt` 复制成 `app/src/main/assets/wenkai-OFL.txt`，再打包，界面就用它；没有就用系统衬线字体。
**不要放进子文件夹**：Windows 上的 aapt2 会把子文件夹路径写成反斜杠（`fonts\wenkai.ttf`），手机上找不到（0.2.0 就是这样没生效）。
字体文件约 26MB，不进仓库（`.gitignore` 里有）。现在用的是 2026-11-22 从作者的发布页下载的 v1.530：
`https://github.com/lxgw/LxgwWenKai-Screen/releases/download/v1.530/LXGWWenKaiScreen.ttf`，
SHA-256 `abd13364163e3cd84372b333f2fdcee9efb848634668f1c0ce5788dcd059ee61`（和发布页写的一致）。带字体的 APK 约 15MB。

## 装到手机

手机打开 USB 调试，连上电脑：

```powershell
D:\android\sdk\platform-tools\adb.exe install -r android\build\AwyRead.apk
```

也可以把 apk 发到手机上直接点开安装（ColorOS 会提示「未知来源」，自己打的包都会这样）。

装好后在 App 的「准备」里把四项都处理一下：健康数据、应用使用情况、后台读取健康数据、允许后台运行
（ColorOS 还要在「应用详情 → 耗电管理」里允许后台运行和自启动，不然定时读取会被停掉）。

## 和电脑配对

1. 电脑上 AlwaysWithYou →「设置 → 手机」→ 打开「接收手机数据」（第一次 Windows 可能问要不要允许访问网络，选「专用网络」）。
2. 点「配对新手机」，电脑上出现 12 位配对码。
3. 手机 AwyRead →「电脑」里填配对码，点「配对」（第一次会问「附近的设备」权限，要允许）。找不到电脑时把电脑上显示的地址填进「电脑地址」。

## 用模拟器测试

模拟器里 `10.0.2.2` 到不了电脑时，用 adb 转发：`adb -s emulator-5554 reverse tcp:47824 tcp:47824`，
然后在「电脑地址」里填 `127.0.0.1`。
