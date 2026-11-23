# Always With You · Releases（测试仓库 / Test repository）

> ⚠️ **这是测试仓库，不是正式版。**
> 这里的安装包都是开发中的测试版本，功能随时会变，可能有 bug，**请不要用于日常使用，也请不要转发**。
> 正式版发布时会另行说明。
>
> ⚠️ **This is a test repository, not an official release.**
> Everything here is a work-in-progress test build. Features change often and there may be bugs.
> **Please don't rely on it or share it yet.** An official release will be announced separately.

---

## 这个仓库是做什么的 / What this is

「一个时刻陪着你的AI」（Always With You）是一个只在你自己电脑上运行的个人记忆 + 陪伴程序（Windows）。
这个仓库**只放安装包和更新说明**，供程序里的「检查更新」使用；源码目前不公开。

*Always With You* is a personal memory + companion app that runs only on your own Windows PC.
This repository **only hosts installers and release notes** for the in-app "Check for updates"; the source code is not public yet.

## 校验 / Verifying a download

每个版本的说明里都写着安装包的 SHA-256。程序内更新会自动核对，对不上就不安装。手动下载时可以在 PowerShell 里核对：

Each release lists the installer's SHA-256. In-app updates check it automatically and refuse to install on mismatch. To check a manual download in PowerShell:

```powershell
Get-FileHash .\AlwaysWithYou-Setup-0.2.0.exe -Algorithm SHA256
```
