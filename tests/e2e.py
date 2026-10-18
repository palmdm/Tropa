"""Local proxy servers (desktop sing-box) and an HTTP target for end-to-end tests."""
import base64
import json
import os
import socket
import struct
import subprocess
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import harness as H


def free_ports(n):
    socks, ports = [], []
    for _ in range(n):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        socks.append(s)
        ports.append(s.getsockname()[1])
    for s in socks:
        s.close()
    return ports


class _Target(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(204)
        self.end_headers()

    def do_HEAD(self):
        self.send_response(204)
        self.end_headers()

    def log_message(self, *a):
        pass


def start_http():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Target)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv.server_address[1]


class Servers:
    """sing-box server with vless/trojan/ss/vmess/hy2/tuic inbounds on 127.0.0.1."""

    def __init__(self):
        d = os.path.join(H.WORK, "server")
        os.makedirs(d, exist_ok=True)
        self.cert, self.key = os.path.join(d, "cert.pem"), os.path.join(d, "key.pem")
        subprocess.run(["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
                        "-nodes", "-keyout", self.key, "-out", self.cert, "-days", "2", "-subj", "/CN=localhost",
                        "-addext", "subjectAltName=DNS:localhost"], check=True, capture_output=True)
        self.uuid, self.pw, self.obfs = str(uuid.uuid4()), "pw-" + uuid.uuid4().hex[:12], "ob-" + uuid.uuid4().hex[:8]
        p = free_ports(8)
        self.ports = dict(zip(("vless", "vless_tls", "trojan", "ss", "vmess", "hy2", "hy2_obfs", "tuic"), p))
        tls = {"enabled": True, "server_name": "localhost", "certificate_path": self.cert, "key_path": self.key}
        quic_tls = dict(tls, alpn=["h3"])
        cfg = {"log": {"level": "warn"}, "inbounds": [
            {"type": "vless", "tag": "a", "listen": "127.0.0.1", "listen_port": p[0], "users": [{"uuid": self.uuid}]},
            {"type": "vless", "tag": "b", "listen": "127.0.0.1", "listen_port": p[1], "users": [{"uuid": self.uuid}], "tls": tls},
            {"type": "trojan", "tag": "c", "listen": "127.0.0.1", "listen_port": p[2], "users": [{"password": self.pw}], "tls": tls},
            {"type": "shadowsocks", "tag": "d", "listen": "127.0.0.1", "listen_port": p[3], "method": "aes-128-gcm", "password": self.pw},
            {"type": "vmess", "tag": "e", "listen": "127.0.0.1", "listen_port": p[4], "users": [{"uuid": self.uuid, "alterId": 0}],
             "transport": {"type": "ws", "path": "/ws"}},
            {"type": "hysteria2", "tag": "f", "listen": "127.0.0.1", "listen_port": p[5], "users": [{"password": self.pw}], "tls": quic_tls},
            {"type": "hysteria2", "tag": "g", "listen": "127.0.0.1", "listen_port": p[6], "users": [{"password": self.pw}],
             "obfs": {"type": "salamander", "password": self.obfs}, "tls": quic_tls},
            {"type": "tuic", "tag": "h", "listen": "127.0.0.1", "listen_port": p[7], "users": [{"uuid": self.uuid, "password": self.pw}],
             "congestion_control": "bbr", "tls": quic_tls},
        ], "outbounds": [{"type": "direct", "tag": "direct"}]}
        path = os.path.join(d, "server.json")
        json.dump(cfg, open(path, "w"))
        self.proc = subprocess.Popen([H.SING_BOX, "run", "-c", path], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        deadline = time.time() + 8
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(self.proc.stderr.read().decode())
            try:
                socket.create_connection(("127.0.0.1", p[0]), 0.2).close()
                break
            except OSError:
                time.sleep(0.1)
        time.sleep(0.3)

    def links(self):
        P, u, pw = self.ports, self.uuid, self.pw
        ss = base64.urlsafe_b64encode(f"aes-128-gcm:{pw}".encode()).decode().rstrip("=")
        vm = base64.b64encode(json.dumps({"v": "2", "ps": "vmess-ws", "add": "127.0.0.1", "port": str(P["vmess"]), "id": u,
                                          "aid": "0", "net": "ws", "path": "/ws", "tls": ""}).encode()).decode()
        return {
            "vless": f"vless://{u}@127.0.0.1:{P['vless']}?type=tcp&security=none#vless-plain",
            "vless_tls": f"vless://{u}@127.0.0.1:{P['vless_tls']}?type=tcp&security=tls&sni=localhost&allowInsecure=1&fp=chrome#vless-tls",
            "trojan": f"trojan://{pw}@127.0.0.1:{P['trojan']}?security=tls&sni=localhost&allowInsecure=1#trojan",
            "ss": f"ss://{ss}@127.0.0.1:{P['ss']}#shadowsocks",
            "vmess": f"vmess://{vm}",
            "hy2": f"hy2://{pw}@127.0.0.1:{P['hy2']}?sni=localhost&insecure=1&fp=chrome#hy2-fp",
            "hy2_obfs": f"hysteria2://{pw}@127.0.0.1:{P['hy2_obfs']}?sni=localhost&insecure=1&obfs=salamander&obfs-password={self.obfs}#hy2-obfs",
            "tuic": f"tuic://{u}:{pw}@127.0.0.1:{P['tuic']}?sni=localhost&insecure=1&congestion_control=bbr&alpn=h3&fp=chrome#tuic",
        }

    def stop(self):
        try:
            self.proc.kill()
        except Exception:
            pass


def socks_get(port, user, pwd, url_port, path="/generate_204", timeout=8.0):
    """HTTP GET through a SOCKS5 proxy with auth; returns the status code or an error string."""
    try:
        s = socket.create_connection(("127.0.0.1", port), timeout)
        s.sendall(b"\x05\x01\x02")
        if s.recv(2) != b"\x05\x02":
            return "no auth"
        ub, pb = user.encode(), pwd.encode()
        s.sendall(b"\x01" + bytes([len(ub)]) + ub + bytes([len(pb)]) + pb)
        if s.recv(2)[1] != 0:
            return "auth failed"
        s.sendall(b"\x05\x01\x00\x01" + socket.inet_aton("127.0.0.1") + struct.pack("!H", url_port))
        rep = s.recv(10)
        if len(rep) < 2 or rep[1] != 0:
            return f"connect failed {rep!r}"
        s.sendall(f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n".encode())
        data = s.recv(1024)
        s.close()
        return int(data.split()[1])
    except Exception as e:  # noqa: BLE001
        return f"error {e}"
