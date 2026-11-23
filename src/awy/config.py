"""程序设置。保存在数据目录的 config.json 里（不在代码仓库里）。

设计原则：
- 所有字段都有默认值，旧版本的配置文件缺字段也能正常读。
- 密钥字段只存 DPAPI 加密后的内容（见 vault.py）。
- MCP 的两把钥匙（读取 / 整理）首次运行时随机生成。
"""

from __future__ import annotations

import json
import secrets as _rand
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from awy import paths

TERMS_VERSION = "2026-11-22"   # 风险说明的版本（2026-11-22 加了手机数据那条）（界面文字在 ui/js/app.js 的 TERMS）

DEFAULT_BLOCKED_APPS = [
    # 密码管理器 / 银行 / 支付类桌面程序（按进程名，大小写不敏感）
    "KeePass.exe", "KeePassXC.exe", "1Password.exe", "Bitwarden.exe",
    "AliPay.exe", "Alipay.exe", "UnionPay.exe",
]
DEFAULT_BLOCKED_KEYWORDS = [
    # 窗口标题里出现这些词时，整条记录只记成「隐私窗口」
    "密码", "password", "网银", "银行", "支付宝", "alipay", "微信支付", "paypal",
    "银联", "证券", "私密浏览", "InPrivate", "无痕", "Incognito",
]


@dataclass
class Settings:
    # 采集
    collect_enabled: bool = True
    poll_seconds: int = 5
    idle_threshold_seconds: int = 300
    blocked_apps: list[str] = field(default_factory=lambda: list(DEFAULT_BLOCKED_APPS))
    blocked_keywords: list[str] = field(default_factory=lambda: list(DEFAULT_BLOCKED_KEYWORDS))
    raw_retention_days: int = 30  # 原始记录保留天数；摘要和记忆永久保留

    # 整理
    organize_times: list[str] = field(default_factory=lambda: ["10:00", "14:00", "19:00", "23:30"])
    organizer: str = "deepseek"  # deepseek | claude_cli | none
    deepseek_api_key_protected: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    organizer_max_steps: int = 60

    # 我所在的地区（时区）："" = 跟随电脑；或 IANA 名如 Europe/London。见 clock.py、决定 0011
    timezone: str = ""

    # 界面语言："" 表示跟随 Windows 系统语言；zh | en（见 i18n.py）
    language: str = ""

    # 聊天（「陪我聊聊」）由谁回答：deepseek | antigravity | claude
    chat_brain: str = "deepseek"
    chat_history_turns: int = 20  # 用 DeepSeek 时带上最近多少轮对话
    chat_in_memory: bool = True   # 聊天内容（双方）参与整理，见决定 0011
    chat_in_memory_since: str = ""   # 最近一次打开上面这个开关的时间：关着那段时间的聊天不补进整理
    # 「检查更新」去哪个公开仓库看（只放安装包的发布仓库；源码仓库是私有的）
    update_repo: str = "The-Dark-Iceberg/always-with-you-releases"

    # Antigravity 聊天用哪个模型档位。Flash Low 最快；High 会先深度思考，实测一句话要几分钟（2026-11-20）
    antigravity_model: str = "gemini-3.8-flash-low"

    # MCP 服务（只监听本机）
    read_port: int = 47821
    browser_port: int = 47823   # 浏览器扩展发数据的端口（改了要同步改 browser-extension 里的地址）
    write_port: int = 47822
    read_token: str = ""
    write_token: str = ""

    # 上下文预算（字符数，中文约等于 token 数）
    context_budget_static: int = 1500
    context_budget_recent: int = 2000
    context_budget_today: int = 1500

    # 向量模型
    embedding_enabled: bool = True

    # 手机（决定 0014）：接收手机端 AwyRead 的数据。要监听局域网，所以默认关着
    phone_enabled: bool = False
    phone_port: int = 47824     # TCP（接收）和 UDP（让手机找到电脑）都用这个端口；手机端写死了 47824
    phone_pc_id: str = ""       # 这台电脑的编号（首次运行随机生成），手机靠它认出配对过的电脑
    phone_devices: list[dict] = field(default_factory=list)   # [{id, name, key（DPAPI 加密）, paired_at}]

    # 其他
    autostart: bool = False

    # 第一次打开（决定 0012）：先确认风险，再看引导。接受之前不记录任何东西。
    accepted_terms: str = ""    # 接受过的风险说明版本（TERMS_VERSION）；说明有实质改动时改版本号，会重新问一次
    onboarded: bool = False     # 引导看完或跳过了

    def ensure_tokens(self) -> bool:
        changed = False
        if not self.read_token:
            self.read_token = _rand.token_urlsafe(32)
            changed = True
        if not self.write_token:
            self.write_token = _rand.token_urlsafe(32)
            changed = True
        if not self.phone_pc_id:
            self.phone_pc_id = _rand.token_hex(8)
            changed = True
        return changed


RETENTION_MIN, RETENTION_MAX = 1, 3650   # 原始记录保留天数的范围（设置页写的也是这个）


def is_valid_retention(v: object) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and RETENTION_MIN <= v <= RETENTION_MAX


def clean_retention(v: object) -> int:
    """保留天数整理成 1~3650 的整数：不是整数就用默认 30，超出范围就取边界。
    0 或负数如果不拦，会把今天的原始记录也删掉。"""
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v:   # v != v：NaN
        return Settings.raw_retention_days
    return int(min(max(v, RETENTION_MIN), RETENTION_MAX))


def load(path: Path | None = None) -> Settings:
    path = path or paths.config_file()
    s = Settings()
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        known = {f.name for f in fields(Settings)}
        for k, v in data.items():
            if k in known:
                setattr(s, k, v)
        if "onboarded" not in data:   # 从旧版本升级上来的老用户：不用再看引导（风险确认还是要看一次）
            s.onboarded = True
        s.raw_retention_days = clean_retention(s.raw_retention_days)   # 手改过的配置文件里可能是乱填的
    if s.ensure_tokens() or not path.exists():
        save(s, path)
    return s


def save(s: Settings, path: Path | None = None) -> None:
    path = path or paths.config_file()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(s), ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
