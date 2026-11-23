"""用编造的账号、密码、密钥检验隐私打码（全部是假数据）。

检查方式是严格的：秘密拆成的每一段（3 个字符以上）都不能出现在结果里，
避免「只隐藏了第一段、后面几段漏出来」这种情况被当成通过。
2026-11-20 第一次跑这批数据时漏了 15 项（带标签的密码/账号、银联卡、网址里的账号密码、
私钥正文等），规则补齐后全部通过。改 privacy.py 后必须保持这个文件全部通过。
"""

import pytest

from awy.privacy import mask

SENSITIVE = [
    ("手机号", "联系人 13912345678 张三", "13912345678"),
    ("手机号带空格", "电话 139 1234 5678", "139 1234 5678"),
    ("手机号带+86", "+86-13912345678", "13912345678"),
    ("身份证", "身份证号 11010519491231002X", "11010519491231002X"),
    ("银联卡分段", "卡号 6222 0212 3456 7890 128", "6222 0212 3456 7890 128"),
    ("银联卡连写", "6217000010012345678", "6217000010012345678"),
    ("卡号标签+分段", "卡号 4000 1234 5678 9010", "4000 1234 5678 9010"),
    ("邮箱", "登录 fake.user@example.com 成功", "fake.user@example.com"),
    ("验证码", "【某宝】您的验证码是 837261，请勿泄露", "837261"),
    ("英文验证码", "Your code: 4F7K9Q", "4F7K9Q"),
    ("密码中文", "密码：Abc@12345", "Abc@12345"),
    ("密码英文", "password=hunter2!", "hunter2!"),
    ("pwd", "pwd: Qwerty#2026", "Qwerty#2026"),
    ("口令", "登录口令 Mima_8899", "Mima_8899"),
    ("账号", "账号：fake_account01", "fake_account01"),
    ("用户名", "用户名: zhangsan_test", "zhangsan_test"),
    ("QQ号", "QQ：123456789", "123456789"),
    ("QQ是", "我的QQ是 987654321", "987654321"),
    ("微信号", "微信号 wxid_abc123xyz", "wxid_abc123xyz"),
    ("电话标签分段", "电话：021-6543 2100", "6543 2100"),
    ("混合一句话", "QQ 987654321，密码 Pass_word99，手机 15800001111", "987654321 Pass_word99 15800001111"),
    ("OpenAI/DeepSeek 密钥", "sk-1234567890abcdefABCDEF1234", "sk-1234567890abcdefABCDEF1234"),
    ("Anthropic 密钥", "sk-ant-api03-AbCdEfGhIjKlMnOpQrSt", "sk-ant-api03-AbCdEfGhIjKlMnOpQrSt"),
    ("GitHub 令牌", "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"),
    ("AWS", "AKIAABCDEFGHIJKLMNOP", "AKIAABCDEFGHIJKLMNOP"),
    ("Google 密钥", "AIzaSyA-1234567890abcdefghijklmnopqrs", "AIzaSyA-1234567890abcdefghijklmnopqrs"),
    ("JWT", "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
     "eyJhbGciOiJIUzI1NiJ9 dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"),
    ("Bearer", "Authorization: Bearer abcDEF123456ghiJKL789", "abcDEF123456ghiJKL789"),
    ("token=", "token=9f8e7d6c5b4a3210fedcba", "9f8e7d6c5b4a3210fedcba"),
    ("api_key", "api_key: my-secret-key-123456", "my-secret-key-123456"),
    ("网址带账号密码", "https://admin:P@ssw0rd@192.168.1.1/login", "P@ssw0rd admin"),
    ("网址参数", "https://bank.example.com/cb?ticket=SECRET123&uid=42", "SECRET123"),
    ("私钥整段", "-----BEGIN RSA PRIVATE KEY----- MIIEowIBAAKCAQEA0fakefakefake -----END RSA PRIVATE KEY-----",
     "MIIEowIBAAKCAQEA0fakefakefake"),
    ("私钥没写完", "粘贴：-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASC\nfakefakefake",
     "MIIEvQIBADANBgkqhkiG9w0BAQEFAASC fakefakefake"),
    ("护照", "护照号 E12345678", "E12345678"),
    # ---- 没有任何标签的密码和密钥（靠「像密码的字符串」规则）----
    ("无标签密码", "笔记.txt - Abc@12345 - 记事本", "Abc@12345"),
    ("无标签密码带感叹号", "P@ssw0rd! 别忘了", "P@ssw0rd!"),
    ("8位符号密码", "Zx#9vQ!2", "Zx#9vQ!2"),
    ("文件名就是密码", "Abc@12345.txt - 记事本", "Abc@12345"),
    ("来回切换的短串", "临时 aB3dE5fG9h", "aB3dE5fG9h"),
    ("随机短串", "x7Kp2Qm9Lw4R 备用", "x7Kp2Qm9Lw4R"),
    ("十六进制密钥", "9f8e7d6c5b4a3210fedcba9876543210", "9f8e7d6c5b4a3210fedcba9876543210"),
    ("随机长密钥", "复制 Qm9Xz2Lp7Rt4Vb8Nc3Kd6Wf1Hs5", "Qm9Xz2Lp7Rt4Vb8Nc3Kd6Wf1Hs5"),
    ("重置链接里的令牌", "https://example.com/reset/aB3dE5fGh7Jk9Lm2 - Edge", "aB3dE5fGh7Jk9Lm2"),
    ("句末的密码", "新密码是Abc@12345.", "Abc@12345"),
]

ORDINARY = [
    "memory.py - always-with-you - Visual Studio Code",
    "哔哩哔哩 (゜-゜)つロ 干杯~-bilibili",
    "第3章 线性代数 - 期末复习.pdf",
    "订单 123456789012345678 已发货",
    "2026年11月20日 星期五",
    "设置 - 修改密码 - 帮助中心",
    "Python 3.13.14 文档",
    "版本 v1.2.3 更新说明",
    "下载进度 1594 / 2162 MB",
    "QQ音乐 - 晴天",
    "微信",
    "修改密码帮助中心",
    "用户名登录页面",
    "账号设置 - Google Chrome",
    "Token 用量统计",
    # ---- 容易被「像密码」规则误伤的正常名字 ----
    "BV1tDs66oEQa 我做了一个陪伴AI - 哔哩哔哩",
    "https://www.bilibili.com/video/BV1tDs66oEQa/",
    "IMG_20241120_153045.jpg - 照片",
    "Windows11Pro 激活",
    "RTX5060Ti 驱动下载",
    "GPT4oMini 价格",
    "Report_2024.docx - Word",
    r"D:\Users\Iceberg\Desktop\agent-knowledge-base",
    "npm install react@18.3.1",
    "utf8mb4_general_ci 排序规则",
    "localhost:8080 - Edge",
    "192.168.1.1 路由器",
    "Python3.13 安装",
    "Qwen2.5-7B-Instruct 模型",
    "bge-m3 下载",
    "ISO-8859-1 编码",
    "AlwaysWithYou-Setup-0.1.0.exe",
    "always-with-you commit 847745b",
    "第2026-11-20期 周报.md",
    "HelloWorld2024.java",
]


# 已知做不到的（写在这里提醒后来的人，不当成测试失败）：
# 「zhang123456」「password1」这种只有一处字母→数字切换的弱密码，和「Windows11」「python313」
# 长得一样，规则分不出来。防这类只能靠黑名单（处理密码的软件整条不记）。


@pytest.mark.parametrize("name,text,secret", SENSITIVE, ids=[s[0] for s in SENSITIVE])
def test_fake_secret_is_hidden(name, text, secret):
    out = mask(text)
    leaked = [p for p in secret.split() if len(p) >= 3 and p in out]
    assert not leaked, f"{name} 漏出了 {leaked}：{out}"


@pytest.mark.parametrize("text", ORDINARY)
def test_ordinary_text_untouched(text):
    assert mask(text) == text


def test_password_file_name_keeps_extension():
    assert mask("Zx#9vQ!2.txt - 记事本") == "[已隐藏].txt - 记事本"
    assert "Abc@12345" not in mask("Abc@12345.txt - 记事本")      # 这个形状像邮箱，被邮箱规则整段隐藏


def test_collector_masks_fake_secret_in_window_title():
    """走一遍真正的采集流程：窗口标题里带假密码，写进原始记录前就被隐藏。"""
    from awy.collect_pc import PcCollector
    from awy.config import Settings
    got = []
    s = Settings(blocked_apps=[], blocked_keywords=[])
    c = PcCollector(lambda: s, probe=lambda: ("notepad.exe", "笔记.txt - 账号 fake_user01 密码 Abc@12345"),
                    idle=lambda: 0, sink=got.append)
    c.tick()
    assert "fake_user01" not in got[0]["title"] and "Abc@12345" not in got[0]["title"]
