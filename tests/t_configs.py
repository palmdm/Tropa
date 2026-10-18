"""Configs that Tropa gives the cores: checked by real sing-box builds (1.13.19 with uTLS, 1.13.20)."""
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as H  # noqa: E402

m = H.load()
FAKEXRAY = os.path.join(H.FAKECORE_DIR, "fakexray.py")
SING_BOX_114 = os.environ.get("SING_BOX_114", "/home/claude/bin/sing-box-1.13.14")
fails = []


def check(binary, cfg):
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(cfg, f)
    r = subprocess.run([binary, "check", "-c", f.name], capture_output=True, text=True, timeout=60)
    os.unlink(f.name)
    return r.returncode == 0, " ".join((r.stdout + r.stderr).split())[-300:]


def has_utls(ob):
    return "utls" in (ob.get("tls") or {})


links = {
    "vless-reality": "vless://11111111-2222-3333-4444-555555555555@example.com:443?type=tcp&security=reality&pbk=Aw0gYxk8Wz3XvyNN4SDZK3Tj6M1L8pYlJXCtWMrqU0E&sid=ab12&sni=www.microsoft.com&fp=chrome&flow=xtls-rprx-vision#reality",
    "vless-ws-tls": "vless://11111111-2222-3333-4444-555555555555@example.com:443?type=ws&security=tls&path=%2Fws%3Fed%3D2048&host=cdn.example.com&sni=cdn.example.com#ws",
    "vless-grpc": "vless://11111111-2222-3333-4444-555555555555@example.com:443?type=grpc&security=tls&serviceName=svc&sni=example.com#grpc",
    "vless-none": "vless://11111111-2222-3333-4444-555555555555@1.2.3.4:8080?type=tcp&security=none#plain",
    "trojan": "trojan://secret@example.com:443?sni=example.com#trojan",
    "ss": "ss://YWVzLTI1Ni1nY206cGFzcw@1.2.3.4:8388#ss",
    "ss2022": "ss://2022-blake3-aes-128-gcm:YctPZ6U7xPPcU%2Bgp3u%2BTmw%3D%3D@1.2.3.4:8388#ss2022",
    "vmess": "vmess://eyJ2IjoiMiIsInBzIjoidm0iLCJhZGQiOiJleGFtcGxlLmNvbSIsInBvcnQiOiI0NDMiLCJpZCI6IjExMTExMTExLTIyMjItMzMzMy00NDQ0LTU1NTU1NTU1NTU1NSIsImFpZCI6IjAiLCJuZXQiOiJ3cyIsInBhdGgiOiIvd3MiLCJ0bHMiOiJ0bHMiLCJzbmkiOiJleGFtcGxlLmNvbSJ9",
    "hy2-fp": "hy2://pass@example.com:443?sni=example.com&fp=chrome&insecure=0#hy2",
    "hy2-obfs": "hysteria2://pass@example.com:8443?sni=example.com&obfs=salamander&obfs-password=xyz#hy2obfs",
    "tuic-fp": "tuic://11111111-2222-3333-4444-555555555555:pass@example.com:443?sni=example.com&congestion_control=bbr&alpn=h3&fp=chrome#tuic",
}

nodes = {k: m.parse_link(v) for k, v in links.items()}
for k, n in nodes.items():
    if n is None:
        fails.append(f"parse {k}")

# 1) single-server configs
for k, n in nodes.items():
    cfg = m.build_main_config(m.CORE_SINGBOX, [n], 23456, "tropa_user0001", "p" * 24)
    ob = cfg["outbounds"][0]
    if cfg["log"] != {"level": "panic"}:
        fails.append(f"{k}: log is {cfg['log']}")
    if [o["tag"] for o in cfg["outbounds"]] != ["proxy"]:
        fails.append(f"{k}: outbounds {[o['tag'] for o in cfg['outbounds']]}")
    if n["proto"] in ("hy2", "tuic") and has_utls(ob):
        fails.append(f"{k}: uTLS in a QUIC outbound")
    ok, out = check(H.SING_BOX, cfg)
    if not ok:
        fails.append(f"{k} (1.13.19): {out}")
    if not has_utls(ob):
        for label, binary in (("1.13.20", H.SING_BOX_120), ("1.13.14 legacy", SING_BOX_114)):
            ok, out = check(binary, cfg)
            if not ok:
                fails.append(f"{k} ({label}): {out}")
    print(f"sing-box {k:14} {'ok' if ok else 'FAIL'}")

# 2) auto-best (urltest) and test configs
alln = list(nodes.values())
cfg = m.build_main_config(m.CORE_SINGBOX, alln, 23456, "tropa_user0001", "p" * 24, auto_url="https://www.gstatic.com/generate_204")
ok, out = check(H.SING_BOX, cfg)
print("urltest", "ok" if ok else out)
quic_only = [n for n in alln if n["proto"] in ("hy2", "tuic")]
for label, binary in (("1.13.20", H.SING_BOX_120), ("1.13.14 legacy", SING_BOX_114)):
    qcfg = m.build_main_config(m.CORE_SINGBOX, quic_only, 23456, "tropa_user0001", "p" * 24, auto_url="https://cp.cloudflare.com/generate_204")
    ok2, out2 = check(binary, qcfg)
    print("urltest hy2/tuic", label, "ok" if ok2 else out2)
    if not ok2:
        fails.append(f"urltest hy2/tuic {label}: {out2}")
if not ok:
    fails.append("urltest: " + out)
pairs = [(i, 30000 + i, n) for i, n in enumerate(alln)]
for name, base in (("standalone", None), ("merged", cfg)):
    tcfg = m.add_test_pairs(m.CORE_SINGBOX, base, pairs, "tropat_x", "y" * 20)
    ok, out = check(H.SING_BOX, tcfg)
    print("test config", name, "ok" if ok else out)
    if not ok:
        fails.append(f"test config {name}: {out}")
    if name == "standalone" and tcfg["route"].get("final") != "t-out-0":
        fails.append(f"standalone final {tcfg['route'].get('final')}")

# 3) Xray shapes (validated by the fake's structural check)
xnodes = [n for n in alln if m.node_supported(m.CORE_XRAY, n)]
print("xray-supported:", len(xnodes), "of", len(alln))
for n in xnodes:
    cfg = m.build_main_config(m.CORE_XRAY, [n], 23456, "tropa_user0001", "p" * 24)
    ok, out = check(FAKEXRAY, cfg)
    if not ok:
        fails.append(f"xray {n['name']}: {out}")
for name, base in (("standalone", None), ("merged", m.build_main_config(m.CORE_XRAY, xnodes[:1], 23456, "u" * 10, "p" * 20))):
    ok, out = check(FAKEXRAY, m.add_test_pairs(m.CORE_XRAY, base, [(i, 31000 + i, n) for i, n in enumerate(xnodes)], "a" * 8, "b" * 20))
    if not ok:
        fails.append(f"xray test {name}: {out}")
if any(m.node_supported(m.CORE_XRAY, nodes[k]) for k in ("hy2-fp", "tuic-fp")):
    fails.append("xray claims hy2/tuic support")

print("FAILS:", fails if fails else "none")
sys.exit(1 if fails else 0)
