"""手机端 AwyRead 的接收入口（决定 0014）。

手机只在和电脑连同一个 Wi-Fi 时上传。这里负责：
- 找电脑：手机往局域网广播「AWY-DISCOVER 1」（UDP，端口同下），这里回一句自己是谁（编号、电脑名、端口）。
- 配对：用户在设置里点「配对新手机」，这里生成 12 位配对码（10 分钟有效、只能用一次、输错 5 次作废）。
  手机用配对码算出临时钥匙（PBKDF2，20 万次），带着证明（HMAC）来配对；对上了就发一把随机的长期钥匙，
  用临时钥匙加密（AES-GCM）。配对码本身从不在网络上传。长期钥匙用 Windows DPAPI 加密后存在设置里。
- 上传：每批数据用长期钥匙加密，带递增批次号；只收比上次大的（同一个号重发时只回「收到了」，不重复写），
  回给手机的「收到了」也加密。认不出的设备、解不开的数据一律拒绝。
- 收到的数据先检查格式、过隐私规则，再写进原始记录（src = "phone"），格式见 docs/DATA_FORMAT.md。
  同一条（比如同一个小时的步数）内容没变就不重复写；变了再写一条新的，整理时以最新的为准。

这个入口要监听局域网（0.0.0.0），所以默认关着，用户在设置里打开才启动；关掉就停。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import logging
import secrets
import socket
import threading
import time
from datetime import datetime, timedelta
from typing import Any, Callable

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from awy import clock, paths, privacy, rawlog, vault
from awy.config import Settings

log = logging.getLogger(__name__)

CODE_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"   # 去掉了容易看错的 I L O U
CODE_LEN = 12
PAIR_TTL = 600            # 配对码有效 10 分钟
PAIR_MAX_TRIES = 5        # 输错 5 次作废
PBKDF2_ROUNDS = 200_000
MAX_BODY = 4 * 1024 * 1024
MAX_EVENTS = 1000         # 手机每批最多发 400 条，这里留点余量
DISCOVER = b"AWY-DISCOVER 1"
OLDEST = timedelta(days=40)   # 太旧（或在未来）的记录不收：多半是手机时间不对
PRIVATE_APP = "[隐私应用]"


# ---- 加密小工具（和手机端 PcLink.kt 的 Crypto 一一对应）-----------------------------

def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def unb64(text: str) -> bytes:
    return base64.b64decode(text, validate=True)


def new_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LEN))


def format_code(code: str) -> str:
    return "-".join(code[i:i + 4] for i in range(0, len(code), 4))


def normalize_code(text: str) -> str:
    text = text.upper().replace("O", "0").replace("I", "1").replace("L", "1")
    return "".join(c for c in text if c in CODE_ALPHABET)


def pair_key(code: str, pc_id: str) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", code.encode(), f"awy-pair-v1:{pc_id}".encode(), PBKDF2_ROUNDS, 32)


def seal(key: bytes, plain: bytes, aad: str) -> dict[str, str]:
    iv = secrets.token_bytes(12)
    return {"iv": b64(iv), "ct": b64(AESGCM(key).encrypt(iv, plain, aad.encode()))}


def open_box(key: bytes, box: dict[str, Any], aad: str) -> bytes:
    """解不开（钥匙不对、内容被改过）抛 ValueError。"""
    try:
        return AESGCM(key).decrypt(unb64(str(box["iv"])), unb64(str(box["ct"])), aad.encode())
    except (KeyError, ValueError, InvalidTag, TypeError) as e:
        raise ValueError("解不开") from e


# ---- 收到的记录：检查、过隐私、换成原始记录 ----------------------------------------

def _when(value: Any, now: datetime) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if d.tzinfo is None or d < now - OLDEST or d > now + timedelta(days=1):
        return None
    return clock.to_local(d)


def _int(value: Any, lo: int, hi: int) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
        return None
    v = int(value)
    return v if lo <= v <= hi else None


def clean_event(ev: Any, s: Settings, now: datetime) -> dict[str, Any] | None:
    """手机发来的一条 → 原始记录（不含 rx）。格式不对返回 None。"""
    if not isinstance(ev, dict):
        return None
    kind = ev.get("k")
    start = _when(ev.get("start"), now)
    if start is None:
        return None
    iso = lambda d: d.isoformat(timespec="seconds")   # noqa: E731
    if kind in ("app", "screen", "sleep"):
        end = _when(ev.get("end"), now)
        if end is None or not start < end <= start + timedelta(hours=24):
            return None
    if kind == "app":
        name = str(ev.get("app") or "")[:80].strip()
        pkg = str(ev.get("pkg") or "")[:120].strip()
        if not pkg:
            return None
        if privacy.is_blocked(pkg, f"{name} {pkg}", s.blocked_apps, s.blocked_keywords):
            name, pkg = PRIVATE_APP, ""
        else:
            name = privacy.mask(name or pkg)
        return {"ts": iso(start), "src": "phone", "type": "phone_app", "app": name, "pkg": pkg, "end": iso(end)}
    if kind == "screen":
        return {"ts": iso(start), "src": "phone", "type": "phone_screen", "end": iso(end)}
    if kind == "hour":
        out: dict[str, Any] = {"ts": iso(start), "src": "phone", "type": "phone_health"}
        steps = _int(ev.get("steps"), 0, 100_000)
        if steps:
            out["steps"] = steps
        for k in ("hr_min", "hr_avg", "hr_max"):
            v = _int(ev.get(k), 20, 250)
            if v is not None:
                out[k] = v
        return out if len(out) > 3 else None
    if kind == "sleep":
        out = {"ts": iso(start), "src": "phone", "type": "phone_sleep", "end": iso(end)}
        for k in ("deep", "light", "rem", "awake"):
            out[k] = _int(ev.get(k), 0, 1440) or 0
        out["by"] = privacy.mask(str(ev.get("by") or ""))[:40]
        return out
    return None


def event_key(ev: dict[str, Any]) -> str:
    """同一条记录的「键」：同一个键再收到时，内容没变就不写。"""
    return f"{ev['type']}|{ev.get('pkg', '')}|{ev['ts']}"


def _digest(ev: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(ev, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]


class PhoneState:
    """phone/state.json：每台手机的最后批次号和最后联系时间；phone/index.json：写过的记录（去重用）。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()

    @staticmethod
    def _dir():
        d = paths.data_dir() / "phone"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _read(self, name: str) -> dict[str, Any]:
        try:
            data = json.loads((self._dir() / name).read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _write(self, name: str, data: dict[str, Any]) -> None:
        f = self._dir() / name
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(f)

    def device(self, dev_id: str) -> dict[str, Any]:
        with self._lock:
            d = self._read("state.json").get(dev_id)
            return d if isinstance(d, dict) else {}

    def touch(self, dev_id: str, seq: int | None = None) -> None:
        with self._lock:
            st = self._read("state.json")
            d = st.get(dev_id) if isinstance(st.get(dev_id), dict) else {}
            if seq is not None:
                d["last_seq"] = seq
            d["last_seen"] = clock.now_iso()
            st[dev_id] = d
            self._write("state.json", st)

    def forget(self, dev_id: str) -> None:
        with self._lock:
            st = self._read("state.json")
            if st.pop(dev_id, None) is not None:
                self._write("state.json", st)

    def log_batch(self, rx: str, days: set) -> None:
        """记一笔「什么时候收到了哪几天的数据」（phone/batches.jsonl）。整理时只读这几天的原始记录，不用把一个多月翻一遍。"""
        with self._lock:
            with (self._dir() / "batches.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps({"rx": rx, "days": sorted(d.isoformat() for d in days)}) + "\n")

    def days_received(self, start: datetime, end: datetime) -> list:
        """rx 在 [start, end) 之间收到的数据涉及哪几天。顺便删掉 60 天前的记录。"""
        from datetime import date as _date
        f = self._dir() / "batches.jsonl"
        out: set = set()
        keep: list[str] = []
        cutoff = clock.now() - timedelta(days=60)
        with self._lock:
            try:
                lines = f.read_text(encoding="utf-8").splitlines()
            except OSError:
                return []
            for line in lines:
                try:
                    item = json.loads(line)
                    rx = datetime.fromisoformat(item["rx"])
                except (ValueError, KeyError, TypeError):
                    continue
                if rx >= cutoff:
                    keep.append(line)
                if start <= rx < end:
                    out.update(_date.fromisoformat(d) for d in item.get("days", []))
            if len(keep) < len(lines):
                tmp = f.with_suffix(".tmp")
                tmp.write_text("".join(k + "\n" for k in keep), encoding="utf-8")
                tmp.replace(f)
        return sorted(out)

    def fresh(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """去掉内容没变的重复记录，并记下这次写的。索引里只留 45 天内的。"""
        with self._lock:
            index = self._read("index.json")
            out = []
            for ev in events:
                k, h = event_key(ev), _digest(ev)
                if index.get(k) == h:
                    continue
                index[k] = h
                out.append(ev)
            cutoff = (clock.today() - timedelta(days=45)).isoformat()   # 键的最后一段是记录时间，前 10 位是日期
            index = {k: v for k, v in index.items() if k.rsplit("|", 1)[-1][:10] >= cutoff}
            self._write("index.json", index)
            return out


# ---- 本机在局域网里的地址 ------------------------------------------------------
# 只认真实的 Wi-Fi / 有线网卡（用户要求：虚拟网卡那边不配对）。VPN、组网工具、虚拟机、蓝牙这些网卡上的地址
# 不在设置页显示，从它们那边来的请求一律拒绝。Windows「移动热点」用的「本地连接*」是真实的无线网卡，算在内。
# 这里只读网卡列表，不改任何网卡设置。

VIRTUAL_ADAPTERS = ("zerotier", "radmin", "wintun", "vmware", "virtualbox", "vbox", "hyper-v", "vethernet",
                    "loopback", "tailscale", "wireguard", "openvpn", "tap-", "tun", "vpn", "docker", "wsl",
                    "npcap", "clash", "蓝牙", "bluetooth")
_lan_cache: tuple[float, list] = (0.0, [])


def lan_networks() -> list[ipaddress.IPv4Interface]:
    """真实网卡（已连接）的 IPv4 地址和网段。30 秒内重复调用用缓存。"""
    global _lan_cache
    if time.time() - _lan_cache[0] < 30:
        return _lan_cache[1]
    import psutil
    out: list[ipaddress.IPv4Interface] = []
    stats = psutil.net_if_stats()
    for name, addrs in psutil.net_if_addrs().items():
        st = stats.get(name)
        if any(k in name.lower() for k in VIRTUAL_ADAPTERS) or not st or not st.isup:
            continue
        for a in addrs:
            if a.family == socket.AF_INET and a.netmask and not a.address.startswith(("127.", "169.254.")):
                try:
                    out.append(ipaddress.IPv4Interface(f"{a.address}/{a.netmask}"))
                except ValueError:
                    continue
    _lan_cache = (time.time(), out)
    return out


def lan_addresses() -> list[str]:
    """设置页显示的「这台电脑的地址」：只有真实网卡上的。"""
    return [str(i.ip) for i in lan_networks()]


def is_lan_client(host: str) -> bool:
    """请求是不是从真实网卡所在的网段来的（本机 127.0.0.1 也算：测试、adb 转发）。"""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    if ip.is_loopback:
        return True
    return isinstance(ip, ipaddress.IPv4Address) and any(ip in i.network for i in lan_networks())


# ---- 接收端 ----------------------------------------------------------------

class PhoneBridge:
    """手机的接收端。devices 存在设置里（phone_devices），钥匙用 DPAPI 加密。"""

    def __init__(self, get_settings: Callable[[], Settings], update_settings: Callable[..., None],
                 sink: Callable[[dict], None] = rawlog.append,
                 allow_client: Callable[[str], bool] = is_lan_client) -> None:
        self._get_settings = get_settings
        self._update = update_settings
        self._sink = sink
        self.allow_client = allow_client   # 只收真实网卡网段（和本机）来的请求，见 is_lan_client
        self.state = PhoneState()
        self._lock = threading.Lock()
        self._pairing: dict[str, Any] | None = None
        self.app = Starlette(routes=[
            Route("/phone/hello", self.hello),
            Route("/phone/pair", self.pair, methods=["POST"]),
            Route("/phone/upload", self.upload, methods=["POST"]),
        ])

    # ---- 给设置页用 ----
    def hello_info(self) -> dict[str, Any]:
        s = self._get_settings()
        return {"awy": 1, "pc": s.phone_pc_id, "name": socket.gethostname()[:40], "port": s.phone_port}

    def start_pairing(self) -> dict[str, Any]:
        """生成新的配对码（旧的作废）。临时钥匙先算好（算一次要零点几秒）。"""
        code = new_code()
        key = pair_key(code, self._get_settings().phone_pc_id)
        with self._lock:
            self._pairing = {"code": code, "key": key, "expires": time.time() + PAIR_TTL, "tries": 0}
        return self.pairing_info() or {}

    def cancel_pairing(self) -> None:
        with self._lock:
            self._pairing = None

    def pairing_info(self) -> dict[str, Any] | None:
        with self._lock:
            p = self._pairing
            if p and p["expires"] < time.time():
                self._pairing = p = None
            if not p:
                return None
            return {"code": format_code(p["code"]), "expiresIn": int(p["expires"] - time.time())}

    def devices(self) -> list[dict[str, Any]]:
        out = []
        for d in self._get_settings().phone_devices:
            st = self.state.device(str(d.get("id", "")))
            out.append({"id": d.get("id"), "name": d.get("name", ""), "pairedAt": d.get("paired_at", ""),
                        "lastSeen": st.get("last_seen", "")})
        return out

    def remove_device(self, dev_id: str) -> bool:
        devs = self._get_settings().phone_devices
        keep = [d for d in devs if d.get("id") != dev_id]
        if len(keep) == len(devs):
            return False
        self._update(phone_devices=keep)
        self.state.forget(dev_id)
        return True

    def _device_key(self, dev_id: str) -> bytes | None:
        for d in self._get_settings().phone_devices:
            if d.get("id") == dev_id and dev_id:
                try:
                    return unb64(vault.unprotect(str(d.get("key", ""))))
                except (OSError, ValueError):
                    log.warning("手机 %s 的钥匙解不开", dev_id)
                    return None
        return None

    # ---- 接口 ----
    def _allowed(self, request: Request) -> bool:
        host = request.client.host if request.client else ""
        if self.allow_client(host):
            return True
        log.info("拒绝了不在本地网络里的请求：%s", host)
        return False

    async def _json(self, request: Request) -> dict[str, Any] | None:
        raw = await request.body()
        if len(raw) > MAX_BODY:
            return None
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None

    async def hello(self, request: Request) -> Response:
        if not self._allowed(request):
            return JSONResponse({"error": "not local network"}, status_code=403)
        return JSONResponse(self.hello_info())

    async def pair(self, request: Request) -> Response:
        if not self._allowed(request):
            return JSONResponse({"error": "not local network"}, status_code=403)
        data = await self._json(request)
        if data is None:
            return JSONResponse({"error": "bad request"}, status_code=400)
        nonce = str(data.get("nonce", ""))[:64]
        device = str(data.get("device", ""))[:60].strip() or "手机"
        proof = str(data.get("proof", ""))
        with self._lock:
            p = self._pairing
            if not p or p["expires"] < time.time():
                self._pairing = None
                return JSONResponse({"error": "no pairing"}, status_code=403)
            expected = b64(hmac.new(p["key"], f"pair|{nonce}|{device}".encode(), hashlib.sha256).digest())
            if not nonce or not hmac.compare_digest(expected, proof):
                p["tries"] += 1
                if p["tries"] >= PAIR_MAX_TRIES:
                    self._pairing = None
                    log.warning("配对码输错 %d 次，已作废", PAIR_MAX_TRIES)
                    return JSONResponse({"error": "too many tries"}, status_code=429)
                return JSONResponse({"error": "wrong code"}, status_code=403)
            self._pairing = None   # 配对码只能用一次
            temp_key = p["key"]
        dev_id = secrets.token_hex(8)
        key = secrets.token_bytes(32)
        s = self._get_settings()
        self._update(phone_devices=[*s.phone_devices, {"id": dev_id, "name": privacy.mask(device),
                                                        "key": vault.protect(b64(key)), "paired_at": clock.now_iso()}])
        self.state.touch(dev_id, 0)
        log.info("新手机配对：%s", device)
        info = {**self.hello_info(), "id": dev_id, "key": b64(key)}
        return JSONResponse(seal(temp_key, json.dumps(info).encode(), f"pair-resp|{nonce}"))

    async def upload(self, request: Request) -> Response:
        if not self._allowed(request):
            return JSONResponse({"error": "not local network"}, status_code=403)
        data = await self._json(request)
        if data is None:
            return JSONResponse({"error": "bad request"}, status_code=400)
        dev_id = str(data.get("id", ""))
        key = self._device_key(dev_id)
        if key is None:
            return JSONResponse({"error": "unknown device"}, status_code=403)
        try:
            batch = json.loads(open_box(key, data, f"up|{dev_id}"))
            seq = int(batch["seq"])
            events = batch.get("events") or []
            if not isinstance(events, list):
                raise ValueError
        except (ValueError, KeyError, TypeError):
            return JSONResponse({"error": "cannot open"}, status_code=403)
        last = int(self.state.device(dev_id).get("last_seq", 0) or 0)
        if seq < last:
            return JSONResponse({"error": "old batch", "last": last}, status_code=409)
        stored = 0
        if seq > last:   # seq == last：手机没收到上次的回应、又发了一遍，只回「收到了」
            stored = await self._store(events[:MAX_EVENTS])
            self.state.touch(dev_id, seq)
        else:
            self.state.touch(dev_id)
        return JSONResponse(seal(key, json.dumps({"ack": seq, "stored": stored}).encode(), f"ack|{dev_id}"))

    async def _store(self, events: list[Any]) -> int:
        s = self._get_settings()
        if not s.collect_enabled:
            return 0   # 暂停记录时：收下但不记（和浏览器扩展一样）
        now = clock.now()
        cleaned = [ev for ev in (clean_event(e, s, now) for e in events) if ev]
        rx = clock.now().isoformat()   # 精确到微秒：整理时按「rx 晚于上次整理」找新收到的，同一秒里的也不会漏
        n = 0
        days: set = set()
        for ev in self.state.fresh(cleaned):
            try:
                self._sink({**ev, "rx": rx})
                n += 1
                days.add(datetime.fromisoformat(ev["ts"]).date())   # 原始记录存在 ts 那天的文件夹里
                if "end" in ev:
                    days.add(datetime.fromisoformat(ev["end"]).date())
            except OSError:
                log.exception("写原始记录失败")
        if days:
            self.state.log_batch(rx, days)
        return n


class Discovery:
    """回应手机的「谁是 AlwaysWithYou」广播（UDP）。"""

    def __init__(self, bridge: PhoneBridge, port: int) -> None:
        self.bridge = bridge
        self.port = port
        self._stop = threading.Event()
        self.error: str | None = None
        self._thread = threading.Thread(target=self._run, name="phone-discovery", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=3)

    def _run(self) -> None:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.bind(("0.0.0.0", self.port))
        except OSError as e:
            self.error = f"找电脑用的端口 {self.port} 打不开：{e}"
            log.error(self.error)
            return
        sock.settimeout(1.0)
        with sock:
            while not self._stop.is_set():
                try:
                    data, addr = sock.recvfrom(256)
                except socket.timeout:
                    continue
                except OSError:
                    continue
                if data.strip() == DISCOVER and self.bridge.allow_client(addr[0]):
                    try:
                        sock.sendto(json.dumps(self.bridge.hello_info()).encode(), addr)
                    except OSError:
                        pass
