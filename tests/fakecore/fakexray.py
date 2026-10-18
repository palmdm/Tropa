#!/usr/bin/env python3
"""Stand-in for Xray in tests: `check -c cfg` validates the Xray JSON shape Tropa produces,
`run -c cfg` serves each socks inbound (user/password auth) and connects directly."""
import json
import socket
import struct
import sys
import threading

KNOWN_OUT = {"vless", "vmess", "trojan", "shadowsocks", "freedom"}


def check(cfg):
    ins, outs = cfg.get("inbounds"), cfg.get("outbounds")
    assert isinstance(ins, list) and isinstance(outs, list) and outs, "inbounds/outbounds missing"
    tags = set()
    for ob in outs:
        assert ob.get("protocol") in KNOWN_OUT, f"unknown outbound protocol {ob.get('protocol')}"
        assert ob.get("tag"), "outbound without tag"
        tags.add(ob["tag"])
        if ob["protocol"] in ("vless", "vmess"):
            assert ob["settings"]["vnext"][0]["users"][0]["id"], "user id missing"
        st = ob.get("streamSettings") or {}
        if st.get("security") == "reality":
            assert st["realitySettings"]["publicKey"], "reality publicKey missing"
    for ib in ins:
        assert ib.get("protocol") == "socks" and int(ib.get("port", 0)) > 0, "bad inbound"
        assert ib["settings"]["auth"] == "password" and ib["settings"]["accounts"], "auth missing"
    for rule in (cfg.get("routing") or {}).get("rules") or []:
        if "outboundTag" in rule:
            assert rule["outboundTag"] in tags, f"rule to unknown outbound {rule['outboundTag']}"


def recv_exact(s, n):
    buf = b""
    while len(buf) < n:
        chunk = s.recv(n - len(buf))
        if not chunk:
            raise OSError("closed")
        buf += chunk
    return buf


def pipe(a, b):
    try:
        while True:
            data = a.recv(65536)
            if not data:
                break
            b.sendall(data)
    except Exception:
        pass
    finally:
        for s in (a, b):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass


def serve_client(c, accounts):
    try:
        ver, n = recv_exact(c, 2)
        methods = recv_exact(c, n)
        if 2 not in methods:
            c.sendall(b"\x05\xff")
            return
        c.sendall(b"\x05\x02")
        recv_exact(c, 1)
        user = recv_exact(c, recv_exact(c, 1)[0]).decode()
        pwd = recv_exact(c, recv_exact(c, 1)[0]).decode()
        if accounts.get(user) != pwd:
            c.sendall(b"\x01\x01")
            return
        c.sendall(b"\x01\x00")
        _v, cmd, _r, atyp = recv_exact(c, 4)
        if atyp == 1:
            host = socket.inet_ntoa(recv_exact(c, 4))
        elif atyp == 3:
            host = recv_exact(c, recv_exact(c, 1)[0]).decode()
        else:
            host = socket.inet_ntop(socket.AF_INET6, recv_exact(c, 16))
        port = struct.unpack("!H", recv_exact(c, 2))[0]
        r = socket.create_connection((host, port), timeout=5)
        c.sendall(b"\x05\x00\x00\x01" + socket.inet_aton("127.0.0.1") + struct.pack("!H", 0))
        threading.Thread(target=pipe, args=(c, r), daemon=True).start()
        pipe(r, c)
    except Exception:
        pass
    finally:
        try:
            c.close()
        except Exception:
            pass


def run(cfg):
    servers = []
    for ib in cfg["inbounds"]:
        accounts = {a["user"]: a["pass"] for a in ib["settings"]["accounts"]}
        s = socket.socket()
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((ib.get("listen", "127.0.0.1"), int(ib["port"])))
        s.listen(64)
        servers.append((s, accounts))

    def accept_loop(s, accounts):
        while True:
            c, _ = s.accept()
            threading.Thread(target=serve_client, args=(c, accounts), daemon=True).start()
    for s, accounts in servers:
        threading.Thread(target=accept_loop, args=(s, accounts), daemon=True).start()
    threading.Event().wait()


def main():
    cmd, path = sys.argv[1], sys.argv[3]
    cfg = json.load(open(path))
    if cmd == "check":
        try:
            check(cfg)
        except Exception as e:  # noqa: BLE001
            print(f"xray config error: {e}", file=sys.stderr)
            sys.exit(1)
        return
    check(cfg)
    run(cfg)


if __name__ == "__main__":
    main()
