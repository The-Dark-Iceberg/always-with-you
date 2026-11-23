"""多语言：代码里每一句 t("…")（后台）/ T("…")（界面）在每个翻译文件里都要有，变量名也要一致。

改了界面文字以后跑这个测试，它会列出漏翻的句子。翻译文件在 ui/i18n/<语言>.json。
"""

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
I18N_DIR = ROOT / "ui" / "i18n"
PY_CALL = re.compile(r'(?<![\w.])t\(\s*"((?:[^"\\]|\\.)*)"')
JS_CALL = re.compile(r'(?<![\w.])T\(\s*"((?:[^"\\]|\\.)*)"')
HTML_ATTR = re.compile(r'data-i18n(?:-title|-aria)?="([^"]*)"')
VAR = re.compile(r"\{(\w+)\}")


def source_strings() -> dict[str, str]:
    """{中文原文: 出现在哪个文件}"""
    out: dict[str, str] = {}
    for f in (ROOT / "src" / "awy").rglob("*.py"):
        for m in PY_CALL.finditer(f.read_text(encoding="utf-8")):
            out.setdefault(m.group(1).encode().decode("unicode_escape").encode("latin1").decode("utf-8")
                           if "\\" in m.group(1) else m.group(1), f.name)
    for f in (ROOT / "ui" / "js").glob("*.js"):
        for m in JS_CALL.finditer(f.read_text(encoding="utf-8")):
            out.setdefault(m.group(1), f.name)
    for m in HTML_ATTR.finditer((ROOT / "ui" / "index.html").read_text(encoding="utf-8")):
        out.setdefault(m.group(1), "index.html")
    return out


def lang_files() -> list[Path]:
    return sorted(I18N_DIR.glob("*.json"))


def test_there_is_at_least_english():
    assert (I18N_DIR / "en.json").exists()


@pytest.mark.parametrize("path", lang_files(), ids=lambda p: p.stem)
def test_every_string_is_translated(path):
    tr = json.loads(path.read_text(encoding="utf-8"))
    src = source_strings()
    missing = [f"{s}  （{where}）" for s, where in sorted(src.items()) if s not in tr]
    assert not missing, f"{path.name} 漏翻了 {len(missing)} 句：\n" + "\n".join(missing)


@pytest.mark.parametrize("path", lang_files(), ids=lambda p: p.stem)
def test_placeholders_match(path):
    tr = json.loads(path.read_text(encoding="utf-8"))
    bad = [k for k, v in tr.items() if sorted(VAR.findall(k)) != sorted(VAR.findall(v))]
    assert not bad, f"{path.name} 里这些句子的 {{变量}} 和原文对不上：{bad}"


@pytest.mark.parametrize("path", lang_files(), ids=lambda p: p.stem)
def test_no_leftover_entries(path):
    """翻译文件里不应留着代码里已经不用的句子（改了原文忘了改翻译的情况）。"""
    tr = json.loads(path.read_text(encoding="utf-8"))
    src = source_strings()
    stale = [k for k in tr if k not in src]
    assert not stale, f"{path.name} 里这些句子代码里已经没有了，删掉或改成新原文：{stale}"


def test_python_t_switches_language():
    from awy import i18n
    i18n.set_lang("en")
    try:
        assert i18n.t("保存") == "Save"
        assert i18n.t("向量模型已启用，已为 {n} 条记忆建立索引", n=3).count("3") == 1      # 变量填进了英文句子
        assert "条" not in i18n.t("{n} 条", n=5)
        assert i18n.t("这句没有翻译") == "这句没有翻译"          # 没翻译的直接显示原文，不会出错
    finally:
        i18n.set_lang("zh")
    assert i18n.t("保存") == "保存"


def test_language_setting_via_api(monkeypatch):
    import awy.core as core_mod
    monkeypatch.setattr(core_mod.ServerThread, "start", lambda self: None)
    from starlette.testclient import TestClient

    from awy import i18n
    from awy.core import Core
    from awy.webapi import WebApi
    core = Core()
    c = TestClient(WebApi(core, "k", 48998).app, base_url="http://127.0.0.1:48998")
    c.headers.update({"X-AWY-Token": "k"})
    try:
        assert c.get("/api/status").json()["language"] == "zh"
        assert c.post("/api/settings", json={"language": "klingon"}).status_code == 400
        c.post("/api/settings", json={"language": "en"})
        st = c.get("/api/status").json()
        assert st["language"] == "en" and st["languageSetting"] == "en"
        assert c.get("/api/today").json()["stats"][0]["lab"] == i18n.t("在电脑前") != "在电脑前"
        assert c.post("/api/install/nope").json()["error"] == i18n.t("不认识这个名字")
        c.post("/api/settings", json={"language": ""})                  # 跟随系统（测试里系统语言固定为中文）
        assert c.get("/api/status").json()["language"] == "zh"
    finally:
        i18n.set_lang("zh")
        core.store.close()
