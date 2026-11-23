; Inno Setup 安装脚本：生成 AlwaysWithYou-Setup-<版本>.exe
; 由 packaging/build.ps1 调用：ISCC.exe /DAppVersion=0.1.0 installer.iss
; 特点：
;  - 装到 %LOCALAPPDATA%\Programs\AlwaysWithYou，不需要管理员权限
;  - 可选：桌面快捷方式、开机自启
;  - 卸载：先关掉正在运行的程序，删除开机自启项；询问是否同时删除记忆数据（默认保留）
;  - 中英双语：按 Windows 界面语言自动选，选不中时让用户挑；所有给人看的文字在 [CustomMessages]
;  - 如果 packaging\model\bge-m3\ 里放了模型文件，会一起装进去，否则用户可在程序里下载

#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#define AppExe "AlwaysWithYou.exe"

[Setup]
AppId={{E0090876-DC5D-4D23-862D-90E2AA34FF45}
AppName={cm:AppName}
AppVersion={#AppVersion}
AppPublisher=Always With You
DefaultDirName={localappdata}\Programs\AlwaysWithYou
DefaultGroupName={cm:AppName}
PrivilegesRequired=lowest
OutputDir=output
OutputBaseFilename=AlwaysWithYou-Setup-{#AppVersion}
SetupIconFile=output\app.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={cm:AppName}
ShowLanguageDialog=auto
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
CloseApplications=yes

[Languages]
Name: "chs"; MessagesFile: "ChineseSimplified.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
chs.AppName=一个时刻陪着你的AI
en.AppName=Always With You
chs.ExtraOptions=附加选项：
en.ExtraOptions=Additional options:
chs.DesktopIcon=创建桌面快捷方式
en.DesktopIcon=Create a desktop shortcut
chs.AutoStart=开机时自动启动（只在托盘）
en.AutoStart=Start with Windows (tray only)
chs.Manual=使用说明
en.Manual=User guide
chs.UninstallApp=卸载 %1
en.UninstallApp=Uninstall %1
chs.LaunchNow=立即启动
en.LaunchNow=Launch now
chs.DeleteData=是否同时删除你的记忆数据？%n%n位置：%1%n（包括记忆库、原始记录、设置、模型和记忆存档。删除后无法恢复。选「否」则保留，重新安装后可继续使用。）
en.DeleteData=Also delete your memory data?%n%nLocation: %1%n(This includes the memory database, raw records, settings, the model and memory archives. It cannot be recovered. Choose "No" to keep it so you can continue after reinstalling.)

[Tasks]
Name: "desktopicon"; Description: "{cm:DesktopIcon}"; GroupDescription: "{cm:ExtraOptions}"
Name: "autostart"; Description: "{cm:AutoStart}"; GroupDescription: "{cm:ExtraOptions}"

[Files]
Source: "..\dist\AlwaysWithYou\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\docs\使用说明.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\docs\USER_GUIDE.md"; DestDir: "{app}"; Flags: ignoreversion
#if DirExists(AddBackslash(SourcePath) + "model\bge-m3")
Source: "model\bge-m3\*"; DestDir: "{localappdata}\AlwaysWithYou\models\bge-m3"; Flags: ignoreversion onlyifdoesntexist
#endif

[Icons]
Name: "{group}\{cm:AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\{cm:Manual}"; Filename: "{win}\notepad.exe"; Parameters: """{app}\使用说明.md"""; Languages: chs
Name: "{group}\{cm:Manual}"; Filename: "{win}\notepad.exe"; Parameters: """{app}\USER_GUIDE.md"""; Languages: en
Name: "{group}\{cm:UninstallApp,{cm:AppName}}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\{cm:AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "AlwaysWithYou"; ValueData: """{app}\{#AppExe}"" --minimized"; Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchNow}"; Flags: nowait postinstall skipifsilent
; 程序里「检查更新」是静默安装（/SILENT），上面那行会被跳过；这一行负责装完把程序重新打开
Filename: "{app}\{#AppExe}"; Flags: nowait; Check: WizardSilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM {#AppExe}"; Flags: runhidden; RunOnceId: "KillApp"

[Code]
{ 记忆库被用户搬到别处时（决定 0012），程序在默认目录留一个 location.txt（带 BOM 的 UTF-8，只有一行路径）。
  只认最后一段叫 AlwaysWithYou、并且里面确实有 memory.db 或 config.json 的文件夹，免得误删别的东西。 }
function MovedDataDir(): string;
var
  Lines: TArrayOfString;
  F, D: string;
begin
  Result := '';
  F := ExpandConstant('{localappdata}\AlwaysWithYou\location.txt');
  if FileExists(F) and LoadStringsFromFile(F, Lines) and (GetArrayLength(Lines) > 0) then
  begin
    D := Trim(Lines[0]);
    if (D <> '') and DirExists(D) and (CompareText(ExtractFileName(RemoveBackslashUnlessRoot(D)), 'AlwaysWithYou') = 0)
       and (FileExists(AddBackslash(D) + 'memory.db') or FileExists(AddBackslash(D) + 'config.json')) then
      Result := D;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir, CompanionDir, MovedDir, Shown: string;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    RegDeleteValue(HKEY_CURRENT_USER, 'Software\Microsoft\Windows\CurrentVersion\Run', 'AlwaysWithYou');
    DataDir := ExpandConstant('{localappdata}\AlwaysWithYou');
    CompanionDir := ExpandConstant('{%USERPROFILE}\AlwaysWithYou-Companion');
    MovedDir := MovedDataDir();
    Shown := DataDir;
    if MovedDir <> '' then
      Shown := MovedDir + #13#10 + DataDir;
    { 删除数据必须由用户在弹窗里亲手点「是」。
      静默卸载（/SILENT、/VERYSILENT，包括升级覆盖时）一律保留数据，连弹窗都不出。
      2026-11-20 教训：原先用的普通 MsgBox 在 /VERYSILENT /SUPPRESSMSGBOXES 下被当成「是」，删掉了用户数据。
      现在用 SuppressibleMsgBox 并显式给出静默时的默认答案 IDNO，双重保险。 }
    if (DirExists(DataDir) or (MovedDir <> '')) and (not UninstallSilent()) then
    begin
      if SuppressibleMsgBox(FmtMessage(CustomMessage('DeleteData'), [Shown]),
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2, IDNO) = IDYES then
      begin
        if MovedDir <> '' then
          DelTree(MovedDir, True, True, True);
        DelTree(DataDir, True, True, True);
        DelTree(CompanionDir, True, True, True);
      end;
    end;
  end;
end;
