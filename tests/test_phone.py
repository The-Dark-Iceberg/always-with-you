"""手机接收入口（决定 0014）：配对、加密上传、防重放、隐私过滤、去重、手机摘要。

这里用 Python 扮演手机端（和 android/.../PcLink.kt 做同样的计算），不需要真手机。
"""

import hashlib
import hmac
import json
from datetime import timedelta

import pytest
from starlette.testclient import TestClient

from awy import clock, config, phone, rawlog
from awy.phone import PhoneBridge, PhoneState, b64, open_box, pair_key, seal, unb64


@pytest.fixture
def fast(monkeypatch):
    monkeypatch.setattr(phone, "PBKDF2_ROUNDS", 1000)   # 测试里算快一点；真实轮数见 test_pair_key_is_stable


@pytest.fixture
def setup(fast):
    s = config.Settings()
    s.ensure_tokens()
    written = []

    def update(**kw):
        for k, v in kw.items():
            setattr(s, k, v)

    bridge = PhoneBridge(lambda: s, update, sink=written.append, allow_client=lambda host: True)
    return s, bridge, TestClient(bridge.app), written


def pair(s, bridge, client, code=None, device="Test Phone"):
    """扮演手机配对，返回 (设备编号, 长期钥匙)。"""
    code = code or phone.normalize_code(bridge.start_pairing()["code"])
    key = pair_key(code, s.phone_pc_id)
    nonce = b64(b"n" * 16)
    proof = b64(hmac.new(key, f"pair|{nonce}|{device}".encode(), hashlib.sha256).digest())
    r = client.post("/phone/pair", json={"v": 1, "device": device, "nonce": nonce, "proof": proof})
    assert r.status_code == 200, r.text
    info = json.loads(open_box(key, r.json(), f"pair-resp|{nonce}"))
    assert info["pc"] == s.phone_pc_id
    return info["id"], unb64(info["key"])


def upload(client, dev_id, key, seq, events):
    box = seal(key, json.dumps({"seq": seq, "events": events}).encode(), f"up|{dev_id}")
    return client.post("/phone/upload", json={"v": 1, "id": dev_id, **box})


def iso(delta_minutes=0):
    return (clock.now() - timedelta(minutes=delta_minutes)).isoformat(timespec="seconds")


def test_pair_key_is_stable():
    # 手机端（Kotlin）和电脑端必须算出同一把钥匙：算法一改就配不上了。真机上已经实测配对成功过（2026-11-22）
    assert pair_key("0123456789AB", "pc").hex()[:16] == hashlib.pbkdf2_hmac(
        "sha256", b"0123456789AB", b"awy-pair-v1:pc", 200_000, 32).hex()[:16]


def test_code_format():
    code = phone.new_code()
    assert len(code) == 12 and set(code) <= set(phone.CODE_ALPHABET)
    assert phone.normalize_code(phone.format_code(code).lower()) == code
    assert phone.normalize_code("7k3q-9xmd-2pLf") == "7K3Q9XMD2P1F"   # 小写、L 当 1


def test_pair_then_upload_roundtrip(setup):
    s, bridge, client, written = setup
    dev_id, key = pair(s, bridge, client)
    assert s.phone_devices[0]["name"] == "Test Phone"
    assert s.phone_devices[0]["key"] != b64(key)          # 存的是加密后的
    events = [
        {"k": "app", "pkg": "tv.danmaku.bili", "app": "哔哩哔哩", "start": iso(60), "end": iso(30)},
        {"k": "screen", "start": iso(61), "end": iso(29)},
        {"k": "hour", "start": iso(120), "steps": 1200, "hr_min": 60, "hr_avg": 72, "hr_max": 98},
        {"k": "sleep", "start": iso(600), "end": iso(150), "deep": 80, "light": 300, "rem": 70, "awake": 10, "by": "欢太健康"},
    ]
    r = upload(client, dev_id, key, 1, events)
    assert r.status_code == 200
    ack = json.loads(open_box(key, r.json(), f"ack|{dev_id}"))
    assert ack == {"ack": 1, "stored": 4}
    assert [e["type"] for e in written] == ["phone_app", "phone_screen", "phone_health", "phone_sleep"]
    assert all(e["src"] == "phone" and e["rx"] for e in written)
    assert bridge.devices()[0]["lastSeen"]


def test_code_is_single_use_and_locks_after_five_wrong(setup):
    s, bridge, client, _ = setup
    code = phone.normalize_code(bridge.start_pairing()["code"])
    pair(s, bridge, client, code)
    with pytest.raises(AssertionError):     # 用过一次就作废
        pair(s, bridge, client, code)
    bridge.start_pairing()
    for i in range(5):
        nonce = b64(bytes([i]) * 16)
        r = client.post("/phone/pair", json={"nonce": nonce, "device": "x", "proof": b64(b"0" * 32)})
        assert r.status_code == (429 if i == 4 else 403)
    assert bridge.pairing_info() is None    # 输错 5 次作废


def test_pairing_expires(setup, monkeypatch):
    _, bridge, _, _ = setup
    bridge.start_pairing()
    import time as _t
    real = _t.time
    monkeypatch.setattr(phone.time, "time", lambda: real() + phone.PAIR_TTL + 1)
    assert bridge.pairing_info() is None


def test_replay_and_old_batches(setup):
    s, bridge, client, written = setup
    dev_id, key = pair(s, bridge, client)
    ev = [{"k": "app", "pkg": "a.b", "app": "微信", "start": iso(10), "end": iso(5)}]
    assert upload(client, dev_id, key, 3, ev).status_code == 200
    r = upload(client, dev_id, key, 3, ev)          # 手机没收到回应又发了一遍：只回收到，不重复写
    assert json.loads(open_box(key, r.json(), f"ack|{dev_id}")) == {"ack": 3, "stored": 0}
    assert len(written) == 1
    r = upload(client, dev_id, key, 2, ev)          # 比上次还旧：拒绝，并告诉手机上次是几
    assert r.status_code == 409 and r.json()["last"] == 3


def test_unknown_device_tampered_and_unpaired(setup):
    s, bridge, client, written = setup
    dev_id, key = pair(s, bridge, client)
    assert upload(client, "nope", key, 1, []).status_code == 403
    assert upload(client, dev_id, b"x" * 32, 1, []).status_code == 403     # 钥匙不对
    box = seal(key, b'{"seq":1,"events":[]}', f"up|{dev_id}")
    box["ct"] = b64(unb64(box["ct"])[:-1] + b"\0")                           # 内容被改过
    assert client.post("/phone/upload", json={"id": dev_id, **box}).status_code == 403
    assert bridge.remove_device(dev_id)
    assert upload(client, dev_id, key, 1, []).status_code == 403             # 取消配对后不再收
    assert client.post("/phone/upload", content=b"not json").status_code == 400
    assert written == []


def test_clean_event_privacy_and_validation():
    s = config.Settings()
    now = clock.now()
    blocked = phone.clean_event({"k": "app", "pkg": "com.eg.android.AlipayGphone", "app": "支付宝",
                                 "start": iso(10), "end": iso(5)}, s, now)
    assert blocked["app"] == phone.PRIVATE_APP and blocked["pkg"] == ""
    masked = phone.clean_event({"k": "app", "pkg": "x.y", "app": "验证码 123456", "start": iso(10), "end": iso(5)}, s, now)
    assert "123456" not in masked["app"]
    assert phone.clean_event({"k": "app", "pkg": "x.y", "start": "2026-11-22T08:00:00", "end": iso(1)}, s, now) is None   # 没时区
    assert phone.clean_event({"k": "app", "pkg": "x.y", "start": iso(-3000), "end": iso(-3001)}, s, now) is None          # 未来
    assert phone.clean_event({"k": "app", "pkg": "x.y", "start": iso(5), "end": iso(10)}, s, now) is None                 # 结束早于开始
    assert phone.clean_event({"k": "screen", "start": iso(60 * 25 + 1), "end": iso(0)}, s, now) is None                   # 一段超过 24 小时
    assert phone.clean_event({"k": "hour", "start": iso(60), "hr_avg": 500}, s, now) is None                              # 心率不合理
    hour = phone.clean_event({"k": "hour", "start": iso(60), "steps": 30, "hr_avg": 70, "hr_max": True}, s, now)
    assert hour["steps"] == 30 and hour["hr_avg"] == 70 and "hr_max" not in hour
    assert phone.clean_event({"k": "whatever", "start": iso(1)}, s, now) is None
    assert phone.clean_event("not a dict", s, now) is None


def test_same_record_not_written_twice_but_changes_are(setup):
    s, bridge, client, written = setup
    dev_id, key = pair(s, bridge, client)
    start = iso(120)
    upload(client, dev_id, key, 1, [{"k": "hour", "start": start, "steps": 100}])
    upload(client, dev_id, key, 2, [{"k": "hour", "start": start, "steps": 100}])   # 一样：不写
    upload(client, dev_id, key, 3, [{"k": "hour", "start": start, "steps": 900}])   # 手表晚同步，步数变多：再写一条
    assert [e["steps"] for e in written] == [100, 900]


def test_paused_recording_acks_but_does_not_store(setup):
    s, bridge, client, written = setup
    dev_id, key = pair(s, bridge, client)
    s.collect_enabled = False
    r = upload(client, dev_id, key, 1, [{"k": "screen", "start": iso(10), "end": iso(5)}])
    assert json.loads(open_box(key, r.json(), f"ack|{dev_id}"))["stored"] == 0 and written == []


def test_hello_says_who_we_are(setup):
    s, _, client, _ = setup
    info = client.get("/phone/hello").json()
    assert info == {"awy": 1, "pc": s.phone_pc_id, "name": info["name"], "port": 47824}


def test_config_gets_pc_id_once(tmp_path):
    p = tmp_path / "c.json"
    a = config.load(p)
    assert len(a.phone_pc_id) == 16 and a.phone_enabled is False
    assert config.load(p).phone_pc_id == a.phone_pc_id


def test_phone_episode_from_late_data(fast, store):
    """手机回家才上传：昨天的数据今天收到，也要写进这次的手机摘要；同样的数据不会再写第二次。"""
    from awy import pipeline
    s = config.Settings()
    s.ensure_tokens()
    bridge = PhoneBridge(lambda: s, lambda **kw: [setattr(s, k, v) for k, v in kw.items()], allow_client=lambda host: True)  # 写真的原始记录
    client = TestClient(bridge.app)
    dev_id, key = pair(s, bridge, client)
    now = clock.now()
    y = now - timedelta(days=1)
    at = lambda d, m: (d - timedelta(minutes=m)).isoformat(timespec="seconds")   # noqa: E731
    events = [
        {"k": "app", "pkg": "tv.danmaku.bili", "app": "哔哩哔哩", "start": at(y, 90), "end": at(y, 30)},
        {"k": "app", "pkg": "com.tencent.mm", "app": "微信", "start": at(y, 29), "end": at(y, 20)},
        {"k": "screen", "start": at(y, 91), "end": at(y, 19)},
        {"k": "hour", "start": at(y, 120), "steps": 3000, "hr_min": 55, "hr_avg": 70, "hr_max": 120},
        {"k": "sleep", "start": at(now, 600), "end": at(now, 120), "deep": 80, "light": 300, "rem": 90, "awake": 10, "by": "欢太健康"},
    ]
    assert upload(client, dev_id, key, 1, events).status_code == 200
    ep = pipeline.make_phone_episode(store, clock.now())
    assert ep
    text = store.pending_episodes()[-1]["content"]
    assert "手机活动摘要" in text and "哔哩哔哩（1 小时）" in text and "微信" in text
    assert "步数：共 3000 步" in text and "最高 120" in text and "深睡 1 小时 20 分" in text and "欢太健康" in text
    assert pipeline.make_phone_episode(store, clock.now()) is None   # 没有新收到的
    # 再收到同一小时更新后的步数：这次摘要里写的是最新的
    upload(client, dev_id, key, 2, [{"k": "hour", "start": at(y, 120), "steps": 4200, "hr_avg": 70}])
    assert pipeline.make_phone_episode(store, clock.now())
    assert "步数：共 4200 步" in store.pending_episodes()[-1]["content"]


def test_days_received_only_reads_needed_days(fast):
    st = PhoneState()
    now = clock.now()
    st.log_batch((now - timedelta(hours=2)).isoformat(), {now.date()})
    st.log_batch((now - timedelta(days=70)).isoformat(), {now.date() - timedelta(days=70)})
    assert st.days_received(now - timedelta(hours=3), now) == [now.date()]
    lines = (st._dir() / "batches.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1        # 60 天前的那行顺手删掉了


def test_nothing_written_to_raw_without_rx(fast):
    """手机写进原始记录的每一条都带 rx（收到的时间），整理时靠它找「新收到的」。"""
    s = config.Settings()
    s.ensure_tokens()
    bridge = PhoneBridge(lambda: s, lambda **kw: [setattr(s, k, v) for k, v in kw.items()], allow_client=lambda host: True)
    client = TestClient(bridge.app)
    dev_id, key = pair(s, bridge, client)
    upload(client, dev_id, key, 1, [{"k": "screen", "start": iso(10), "end": iso(5)}])
    evs = [e for e in rawlog.read_day(clock.today()) if e.get("src") == "phone"]
    assert evs and all(e.get("rx") for e in evs)


def test_only_real_lan_adapters_count(monkeypatch):
    """用户要求：虚拟网卡那边不配对。VPN / 组网 / 虚拟机网卡的地址不显示，从那边来的请求拒绝。"""
    import ipaddress
    import socket
    from types import SimpleNamespace as NS
    addr = lambda ip, mask: NS(family=socket.AF_INET, address=ip, netmask=mask)   # noqa: E731
    fake_addrs = {
        "WLAN": [addr("10.20.30.40", "255.252.0.0")],
        "本地连接* 2": [addr("192.168.137.1", "255.255.255.0")],          # Windows 移动热点：真实无线网卡
        "Radmin VPN": [addr("26.133.170.246", "255.0.0.0")],
        "ZeroTier One [abc]": [addr("10.252.205.238", "255.255.255.0")],
        "wintun": [addr("10.0.0.33", "255.255.255.0")],
        "VMware Network Adapter VMnet8": [addr("192.168.23.1", "255.255.255.0")],
        "以太网": [addr("169.254.104.124", "255.255.0.0")],
    }
    up = {k: NS(isup=True) for k in fake_addrs}
    import psutil
    monkeypatch.setattr(psutil, "net_if_addrs", lambda: fake_addrs)
    monkeypatch.setattr(psutil, "net_if_stats", lambda: up)
    monkeypatch.setattr(phone, "_lan_cache", (0.0, []))
    assert phone.lan_addresses() == ["10.20.30.40", "192.168.137.1"]
    assert phone.is_lan_client("10.20.29.15")          # 同一个 Wi-Fi 里的手机
    assert phone.is_lan_client("192.168.137.23")         # 连电脑热点的手机
    assert phone.is_lan_client("127.0.0.1")
    for bad in ("10.252.205.9", "26.1.2.3", "10.0.0.5", "192.168.23.7", "8.8.8.8", "testclient", ""):
        assert not phone.is_lan_client(bad), bad
    assert ipaddress.ip_address("10.20.29.15") in phone.lan_networks()[0].network


def test_requests_from_outside_lan_are_refused(fast):
    s = config.Settings()
    s.ensure_tokens()
    bridge = PhoneBridge(lambda: s, lambda **kw: None, sink=lambda e: None, allow_client=lambda host: False)
    client = TestClient(bridge.app)
    bridge.start_pairing()
    assert client.get("/phone/hello").status_code == 403
    assert client.post("/phone/pair", json={"nonce": "x", "device": "x", "proof": "x"}).status_code == 403
    assert bridge.pairing_info() is not None             # 被拒绝的请求不算「输错一次」
    assert client.post("/phone/upload", json={"id": "x"}).status_code == 403
