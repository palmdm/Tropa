"""Core installation: signed downloads happen once, channels/types switch without re-downloading
or restarting, panic fallback, staged updates, tampering is refused, Tropa 0.1 layout migrates."""
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as H  # noqa: E402
import e2e as E  # noqa: E402

os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"
fails = []


def ok(cond, what):
    print(("  ok   " if cond else "  FAIL ") + what)
    if not cond:
        fails.append(what)


cdir = H.core_env()
os.environ["FAKECORE_BIN_xrmodern"] = os.path.join(H.FAKECORE_DIR, "fakexray.py")
m = H.load()

# ---- a signing key and a release server like GitHub's
kdir = os.path.join(H.WORK, "keys")
os.makedirs(kdir, exist_ok=True)
key = os.path.join(kdir, "key.pem")
subprocess.run(["openssl", "ecparam", "-name", "prime256v1", "-genkey", "-noout", "-out", key], check=True)
der = subprocess.run(["openssl", "ec", "-in", key, "-pubout", "-outform", "DER"], capture_output=True, check=True).stdout
pub = (int.from_bytes(der[-64:-32], "big"), int.from_bytes(der[-32:], "big"))
m.ecdsa_verify.__defaults__ = (pub,)
m._elf_ok = lambda p: open(p, "rb").read(4) == b"\x7fELF"


def sign(data):
    p = os.path.join(kdir, "m.json")
    open(p, "wb").write(data)
    return subprocess.run(["openssl", "dgst", "-sha256", "-sign", key, p], capture_output=True, check=True).stdout


files, hits = {}, []
releases = []


def publish(core, tag, src, upstream):
    fam = m.CORE_FAMILIES[core]
    blob = open(H.padded_core(src, os.path.join(kdir, f"{tag}.so")), "rb").read()
    man = {"schema": 3, "coreApi": 2, "configContract": 1, "family": fam["family"], "releaseTag": tag,
           "upstream": {"tag": upstream}, "minAndroidApi": 29, "requiredExports": ["StartCore", "StopCore"],
           "assets": {"arm64-v8a": {"name": fam["asset"], "size": len(blob), "sha256": hashlib.sha256(blob).hexdigest(),
                                    "exports": ["StartCore", "StopCore"]}}}
    raw = json.dumps(man).encode()
    files[f"/dl/{tag}/manifest.json"] = raw
    files[f"/dl/{tag}/manifest.json.sig"] = sign(raw)
    files[f"/dl/{tag}/{fam['asset']}"] = blob
    releases.insert(0, {"tag_name": tag, "draft": False, "prerelease": False,
                        "assets": [{"name": n} for n in ("manifest.json", "manifest.json.sig", fam["asset"])]})


class Srv(BaseHTTPRequestHandler):
    def do_GET(self):
        hits.append(self.path)
        if self.path == "/api/releases":
            body = json.dumps(releases).encode()
        elif self.path in files:
            body = files[self.path]
        else:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


httpd = ThreadingHTTPServer(("127.0.0.1", 0), Srv)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{httpd.server_address[1]}"
m.CORE_RELEASES_API = base + "/api/releases"
m.CORE_DL_BASE = base + "/dl"
m.CORE_PINNED = {"singbox": "sb-v1.13.20-w4079", "xray": "xray-v26.7.28-w10110"}
m.LEGACY_CORE_URLS = {"singbox": [base + "/legacy/sb.so"], "xray": [base + "/legacy/xr.so"]}
files["/legacy/sb.so"] = open(H.padded_core("libsb-legacy.so", os.path.join(kdir, "legacy-sb.so")), "rb").read()
files["/legacy/xr.so"] = open(H.padded_core("libxr-legacy.so", os.path.join(kdir, "legacy-xr.so")), "rb").read()
publish("singbox", "sb-v1.13.20-w4079", "libsb-modern.so", "v1.13.20")
publish("xray", "xray-v26.7.28-w10110", "libxr-modern.so", "v26.7.28")

srv = E.Servers()
http_port = E.start_http()
links = srv.links()
store = {"elix": {"nodes": [{"uri": links["vless"]}, {"uri": links["hy2"]}], "info": {}, "updated": int(time.time())},
         "own": {"subs": [], "keys": []}, "active": {"elix": "", "own": ""}, "pings": {}, "clip_seen": ""}
H.SETTINGS["store"] = json.dumps(json.dumps(store))
H.SETTINGS["core_check_ts"] = json.dumps(int(time.time()))


def downloads():
    return [h for h in hits if h.endswith(".so")]


def session_ok(P):
    s = P._session
    return s is not None and E.socks_get(s["port"], s["user"], s["pwd"], http_port) == 204


def new_process():
    """Telegram restart: fresh process state, SharedConfig re-read from preferences."""
    sys.modules.pop("_tropa_core_process_v2", None)
    H.SharedConfig.restart()


def boot():
    P = m.TropaPlugin()
    P.on_plugin_load()
    return P


def connect(P, why="test"):
    P.connect(why)
    return P._state


def restart_boot(P, timeout=30):
    """Один тап «Перезапустить» + запуск заново."""
    P.on_plugin_unload()
    new_process()
    P2 = boot()
    H.wait_for(lambda: P2._state in ("on", "error", "restart"), timeout)
    return P2


print("A) first connect downloads the signed core once")
H.SETTINGS["enabled"] = json.dumps(True)
P = boot()
H.wait_for(lambda: P._state in ("on", "error"), 40)
ok(P._state == "on" and session_ok(P), f"connected ({P._state}: {P._state_detail})")
ok(downloads() == ["/dl/sb-v1.13.20-w4079/libexitfy-sb-arm64-v8a.so"], f"one download: {downloads()}")
ok(os.path.exists(os.path.join(H.FILES, "app_tropa", "cores", "singbox-modern.so")), "stored as singbox-modern.so")

print("B) restart: nothing is downloaded again")
P.on_plugin_unload()
new_process()
n = len(downloads())
P = boot()
H.wait_for(lambda: P._state in ("on", "error"), 30)
ok(P._state == "on" and session_ok(P), f"connected after restart ({P._state})")
ok(len(downloads()) == n, f"no new downloads: {downloads()[n:]}")

print("C) legacy on: restart offered, downloaded at the restart, then files re-used")
P._on_core_legacy(True)
H.wait_for(lambda: P._state == "restart", 15)
ok(P._state == "restart", "enabling legacy asks for a restart (different .so)")
ok(downloads()[n:] == [], f"nothing downloaded until the core is actually needed: {downloads()[n:]}")
P = restart_boot(P)
ok(P._state == "on" and P._session["channel"] == "legacy" and session_ok(P), f"legacy after restart ({P._state}: {P._state_detail})")
ok(downloads()[n:] == ["/legacy/sb.so"], f"legacy downloaded once, at the restart: {downloads()[n:]}")
n = len(downloads())
P._on_core_legacy(False)
H.wait_for(lambda: P._state == "restart", 15)
P = restart_boot(P)
ok(P._state == "on" and P._session["channel"] == "modern" and session_ok(P), "back to the new core after a restart")
ok(len(downloads()) == n, f"modern re-used, no download: {downloads()[n:]}")

print("D) Xray: restart to switch, downloaded once, files re-used both ways")
P._select(P._unique(P._entries())[0][0])           # vless works with Xray
H.wait_for(lambda: P._state == "on", 20)
P._on_core_type(1)
H.wait_for(lambda: P._state == "restart", 15)
ok(P._state == "restart", "switching to Xray asks for a restart")
P = restart_boot(P)
ok(P._state == "on" and P._session["core"] == "xray" and session_ok(P), f"Xray after restart ({P._state}: {P._state_detail})")
ok(downloads()[n:] == ["/dl/xray-v26.7.28-w10110/libxray-arm64-v8a.so"], f"Xray downloaded once: {downloads()[n:]}")
n = len(downloads())
P._on_core_type(0)
H.wait_for(lambda: P._state == "restart", 15)
P = restart_boot(P)
ok(P._state == "on" and P._session["core"] == "singbox" and session_ok(P) and len(downloads()) == n,
   "back on sing-box after a restart, no new downloads")

print("E) the new core panics: restart offered, legacy on next launch, no download")
open(os.path.join(cdir, "sbmodern.panic"), "w").close()
connect(P, "panic")
ok(P._state == "restart", f"panic offers a restart ({P._state}: {P._state_detail})")
ok(len(P.cores.runtime.loaded()) == 1 and P.cores.runtime.loaded()[0]["channel"] == "modern",
   "legacy not loaded into the same process")
P = restart_boot(P)
ok(P._state == "on" and P._session["channel"] == "legacy" and session_ok(P), f"legacy after restart ({P._state}: {P._state_detail})")
ok(len(downloads()) == n, "fallback needed no download (legacy already on the device)")
os.remove(os.path.join(cdir, "sbmodern.panic"))
P.cores.clear_modern_bad("singbox")
P = restart_boot(P)
ok(P._state == "on" and P._session["channel"] == "modern", "new core used again after clearing the mark and restarting")
n = len(downloads())

print("F) a newer signed build: staged while the old one is loaded, applied after restart")
publish("singbox", "sb-v1.13.21-w4100", "libsb-modern2.so", "v1.13.21")
msg = P.cores.check_updates("singbox", force=True)
ok(m.T("core_staged", name="").split("{")[0][:10] in msg or "перезапуск" in msg, f"staged: {msg}")
ok(downloads()[n:] == ["/dl/sb-v1.13.21-w4100/libexitfy-sb-arm64-v8a.so"], f"update downloaded once: {downloads()[n:]}")
n = len(downloads())
P.on_plugin_unload()
new_process()
P = boot()
H.wait_for(lambda: P._state in ("on", "error"), 30)
info = P.cores.meta("singbox", "modern")
ok(info and info.get("tag") == "sb-v1.13.21-w4100", f"update applied: {info and info.get('tag')}")
ok(P.cores.modern_bad("singbox") is None, "the new build gets a fresh chance")
ok(P._state == "on" and P._session["channel"] == "modern" and session_ok(P), f"connected on the new build ({P._state}: {P._state_detail})")
ok(len(downloads()) == n, "nothing downloaded at restart")
P.on_plugin_unload()

print("G) tampered releases are refused")
publish("xray", "xray-v26.8.1-w10200", "libxr-modern.so", "v26.8.1")
files["/dl/xray-v26.8.1-w10200/manifest.json.sig"] = sign(b"something else")
man, err = m.fetch_core_manifest("xray", "xray-v26.8.1-w10200")
ok(man is None and "signature" in err, f"bad signature refused: {err}")
dest = os.path.join(H.WORK, "x1.so")
info = P.cores._download("xray", "modern", dest)
ok(info is not None and info["tag"] == m.CORE_PINNED["xray"], f"a bad latest release falls back to the pinned one: {info and info['tag']}")
publish("xray", "xray-v26.8.2-w10201", "libxr-modern.so", "v26.8.2")
good = files["/dl/xray-v26.8.2-w10201/libxray-arm64-v8a.so"]
files["/dl/xray-v26.8.2-w10201/libxray-arm64-v8a.so"] = good[:-10] + b"x" * 10
man, err = m.fetch_core_manifest("xray", "xray-v26.8.2-w10201")
dest2 = os.path.join(H.WORK, "x2.so")
ok(man is not None and m.download_file([man["url"]], dest2, man["sha256"], man["size"]) is None, "hash mismatch refused")
ok(not os.path.exists(dest2) and not os.path.exists(dest2 + ".part"), "nothing left behind")
files["/legacy/xr.so"] = b"<html>not a library</html>" * 50000
ok(m.download_file(m.LEGACY_CORE_URLS["xray"], dest2) is None and not os.path.exists(dest2), "non-ELF legacy file refused")

print("H) Tropa 0.1 layout is migrated, not re-downloaded")
saved = dict(H.SETTINGS)
cores_dir = os.path.join(H.FILES, "app_tropa", "cores")
for f in os.listdir(cores_dir):
    os.remove(os.path.join(cores_dir, f))
H.SETTINGS.pop("core_meta2", None)
H.SETTINGS.pop("core_next", None)
p = H.padded_core("libsb-modern.so", os.path.join(cores_dir, "singbox.so"))
old = {"singbox": {"channel": "modern", "tag": "sb-v1.13.20-w4079", "version": "1.13.20",
                   "sha256": hashlib.sha256(open(p, "rb").read()).hexdigest(), "api": 2}}
H.SETTINGS["core_meta"] = json.dumps(json.dumps(old))
new_process()
n = len(downloads())
P = boot()
H.wait_for(lambda: P._state in ("on", "error"), 30)
ok(os.path.exists(os.path.join(cores_dir, "singbox-modern.so")) and not os.path.exists(p), "file moved to the new name")
ok(P.cores.meta("singbox", "modern") is not None and H.SETTINGS.get("core_meta") in ('""', None), "metadata migrated")
ok(len(downloads()) == n and P._state == "on", f"connected without downloading ({P._state}: {P._state_detail})")
P.on_plugin_unload()

print("I) background updates wait for a non-metered network")
H.CONTEXT.cm.metered = True
H.SETTINGS["core_check_ts"] = json.dumps(0)
publish("singbox", "sb-v1.13.22-w4200", "libsb-modern.so", "v1.13.22")
n = len(downloads())
msg = P.cores.check_updates("singbox")
ok(len(downloads()) == n and msg == m.T("core_metered"), f"no download on metered network: {msg}")
H.CONTEXT.cm.metered = False

srv.stop()
httpd.shutdown()
print("FAILS:", fails if fails else "none")
os._exit(1 if fails else 0)
