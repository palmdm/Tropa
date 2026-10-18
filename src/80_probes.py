

# ===========================================================================
# Проверка задержки и сведения о сети
# ===========================================================================
PING_METHODS = ("tcp", "get", "head", "icmp")
PING_DISPLAYS = ("digits", "bars", "both", "dots")
PING_URL_DEFAULT = "https://www.gstatic.com/generate_204"
PING_URL_PRESETS = (
    ("Google", "https://www.gstatic.com/generate_204"),
    ("Cloudflare", "https://cp.cloudflare.com/generate_204"),
    ("Apple", "https://www.apple.com/library/test/success.html"),
    ("Apple Captive", "https://captive.apple.com/hotspot-detect.html"),
    ("Telegram", "https://api.telegram.org/bot"),
)
PING_FAIL = -1
TEST_WORKERS = 24
TEST_BATCH = 120
TEST_LIMIT = 240
_BARS = {4: "▂▄▆█", 3: "▂▄▆▁", 2: "▂▄▁▁", 1: "▂▁▁▁"}


class IcmpUnavailable(Exception):
    pass


def normalize_url(raw):
    s = str(raw or "").strip()
    if not s:
        return PING_URL_DEFAULT
    if "://" not in s:
        s = "https://" + s
    try:
        parts = urllib.parse.urlsplit(s)
        if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
            return PING_URL_DEFAULT
        _ = parts.port
    except Exception:
        return PING_URL_DEFAULT
    return s


def _resolve(host, port=0):
    infos = socket.getaddrinfo(str(host), int(port or 0), 0, socket.SOCK_STREAM)
    for fam, _t, _p, _c, sa in infos:
        if fam == socket.AF_INET:
            return fam, sa
    return infos[0][0], infos[0][4]


def tcp_ping(host, port, timeout):
    try:
        fam, sa = _resolve(host, port)
    except Exception:
        return PING_FAIL
    s = socket.socket(fam, socket.SOCK_STREAM)
    try:
        s.settimeout(float(timeout))
        t0 = _now()
        s.connect(sa)
        return max(1, int(round((_now() - t0) * 1000)))
    except Exception:
        return PING_FAIL
    finally:
        s.close()


def _icmp_sum(data):
    if len(data) % 2:
        data += b"\x00"
    total = sum(struct.unpack("!%dH" % (len(data) // 2), data))
    total = (total >> 16) + (total & 0xFFFF)
    total += total >> 16
    return ~total & 0xFFFF


def icmp_ping(host, timeout):
    try:
        fam, sa = _resolve(host)
    except Exception:
        return PING_FAIL
    v6 = fam == socket.AF_INET6
    try:
        s = socket.socket(fam, socket.SOCK_DGRAM, socket.IPPROTO_ICMPV6 if v6 else socket.IPPROTO_ICMP)
    except Exception as e:
        raise IcmpUnavailable(str(e))
    try:
        seq = random.randint(1, 0xFFFF)
        req, rep = (128, 129) if v6 else (8, 0)
        payload = b"tropa-ping" + os.urandom(8)
        head = struct.pack("!BBHHH", req, 0, 0, 0, seq)
        if not v6:
            head = struct.pack("!BBHHH", req, 0, _icmp_sum(head + payload), 0, seq)
        t0 = _now()
        deadline = t0 + float(timeout)
        s.sendto(head + payload, (sa[0], 0, sa[2], sa[3]) if v6 else (sa[0], 0))
        while True:
            left = deadline - _now()
            if left <= 0:
                return PING_FAIL
            s.settimeout(left)
            data, _ = s.recvfrom(2048)
            if data and not v6 and data[0] >> 4 == 4:
                data = data[(data[0] & 0x0F) * 4:]
            if len(data) >= 8 and data[0] == rep and struct.unpack("!H", data[6:8])[0] == seq:
                return max(1, int(round((_now() - t0) * 1000)))
    except Exception:
        return PING_FAIL
    finally:
        s.close()


def _recv_exact(sock, n, deadline):
    buf = b""
    while len(buf) < n:
        left = deadline - _now()
        if left <= 0:
            raise socket.timeout()
        sock.settimeout(left)
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise OSError("closed")
        buf += chunk
    return buf


def http_probe(local_port, user, password, url, method, timeout):
    """Реальная задержка: HTTP(S)-запрос через локальный SOCKS5-вход ядра, мс или PING_FAIL."""
    s = None
    try:
        parts = urllib.parse.urlsplit(url)
        https = parts.scheme.lower() == "https"
        host = parts.hostname or ""
        tport = int(parts.port or (443 if https else 80))
        path = (parts.path or "/") + (("?" + parts.query) if parts.query else "")
        t0 = _now()
        deadline = t0 + float(timeout)
        s = socket.create_connection((LOCAL_HOST, int(local_port)), timeout=float(timeout))
        ub, pb = str(user).encode(), str(password).encode()
        s.sendall(b"\x05\x01\x02")
        if _recv_exact(s, 2, deadline) != b"\x05\x02":
            return PING_FAIL
        s.sendall(b"\x01" + bytes([len(ub)]) + ub + bytes([len(pb)]) + pb)
        if _recv_exact(s, 2, deadline)[1] != 0:
            return PING_FAIL
        hb = host.encode("idna")
        s.sendall(b"\x05\x01\x00\x03" + bytes([len(hb)]) + hb + struct.pack("!H", tport))
        rep = _recv_exact(s, 4, deadline)
        if rep[1] != 0:
            return PING_FAIL
        tail = {1: 6, 4: 18}.get(rep[3])
        if tail is None:
            tail = _recv_exact(s, 1, deadline)[0] + 2
        _recv_exact(s, tail, deadline)
        if https:
            if ssl is None:
                return PING_FAIL
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            try:
                ctx.set_alpn_protocols(["http/1.1"])
            except Exception:
                pass
            s.settimeout(max(0.05, deadline - _now()))
            s = ctx.wrap_socket(s, server_hostname=host)
        host_hdr = host if tport in (80, 443) else f"{host}:{tport}"
        verb = "HEAD" if method == "head" else "GET"
        s.settimeout(max(0.05, deadline - _now()))
        s.sendall(f"{verb} {path} HTTP/1.1\r\nHost: {host_hdr}\r\nUser-Agent: Tropa\r\nAccept: */*\r\n"
                  f"Connection: close\r\n\r\n".encode())
        buf = b""
        while b"\n" not in buf and len(buf) < 8192:
            left = deadline - _now()
            if left <= 0:
                return PING_FAIL
            s.settimeout(left)
            chunk = s.recv(1024)
            if not chunk:
                break
            buf += chunk
        bits = buf.split(b"\n", 1)[0].split()
        if len(bits) >= 2 and bits[0].startswith(b"HTTP/") and bits[1][:3].isdigit():
            return max(1, int(round((_now() - t0) * 1000)))
        return PING_FAIL
    except Exception:
        return PING_FAIL
    finally:
        if s is not None:
            try:
                s.close()
            except Exception:
                pass


def direct_probe(node, method, timeout):
    """Проверка без ядра -> (мс или PING_FAIL, какой метод сработал).

    Hysteria2 и TUIC работают поверх UDP, поэтому для них TCP-метод проверяет только доступность
    адреса: TCP на тот же порт (как в exitFy), а если не ответил — ICMP."""
    if method == "icmp":
        return icmp_ping(node["host"], timeout), "icmp"
    ms = tcp_ping(node["host"], node["port"], timeout)
    if ms > 0 or node["proto"] not in UDP_PROTOCOLS:
        return ms, "tcp"
    try:
        return icmp_ping(node["host"], timeout), "icmp"
    except IcmpUnavailable:
        return ms, "tcp"


def ping_level(ms, method):
    if ms is None or ms <= 0:
        return 0
    lims = (400, 800, 1500) if method in ("get", "head") else (120, 250, 500)
    return 4 if ms <= lims[0] else 3 if ms <= lims[1] else 2 if ms <= lims[2] else 1


def ping_badge(entry, display):
    """'' — не проверялся; иначе префикс к названию сервера."""
    if not entry:
        return ""
    ms, method = entry.get("ms"), entry.get("m", "tcp")
    if ms is None:
        return ""
    if display == "dots":
        return "🟢" if ms > 0 else "🔴"
    if ms <= 0:
        return "✕"
    bars = _BARS.get(ping_level(ms, method), "")
    if display == "bars":
        return bars
    if display == "both":
        return f"{bars} {ms} {T('ms')}"
    return f"{ms} {T('ms')}"


# ---- сеть устройства ------------------------------------------------------------
_T_CELLULAR, _T_WIFI, _T_BLUETOOTH, _T_ETHERNET, _T_VPN, _T_WIFI_AWARE, _T_USB = 0, 1, 2, 3, 4, 5, 8


def network_snapshot():
    """{'type': wifi|cellular|wired|other|none, 'vpn': bool, 'handle': int} для сети Telegram."""
    snap = {"type": "none", "vpn": False, "handle": 0}
    try:
        cm = ApplicationLoader.applicationContext.getSystemService("connectivity")
        net = cm.getActiveNetwork() if cm is not None else None
        if net is None:
            return snap
        try:
            snap["handle"] = int(net.getNetworkHandle())
        except Exception:
            snap["handle"] = hash(str(net))
        caps = cm.getNetworkCapabilities(net)
        if caps is None:
            snap["type"] = "other"
            return snap

        def has(c, t):
            try:
                return bool(c.hasTransport(int(t)))
            except Exception:
                return False
        snap["vpn"] = has(caps, _T_VPN)
        if has(caps, _T_WIFI) or has(caps, _T_WIFI_AWARE):
            snap["type"] = "wifi"
        elif has(caps, _T_CELLULAR):
            snap["type"] = "cellular"
        elif has(caps, _T_ETHERNET) or has(caps, _T_USB) or has(caps, _T_BLUETOOTH):
            snap["type"] = "wired"
        else:
            snap["type"] = "other"
            if snap["vpn"]:
                for n in _jlist(cm.getAllNetworks()):
                    c = cm.getNetworkCapabilities(n)
                    if c is None or has(c, _T_VPN):
                        continue
                    if has(c, _T_WIFI):
                        snap["type"] = "wifi"
                        break
                    if has(c, _T_CELLULAR):
                        snap["type"] = "cellular"
                        break
    except Exception:
        pass
    return snap


def network_label(snap):
    return T({"wifi": "net_wifi", "cellular": "net_mobile", "wired": "net_wired",
              "none": "net_none"}.get(snap.get("type"), "net_other"))
