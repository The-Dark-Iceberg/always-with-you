"""隐私过滤：在任何数据落盘之前执行。全部是固定规则，没有 AI 参与。

两道关：
1. 黑名单（is_blocked）：命中的软件或窗口整条不记内容，只记成「隐私窗口」，
   这样统计时长时还知道这段时间被占用了，但不知道在干什么。
2. 打码（mask）：把文本里的手机号、身份证号、银行卡号、验证码、邮箱、
   各类密钥、网址参数、「密码：xxx」这类带标签的值，以及长得像密码的随机串换成占位符。

注意：规则不可能抓住所有隐私（比如聊天对象的名字），所以「只把摘要交给 AI」
和「黑名单优先」才是主要防线，打码是补充。详见 docs/SECURITY.md。
"""

from __future__ import annotations

import re

MASK = "[已隐藏]"

# ---- 各类模式 ----------------------------------------------------------------

# 网址：保留协议+域名+路径，去掉 ? 和 # 之后的参数（参数里常带登录令牌）
_URL = re.compile(r"(https?://[^\s?#]+)[?#][^\s]*", re.IGNORECASE)

# 网址里夹带的账号密码：https://用户名:密码@主机
# 贪婪匹配到主机名前「最后一个 @」，这样密码里本身带 @ 也能整段隐藏
_URL_USERINFO = re.compile(r"([a-z][a-z0-9+.\-]*://)[^\s/]*@", re.IGNORECASE)

# 「标签 + 值」：密码：xxx、账号=xxx、QQ 123、token: xxx ……
# 值必须含字母或数字，且至少 3 个字符，避免误伤「修改密码帮助中心」「QQ音乐」这类正常文字。
_LABELS_ZH = r"(?:密码|口令|密钥|秘钥|账号|帐号|账户|帐户|用户名|登录名|手机号|电话|护照号?|微信号?|QQ号?|身份证号?|卡号)"
_LABELS_EN = r"(?<![A-Za-z])(?:password|passwd|pwd|passcode|pin|token|access[_-]?token|refresh[_-]?token|secret|" \
             r"client[_-]?secret|api[_-]?key|access[_-]?key|private[_-]?key|username|user|login|account|qq|wechat|passport)(?![A-Za-z])"
_LABELED = re.compile(
    r"(" + _LABELS_ZH + r"|" + _LABELS_EN + r")([ \t]*(?:[:：=＝]|是|为|is)?[ \t]*)"
    r"(?=[^\s，。,;；、)）\]】\"'“”]*[A-Za-z0-9])"
    r"((?:\d{2,6}(?:[ \-]\d{2,6})+)|[^\s，。,;；、)）\]】\"'“”]{3,})",   # 分段数字（如卡号、电话）整串隐藏
    re.IGNORECASE,
)

# HTTP 认证头：Bearer xxx / Basic xxx
_AUTH = re.compile(r"\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=\-]{8,}", re.IGNORECASE)

# 常见密钥格式
_SECRET_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}\b"),            # OpenAI / DeepSeek 等
    re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{16,}\b"),        # Anthropic
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),        # GitHub
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),                  # AWS
    re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}\b"),           # Google
    re.compile(r"\bxox[abpr]-[A-Za-z0-9\-]{10,}\b"),      # Slack
    re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\b"),  # JWT
    # 整段私钥：从 BEGIN 一直到 END（没有 END 就到文本末尾），不能只隐藏开头那行
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)"),
]

_EMAIL = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")

# 中国大陆手机号（可带 +86，可用空格或短横分成 3-4-4）
_PHONE = re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d(?:[ \-]?\d{4}){2}(?!\d)")

# 银联卡（62 开头 16~19 位）：不少银联卡号不满足 Luhn 校验，所以按开头单独识别
_UNIONPAY = re.compile(r"(?<!\d)6[ \-]?2(?:[ \-]?\d){14,17}(?!\d)")

# 18 位身份证（最后一位可为 X），需通过校验码才打码，减少误伤
_IDCARD = re.compile(r"(?<![0-9A-Za-z])\d{17}[\dXx](?![0-9A-Za-z])")

# 银行卡：13-19 位数字（可有空格或短横），需通过 Luhn 校验
_CARD = re.compile(r"(?<!\d)(?:\d[ \-]?){12,18}\d(?!\d)")

# 验证码：关键词附近的 4-8 位数字/字母
_CODE = re.compile(
    r"((?:验证码|校验码|动态码|动态密码|确认码|code|otp)[^0-9A-Za-z]{0,6})([0-9A-Za-z]{4,8})",
    re.IGNORECASE,
)


# ---- 「像密码的字符串」：没有标签、没有固定格式时的兜底 ------------------------------
# 思路：人起的名字（Windows11Pro、IMG_20241120、Report_2024）字母和数字成块出现，
# 随手敲的密码和机器生成的密钥则「大小写、数字、符号来回切换」或者夹着 @#!$ 这类符号。
# 只看 8 个字符以上、同时有字母和数字的连续英文串（中文、空格、/ \ : 引号括号都会把它切开）。
# 代价：少数正常名字也会被隐藏（比如 YouTube 视频编号、「Q&A_2024」）；B 站 BV 号、
# 版本号、文件扩展名做了放行。认不出「zhang123456」这种只有一处字母数字切换的弱密码。
_CANDIDATE = re.compile(r"[0-9A-Za-z!@#$%^&*+=?~_.\-]{8,}")
_STRONG_SYMBOLS = set("!@#$%^&*+=?~")
_ALLOW = [
    re.compile(r"BV1[0-9A-Za-z]{9}"),                                   # B 站视频编号
    re.compile(r"v?\d+(?:\.\d+)+(?:[-+._][0-9A-Za-z]+)*", re.I),        # 版本号 1.2.3-beta2
    re.compile(r"[a-z][a-z0-9.\-]*@v?\d+(?:\.\d+)+"),                     # 软件包 react@18.3.1（必须带点）
]
_FILE_EXT = re.compile(r"^(.*[0-9A-Za-z!@#$%^&*+=?~])\.([A-Za-z][A-Za-z0-9]{0,4})$")


def _switches(s: str) -> int:
    """数一个串里「字母↔数字」「小写→大写」的切换次数（大写→小写是单词开头，不算）。"""
    kinds = ["D" if c.isdigit() else ("U" if c.isupper() else "L") for c in s if c.isalnum()]
    return sum(1 for a, b in zip(kinds, kinds[1:]) if a != b and not (a == "U" and b == "L"))


def _looks_secret(s: str) -> bool:
    if len(s) < 8 or len(s) > 128 or any(p.fullmatch(s) for p in _ALLOW):
        return False
    alnum = [c for c in s if c.isalnum()]
    if not any(c.isalpha() for c in alnum) or not any(c.isdigit() for c in alnum):
        return False
    if len(s) <= 64 and any(c in _STRONG_SYMBOLS for c in s):     # Abc@12345、Qwerty#2026
        return True
    n, sw = len(alnum), _switches(s)
    if n >= 16:                                                    # 长串：机器生成的密钥、哈希
        return sw >= max(5, -(-n * 3 // 10))
    return n >= 8 and sw >= 4                                      # 短串：aB3dE5fG 这种来回切换


def _mask_random(text: str) -> str:
    def repl(m: re.Match[str]) -> str:
        run = m.group(0)
        tail = len(run) - len(run.rstrip("."))                   # 句末的点不算
        core, end = run[: len(run) - tail], run[len(run) - tail:]
        f = _FILE_EXT.match(core)                                  # 文件名：只看扩展名前面那段，扩展名保留
        if f and _looks_secret(f.group(1)):
            return MASK + "." + f.group(2) + end
        if _looks_secret(core):
            return MASK + end
        return run
    return _CANDIDATE.sub(repl, text)


def _idcard_ok(s: str) -> bool:
    weights = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
    checks = "10X98765432"
    try:
        total = sum(int(c) * w for c, w in zip(s[:17], weights))
    except ValueError:
        return False
    return checks[total % 11] == s[17].upper()


def _luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def mask(text: str) -> str:
    """把文本里的敏感信息换成 [已隐藏]。对普通文本不做任何改动。"""
    if not text:
        return text
    out = _URL_USERINFO.sub(r"\1" + MASK + "@", text)
    out = _URL.sub(r"\1", out)
    for pat in _SECRET_PATTERNS:
        out = pat.sub(MASK, out)
    out = _AUTH.sub(lambda m: m.group(1) + " " + MASK, out)
    out = _EMAIL.sub(MASK, out)
    out = _CODE.sub(lambda m: m.group(1) + MASK, out)
    out = _IDCARD.sub(lambda m: MASK if _idcard_ok(m.group(0)) else m.group(0), out)
    out = _UNIONPAY.sub(MASK, out)
    out = _PHONE.sub(MASK, out)

    def _card(m: re.Match[str]) -> str:
        digits = re.sub(r"[ \-]", "", m.group(0))
        return MASK if 13 <= len(digits) <= 19 and _luhn_ok(digits) else m.group(0)

    out = _CARD.sub(_card, out)
    # 「标签 + 值」必须放在最后：它只认紧跟标签的第一段，如果先执行，会把「卡号 6222 0212 …」
    # 只隐藏第一段，导致后面几段漏出来（2026-11-20 用假数据测出来的问题）。
    out = _LABELED.sub(lambda m: m.group(1) + m.group(2) + MASK if MASK not in m.group(3) else m.group(0), out)
    # 最后兜底：没有标签、没有固定格式，但长得像密码或密钥的英文串
    return _mask_random(out)


def is_blocked(app: str, title: str, blocked_apps: list[str], blocked_keywords: list[str]) -> bool:
    """命中黑名单返回 True。软件名按完整进程名比较，关键词在标题里找（都不分大小写）。"""
    app_l = (app or "").lower()
    if any(app_l == b.lower() for b in blocked_apps if b):
        return True
    title_l = (title or "").lower()
    return any(k.lower() in title_l for k in blocked_keywords if k)
