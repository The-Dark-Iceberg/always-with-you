"""决定 0013：主题（铅笔手绘 / 液态玻璃）的界面偏好。后台只收认识的值，默认值就删掉这一项。"""

import pytest

from tests.test_review_030b import TOKEN, api  # noqa: F401  （api 是共用的夹具）

H = {"X-AWY-Token": TOKEN}


@pytest.mark.parametrize("name,value", [
    ("skin", "glass"), ("glassbg", "wall"), ("glassmode", "light"), ("glassmode", "dark"),
    ("motion", "full"), ("motion", "off"), ("glassveil", 0), ("glassveil", 100), ("glassveil", "35"),
])
def test_theme_prefs_accept_known_values(api, name, value):  # noqa: F811
    _, c = api
    assert c.post(f"/api/prefs/{name}", json={"value": value}, headers=H).status_code == 200
    got = c.get("/api/prefs", headers=H).json()[name]
    assert got == (int(value) if name == "glassveil" else value)
    assert c.delete(f"/api/prefs/{name}", headers=H).status_code == 200
    assert name not in c.get("/api/prefs", headers=H).json()


@pytest.mark.parametrize("name,value", [
    ("skin", "pencil"), ("skin", "<img src=x>"), ("glassbg", "bubbles"), ("glassmode", "auto"),
    ("motion", "calm"), ("motion", True), ("glassveil", -1), ("glassveil", 101), ("glassveil", "很透"), ("glassveil", None),
    ("glassveil", True),
])
def test_theme_prefs_reject_unknown_values(api, name, value):  # noqa: F811
    _, c = api
    assert c.post(f"/api/prefs/{name}", json={"value": value}, headers=H).status_code == 400
    assert name not in c.get("/api/prefs", headers=H).json()


def test_unknown_pref_name_is_404(api):  # noqa: F811
    _, c = api
    assert c.post("/api/prefs/whatever", json={"value": "x"}, headers=H).status_code == 404


def test_old_prefs_still_work(api):  # noqa: F811
    _, c = api
    assert c.post("/api/prefs/side", json={"value": "collapsed"}, headers=H).status_code == 200
    assert c.post("/api/prefs/veil", json={"value": "40"}, headers=H).status_code == 200
    p = c.get("/api/prefs", headers=H).json()
    assert p["side"] == "collapsed" and p["veil"] == "40"


def test_glass_files_are_loaded_by_the_page():
    """界面要真的引用玻璃主题的样式和脚本（打包时整个 ui 文件夹都会带上）。"""
    from pathlib import Path
    ui = Path(__file__).resolve().parents[1] / "ui"
    html = (ui / "index.html").read_text(encoding="utf-8")
    assert 'href="css/glass.css"' in html and 'src="js/glass.js"' in html
    assert html.index("js/glass.js") < html.index("js/app.js")   # app.js 启动时要用到 window.Glass
    assert (ui / "css" / "glass.css").exists() and (ui / "js" / "glass.js").exists()
