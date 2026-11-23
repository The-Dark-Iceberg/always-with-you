# Always With You · User Guide

> Version 0.3.0. Written for people who use the app; no programming knowledge needed.
> 中文版：[使用说明.md](使用说明.md)

---

## 1. What it is

A small "memory + companion" app that runs only on your own computer:

1. **Quietly records**: every few seconds it checks which window is in front (app name and window title only), so it knows what you did on the computer and when you stepped away.
2. **Filters privacy**: before anything is saved, passwords, account names, phone numbers, ID numbers, bank cards and keys are replaced with `[hidden]`. Apps and keywords you list are not recorded at all.
3. **Organizes memories a few times a day**: at set times it writes a one-page summary of your activity and hands it to an AI, which turns it into "memories about you".
4. **Talks with you**: in *Talk with me*, the AI checks your memories first, so it knows who you are, how you've been, and what you're busy with today.

**What it never does**: record audio, take screenshots, log keystrokes, read notifications, use accessibility permissions, or upload raw records anywhere.

---

## 2. Install and uninstall

### Install
1. Double-click `AlwaysWithYou-Setup-0.3.0.exe` (the version may be newer). The installer picks English or Chinese based on your Windows language.
2. Click *Next*. You can choose *Create a desktop shortcut* and *Start with Windows*.
3. No administrator rights are needed; the app installs into your own user folder.

> Your antivirus may warn about an "unknown program": the app isn't code-signed (signing costs money). It is not malware. If blocked, choose "Run anyway" or add it to the trusted list.

### Uninstall
In *Settings → Apps → Installed apps*, find *Always With You* and click *Uninstall*.
You will be **asked whether to delete your memory data too**:
- *No* (default): only the program is removed. Your memories stay, and you can continue after reinstalling.
- *Yes*: memories, chat history, settings and memory archives are deleted as well. **This cannot be undone.**
- If you moved the memory library to another drive, the dialog lists that location too and deletes it on *Yes*.

---

## 3. First use (5 minutes)

After launch, a tray icon appears at the bottom right, and the main window opens.

**The first page is a risk notice**: five points about what is recorded, where data goes, and that the author isn't liable.
- Click **I understand the risks and accept** to start; nothing is recorded before that.
- Click **Quit** to leave; you'll see the page again next time.

**Then a 7-step guide**: welcome & language → my region → what's recorded → who answers → optional features → your memory library → done.
Each page has *Back* / *Next*; *Skip all* at the bottom left skips the rest. Open it again any time from *Settings → Other → Open the guide again*.

> **Important: after changing settings, click Save** (in the guide it's *Save settings*, with an arrow pointing at it). Nothing is saved automatically.
> While there are unsaved changes the Save button keeps glowing; if you try to leave, you'll be asked *Save / Don't save / Stay here*.

You can also set these up later on each page:

1. **Add a DeepSeek API key** (recommended)
   *Settings → Organizing memories → DeepSeek API Key*, then click *Save* at the bottom.
   The key is locked to this computer with Windows' built-in encryption; another computer or Windows account can't read it.
   Without a key, recording still works, but nothing is organized into memories.

2. **Choose *Who answers***
   On the *Who answers* page:
   - **DeepSeek API**: fastest and cheapest; works once the key is saved.
   - **Google Antigravity**: uses your Gemini subscription. The Antigravity CLI must be installed and signed in (see section 6).
   Click *Chat with it* on a card to switch.
   **Speed**: DeepSeek replies in about 3–5 seconds and shows text as it's written. Antigravity takes about 10–40 seconds per reply (that's Google's side, and it varies) and shows the whole answer at once. For speed, use DeepSeek. On the Antigravity card you can change the *Model*: Flash (Low) is fastest for chat; High thinks deeply first and can take minutes.

3. **(Optional) Download the semantic search model**
   *Settings → Other → Semantic search model*, click *Download and enable*, then click again to confirm. About 2.3 GB, downloaded once.
   Files are verified after download; a file that doesn't match is deleted and downloaded again. If the download is interrupted, click again to resume.
   Without it, memory search only matches keywords (searching "exercise" won't find "morning run").

4. **(Optional) Avatar and chat wallpaper**
   Click the circle at the top left to set your avatar. On *Talk with me*, click *Wallpaper* at the top right; the slider controls how faded the picture is.

5. **Language**
   Click the globe icon at the bottom left and choose *简体中文* or *English*. You can also choose in *Settings → Other → Language*, including *Follow system* (the default: Chinese on Chinese Windows, English otherwise).
   Switching changes the window, tray menu and notifications. New memories are written in the chosen language; in chat, the AI replies in the language you write in. Existing memories are not translated.

---

## 4. The pages

| Page | What it does |
|---|---|
| **Today** | Time at the computer, time away, new memories today; a timeline and time per app. *Organize now* (top right) organizes immediately instead of waiting. |
| **Talk with me** | Chat with the AI. It reads your memories before replying (the bubble shows "Read your memories"). Say "**remember: …**" and it leaves a note that becomes a memory at the next organize; say "**you got that wrong, actually …**" and it notes the correction. Long histories show the latest 30 messages; **scroll to the top to load earlier ones**, with date dividers between days. |
| **Memory** | At the top is the *Core profile* (the AI's overall picture of you); below are individual memories. Ticked ones you confirmed yourself; crossed-out ones stopped being true. You can search by meaning, e.g. "how have I been sleeping". The chips above the list **filter by category**; *Export TXT* (top right) exports everything grouped by category. |
| **Write log** | Every change to your memories: who, when, what. **Made a mistake? Click *Undo*.** Nothing is ever really deleted. Grouped by day, filterable by type, and exportable as TXT. |
| **Who answers** | Choose which AI chats and which organizes memories, and see whether each one is installed. |
| **Settings** | Organize times, region, privacy (apps and keywords not to record, how long raw records are kept), language, avatar, model, browser extension, start with Windows, setup guide; click *Save* when done. Further down: *Memory library* (see below) and *About & updates*. |

**Check for updates**: at the bottom of *Settings*, under *About & updates*. The app only goes online when you click it. If there's a new version you'll see the release notes; click *Yes* and the app downloads it, verifies the checksum, then closes, installs and reopens. Memories and settings are kept. Current releases are **test builds**.
You can also update by hand: just run the new installer over the old one. **No need to uninstall first.**

**What else it records (since 0.2.0)**
- **Now playing**: songs playing in the background and videos playing in web pages (title, artist). Note: **videos in incognito windows are recorded too**; Windows can't tell them apart.
- **Recently opened files**: file names only, never contents.
- **Chats**: your chats with the AI are organized into memory too. Your own words count most; the AI's words only record what you talked about, or count when you agree. Each memory shows where it came from (you said / AI's guess / computer activity / talked about together). Turn off *Use chats in organizing* in Settings if you prefer: chats that haven't been organized yet are then no longer sent to the AI either, and if you turn it back on, only chats from that moment on are used — nothing from while it was off. During chats the AI sometimes leaves a "note" for the next organize, with the sentence you just said attached (up to 300 characters). While the switch is on, these notes go to the organizing AI along with the chats; when it's off, notes the AI decides to leave on its own are not accepted, and ones not yet organized are skipped. Only notes left because you said "remember: …" or "you got that wrong …" are not affected and are organized as usual (with your sentence attached so it can be checked).
- **Browser extension** (optional): *Settings → Browser extension → Install browser extension*, confirm, choose a folder, then *Load unpacked* in Edge / Chrome. It records only the https address (parameters removed), title and search terms; never page content; not in incognito. Don't delete the folder afterwards.
- **My region**: in Settings. If your computer's time zone differs from where you live, pick your region here; organize times, "today" and memory times follow it.

**New in 0.3.0**
- **Computer sleep and shutdown**: time when the lid is closed, the computer sleeps or is shut down shows on *Today* as "Computer asleep" or "Shut down" and doesn't count as using the computer. Same for laptops and desktops of any brand — it uses Windows' own records. Brief wake-ups under a minute count as still asleep.
- **My region** names follow the interface language (e.g. "United Kingdom · London"); search by city or country.
- **The AI can go online while chatting**: when it needs fresh information it searches the web and reads pages without asking each time; the bubble shows "Searched the web: …" / "Opened a web page: …". It still can't read or write your files, run commands, or reach local / home-network addresses.
- **"Remember" must come from you**: only when you yourself say "remember…", "don't forget…" or "you got that wrong / actually…" does a note count as confirmed by you. Things the AI decides to note on its own count as ordinary, lower-confidence notes.

**Memory library (Settings → Memory library)**
- **Location**: shows the folder; *Open folder* opens it. At its top level is a guide written for AI agents (MEMORY-README.md, or 记忆库说明.md in Chinese).
- **Change location**: if drive C is full, move it. Pick a folder and the app creates an "AlwaysWithYou" folder inside; it pauses recording, copies and checks every file, deletes the old files only when everything matches, then restarts.
- **Export memory library**: makes a zip in *Documents\AlwaysWithYou 导出*. **It always includes your full chat history**, and you're warned before exporting. In the exported copy, passwords, keys, phone numbers, ID and bank card numbers are replaced with "[hidden]" (rules aren't perfect: names, addresses etc. stay). The zip has **no password**, so keep it safe; it has no API keys or raw window records.
  - On another computer: unzip it and drag the folder to any AI agent (Claude Code, Gemini CLI, Antigravity…). After reading the guide inside it knows you (read-only).
  - With this app installed, import it through *Memory archives* to keep building on it.
- **Memory archives**: shows imported zips and automatic backups. *Import a zip…* adds one; *Use this one* first **backs up your current memories as a zip into the archives**, then switches and restarts. You can always switch back. Two libraries are never merged.

**The sidebar can collapse**: click the small icon at its top right; click again to expand.

**At the bottom left** you see *Recording / Recording paused*, the next organize time, a *Pause recording* button and the language globe.

**Closing the window doesn't quit**: the app keeps recording in the tray. Right-click the tray icon for a small hand-drawn menu (shows recording status and the next organize time): open the main window, pause/resume recording, organize now, or quit. Clicking elsewhere closes it.

**Exported TXT files** go to *Documents\AlwaysWithYou 导出*; the folder opens with the file selected. They contain your memories, so mind your privacy before sharing.

---

## 5. Privacy: what's recorded, what isn't, where data lives

### Recorded
- The **app name** and **window title** of the front window (e.g. "Code.exe · memory.py", "msedge.exe · some page title").
- When you're away (no keyboard/mouse for 5 minutes), the screen is locked, the computer sleeps or is shut down.
- Songs and videos playing, names of recently opened files; with the browser extension, https pages you visit and search terms.
- Your conversations in *Talk with me*.

### Not recorded
- Audio, screenshots, keystrokes, clipboard, file contents, notifications.
- Apps listed in *Settings → Privacy* (by default common password managers, Alipay, etc.), and windows whose title contains your keywords (by default "password", "bank", "Incognito", "InPrivate" and Chinese equivalents). These are only recorded as "Private window" with a duration.
- Passwords, accounts, phone numbers, ID numbers, bank cards, verification codes, emails and keys in titles are replaced with `[hidden]` before anything is written to disk.

> **Honestly**: hiding works by rules, not AI. It recognizes three kinds of things:
> 1. Fixed formats: phone numbers, ID numbers, bank cards, API keys…
> 2. Labeled values: "password: xxx", "account: xxx", "token=xxx"…
> 3. Things that look like passwords: letters and digits mixed with symbols like `@ # ! $` (e.g. `Abc@12345`), or random strings that keep switching between cases and digits (e.g. `x7Kp2Qm9Lw4R`).
>
> It **cannot recognize simple passwords like `zhang123456`**, which look exactly like ordinary names such as `Windows11`. Occasionally it hides harmless things (like YouTube video IDs). The safest approach: add the apps you use for passwords to *Apps not to record*.

### What the AI receives
**Organized activity summaries** (e.g. "14:00–14:45 writing code in VS Code"), never raw window records.
Also, while *Use chats in organizing* is on (the default), your chats with the AI from that period (both sides, long messages shortened) go to the organizing AI. Turn it off in Settings if you prefer. Subscription AIs can read memories, leave notes, search the web and read web pages. They **can't read or write files on your computer or run commands**: every tool request goes through this app, which allows tools by kind — memory, notes, web search and web pages yes, everything else no. Web search terms may include what you asked.

### Where data lives
All on your own computer. By default `C:\Users\<your user name>\AppData\Local\AlwaysWithYou\`; if you moved it, see *Settings → Memory library → Location*.
- `MEMORY-README.md` / `记忆库说明.md`: guide for AI agents
- `memory.db`: memory database
- `raw\`: raw records (deleted after 30 days by default)
- `summaries\`: the summaries used for each organize
- `chats\`: chat history
- `models\`: downloaded model
- `archives\`: memory archives (imported zips, automatic backups)

---

## 6. Chatting through a subscription AI (Google Antigravity example)

1. On *Who answers*, find the Google Antigravity card and click **Install**.
2. A confirmation shows the exact command (`irm https://antigravity.google/cli/install.ps1 | iex`, from Google). Click **Yes**.
3. A PowerShell window opens and installs it. It then starts once; follow the prompts to sign in with your Google account, and close the window when done.
4. Back in the app, the card switches to *Installed* by itself (it checks every 5 seconds). Click *Chat with it*.

> You can also do it by hand: run the command above in PowerShell, then run `agy` to sign in.
> The Claude Code and Codex cards have *Install* too. Codex needs Node.js first (https://nodejs.org); the window tells you if it's missing.

Notes:
- It uses **your own account's subscription quota**. If you share the app, others sign in to their own tools with their own accounts.
- When you open Antigravity yourself for coding, it **can't see** these memories and works as usual.
- The first message is slower (tens of seconds) because it has to start up and read your memories; later ones are faster.

---

## 7. FAQ

**Q: Why is the Memory page empty?**
A: Nothing has been organized yet. Make sure the DeepSeek key is saved, use the computer for a while, then click *Organize now* on *Today* or wait for the next scheduled time.

**Q: The AI remembered something wrong.**
A: Either tell it in chat ("you got that wrong, actually …"), or find the entry in *Write log* and click *Undo*.

**Q: Will I miss an organize if the computer was off or asleep?**
A: No. After startup the app catches up on the missed one (only the most recent). Sleep and shutdown time shows on *Today* and doesn't count as using the computer.

**Q: How do I take my memories to a new computer?**
A: On the old one, *Settings → Memory library → Export zip*. On the new one, install the app, then *Memory archives → Import a zip…* and *Use this one*.

**Q: I don't want to be recorded for a while.**
A: Click *Pause recording* at the bottom left, or right-click the tray icon and choose *Pause recording*.

**Q: Chat replies with an error.**
A: Check on *Who answers* that the AI shows as installed. For DeepSeek, check the key and your balance; for Antigravity, make sure the CLI has been signed in.

**Q: The app won't open or crashes.**
A: Details are in `C:\Users\<your user name>\AppData\Local\AlwaysWithYou\logs\crash.log`. Send that file to whoever helps you maintain the app (or an AI).
