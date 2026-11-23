from awy.privacy import MASK, is_blocked, mask


def test_masks_sensitive_items():
    assert MASK in mask("联系我 13812345678 谢谢")
    assert MASK in mask("+86 13812345678")
    assert MASK in mask("邮箱 someone@example.com")
    assert MASK in mask("key sk-abcdefghijklmnop1234567890")
    assert MASK in mask("token ghp_abcdefghijklmnopqrstuvwxyz0123")
    assert mask("【某银行】验证码：482913，5分钟内有效") == "【某银行】验证码：" + MASK + "，5分钟内有效"
    assert MASK in mask("身份证 11010519491231002X")      # 校验位正确
    assert MASK in mask("卡号 4111 1111 1111 1111")         # Luhn 校验通过


def test_url_query_removed():
    assert mask("https://a.com/path?token=abc&x=1 页面") == "https://a.com/path 页面"


def test_ordinary_text_untouched():
    for t in ["memory.py - always-with-you - Visual Studio Code", "2026年11月20日 第3章 线性代数",
              "订单 123456789012345678 已发货", "版本 1.2.3"]:
        assert mask(t) == t


def test_blacklist():
    apps, kws = ["KeePass.exe"], ["网银", "Incognito"]
    assert is_blocked("keepass.exe", "x", apps, kws)
    assert is_blocked("chrome.exe", "招商银行网银 - Chrome", apps, kws)
    assert is_blocked("chrome.exe", "New Tab - Incognito", apps, kws)
    assert not is_blocked("Code.exe", "main.py", apps, kws)
