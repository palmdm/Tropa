"""End-to-end: Telegram proxy entry, connections through every protocol, quick test,
hot core switching, modern-core panic fallback, restart persistence, copyable errors."""
import hashlib
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as H  # noqa: E402
import e2e as E  # noqa: E402

fails = []


def ok(cond, what):
    print(("  ok   " if cond else "  FAIL ") + what)
    if not cond:
        fails.append(what)


cdir = H.core_env()
os.environ["FAKECORE_BIN_xrmodern"] = os.path.join(H.FAKECORE_DIR, "fakexray.py")
os.environ["FAKECORE_BIN_xrlegacy"] = os.path.join(H.FAKECORE_DIR, "fakexray.py")
m = H.load()

# ---- cores already on the device (no network in this test)
cores_dir = os.path.join(H.FILES, "app_tropa", "cores")
os.makedirs(cores_dir, exist_ok=True)
meta = {}
for core, ch, src, tag, api in (("singbox", "modern", "libsb-modern.so", "sb-v1.13.20-w4079", 2),
                                ("singbox", "legacy", "libsb-legacy.so", "", 1),
                                ("xray", "modern", "libxr-modern.so", "xray-v26.7.28-w10110", 2)):
    p = H.padded_core(src, os.path.join(cores_dir, f"{core}-{ch}.so"))
    meta[f"{core}:{ch}"] = {"core": core, "channel": ch, "tag": tag, "version": tag.split("-v")[-1].split("-w")[0] if tag else "",
                            "sha256": hashlib.sha256(open(p, "rb").read()).hexdigest(), "api": api,
                            "size": os.path.getsize(p)}
H.SETTINGS["core_meta2"] = json.dumps(json.dumps(meta))
net_calls = []
m.requests.get = lambda *a, **k: net_calls.append(a[0]) or (_ for _ in ()).throw(RuntimeError("network disabled in test"))

srv = E.Servers()
http_port = E.start_http()
links = srv.links()
store = {"elix": {"nodes": [{"uri": u} for u in links.values()], "info": {}, "updated": int(time.time())},
         "own": {"subs": [], "keys": []}, "active": {"elix": "", "own": ""}, "pings": {}, "clip_seen": ""}
H.SETTINGS["store"] = json.dumps(json.dumps(store))
H.SETTINGS["core_check_ts"] = json.dumps(int(time.time()))      # no update check in this test

# ---- Telegram state before Tropa: the user's own proxy + leftovers of Tropa 0.1
SC = H.SharedConfig


def ui(fn):
    box = {}
    H.UI.post(lambda: box.setdefault("v", fn()))
    H.UI.flush()
    return box.get("v")


user_proxy = H.ProxyInfo("10.0.0.1", 1080, "me", "mypass", "")
ui(lambda: SC.setCurrentProxy(SC.addProxy(user_proxy)))
for i in range(4):
    ui(lambda i=i: SC.addProxy(H.ProxyInfo("127.0.0.1", 40000 + i, f"tropa_old{i}xxxxxx", f"oldpass{i}" * 3, "")))
print("before:", [(p.address, p.port) for p in SC.entries()])


def ours():
    return [p for p in SC.entries() if p.address == "127.0.0.1" and p.username.startswith("tropa_")]


def keys():
    return {n["name"]: k for k, n in P._unique(P._entries())}


def wait_state(*states, timeout=25):
    H.wait_for(lambda: P._state in states, timeout)
    return P._state


def session_ok():
    s = P._session
    return s is not None and E.socks_get(s["port"], s["user"], s["pwd"], http_port) == 204


P = m.TropaPlugin()
P.on_plugin_load()
H.wait_for(lambda: len(ours()) == 0, 5)
print("1) startup while disabled")
ok(len(ours()) == 0, "stale Tropa 0.1 entries removed at startup")
ok(SC.currentProxy is not None and SC.currentProxy.address == "10.0.0.1" and SC.isProxyEnabled(), "user's proxy untouched")

print("2) enable")
P._on_enable(True)
st = wait_state("on", "error")
ok(st == "on", f"connected (state={st}, detail={P._state_detail})")
ok(len(ours()) == 1, f"exactly one Tropa entry ({len(ours())})")
ok(SC.currentProxy is not None and SC.currentProxy.username.startswith("tropa_") and SC.isProxyEnabled(), "Tropa entry is current and enabled")
ok(any(p.address == "10.0.0.1" for p in SC.entries()), "user's proxy kept in the list")
ok(session_ok(), "traffic through the local port")
port0, user0 = P._session["port"], P._session["user"]

print("3) every server, one by one")
for name, k in keys().items():
    P._select(k)
    time.sleep(0.3)
    st = wait_state("on", "error")
    good = st == "on" and session_ok()
    ok(good, f"{name}: state={st} {P._state_detail if st != 'on' else ''}".strip())
    ok(len(ours()) == 1 and P._session and P._session["port"] == port0 and P._session["user"] == user0,
       f"{name}: still one entry on port {port0}")
ok(not H.UI_VIOLATIONS, f"Telegram proxy list changed only on the UI thread {H.UI_VIOLATIONS[:3]}")

print("4) quick test, TCP")
P._set_choice("ping_method", 0)
P.start_quick_test()
H.wait_for(lambda: not P._testing, 60)
res = {n["name"]: (P._ping(k) or {}) for k, n in P._unique(P._entries())}
ok(all((r.get("ms") or 0) > 0 for r in res.values()), f"all answered: { {k: (v.get('ms'), v.get('m')) for k, v in res.items()} }")
ok(res["hy2-fp"].get("m") == "icmp" and res["tuic"].get("m") == "icmp", "Hysteria2/TUIC checked (ICMP fallback), not skipped")
row = P._test_row().subtext
ok("TCP" in row and "8" in row, f"button shows method and result: {row}")
P._set_choice("ping_method", 1)
row2 = P._test_row().subtext
ok("HTTP GET" in row2 and "из" not in row2, f"button text follows the new method: {row2}")

print("5) quick test, HTTP GET through the core (Telegram stays connected)")
P.set_setting("ping_url", f"http://127.0.0.1:{http_port}/generate_204")
P.start_quick_test()
H.wait_for(lambda: not P._testing, 90)
res = {n["name"]: (P._ping(k) or {}) for k, n in P._unique(P._entries())}
ok(all((r.get("ms") or 0) > 0 and r.get("m") == "get" for r in res.values()),
   f"real delay for all: { {k: (v.get('ms'), v.get('m')) for k, v in res.items()} }")
ok(session_ok() and len(ours()) == 1, "session restored after the test")

def do_restart(timeout=30):
    """Один тап «Перезапустить»: свежий процесс, Telegram перечитывает прокси, плагин загружается заново."""
    global P
    P.on_plugin_unload()
    sys.modules.pop("_tropa_core_process_v2", None)
    SC.restart()
    P = m.TropaPlugin()
    P.on_plugin_load()
    return wait_state("on", "error", "restart", timeout=timeout)


def tap_restart():
    """Найти действие перезапуска в настройках и «нажать» его; вернуть True, если перезапуск запрошен."""
    before = H.RESTARTS[0]
    row = [it for it in P.create_settings()
           if isinstance(it, H.Text) and it.text == m.T("restart_now")]
    if row and callable(row[0].on_click):
        row[0].on_click(None)
        H.UI.flush()
    return H.RESTARTS[0] > before


print("6) switch core type: one-tap restart, then Xray (never two Go cores in one process)")
P._select(keys()["vless-plain"])
wait_state("on", "error")
P._on_core_type(1)
H.wait_for(lambda: P._state == "restart", 10)
ok(P._state == "restart" and P._pending_restart, f"switching to Xray asks for a restart ({P._state})")
ok(len(P.cores.runtime.loaded()) == 1 and P.cores.runtime.loaded()[0]["core"] == "singbox",
   "the second core is NOT loaded into the process")
ok(tap_restart(), "the restart action is offered and triggers a restart")
st = do_restart()
ok(st == "on" and P._session and P._session["core"] == "xray" and session_ok(), f"came up on Xray ({st}: {P._state_detail})")
ok(len(P.cores.runtime.loaded()) == 1 and P.cores.runtime.loaded()[0]["core"] == "xray", "only Xray loaded now")
P._on_core_type(0)
H.wait_for(lambda: P._state == "restart", 10)
ok(P._state == "restart", "switching back to sing-box also asks for a restart")
tap_restart()
st = do_restart()
ok(st == "on" and P._session["core"] == "singbox" and session_ok(), "back on sing-box after the restart")

print("7) a Hysteria2 server while Xray is selected -> sing-box is chosen (via restart)")
H.SETTINGS["core_type"] = json.dumps(1)      # pretend Xray was selected
before = len(H.BULLETINS)
P._select(keys()["hy2-fp"])
H.wait_for(lambda: P._state in ("restart", "on", "error"), 15)
ok(P._core() == "singbox", "core auto-switched to sing-box for the hy2 server")
ok(any("sing-box" in str(t) for _k, t in H.BULLETINS[before:]), "user was told why the core changed")
ok(P._state == "on" and session_ok(), f"sing-box already loaded, so no restart needed ({P._state})")
labels = [it.text for it in P.create_settings() if isinstance(it, H.Text)]
ok(sum(1 for t in labels if "hy2" in t or "tuic" in t) == 3, f"Hysteria2/TUIC servers always listed: {labels}")
H.SETTINGS["core_type"] = json.dumps(1)
labels = [it.text for it in P.create_settings() if isinstance(it, H.Text)]
ok(sum(1 for t in labels if ("hy2" in t or "tuic" in t) and "только sing-box" in t) == 3, "with Xray selected they are marked “только sing-box”")
H.SETTINGS["core_type"] = json.dumps(0)
P._select(keys()["vless-plain"])
do_restart()

print("8) the new core panics -> offer restart onto legacy; probe recorded; no second core loaded")
calls_log = os.path.join(cdir, "sbmodern-calls.log")
open(os.path.join(cdir, "sbmodern.panic"), "w").close()
before = len(H.BULLETINS)
P.connect("test-panic")
ok(P._state == "restart" and P._pending_restart, f"panic asks for a restart onto legacy ({P._state}: {P._state_detail})")
ok(len(P.cores.runtime.loaded()) == 1 and P.cores.runtime.loaded()[0]["channel"] == "modern",
   "legacy was NOT loaded into the same process after the panic")
ok(P.cores.modern_bad("singbox") is not None, "modern sing-box marked as failing")
bad = P.cores.modern_bad("singbox") or {}
ok(len(bad.get("probe") or []) == 4 and all("panic" in x for x in bad["probe"]), f"probe recorded: {bad.get('probe')}")
ok("panic" in str((P._last_error() or {}).get("full")), "panic text saved for the report")
ok(tap_restart(), "restart action offered")
st = do_restart()
ok(st == "on" and P._session["channel"] == "legacy" and session_ok(), f"came up on legacy ({st}: {P._state_detail})")
ok(sum(1 for _ in open(calls_log)) >= 1, "modern was tried once (before the restart)")
n_modern = sum(1 for _ in open(calls_log))
P.connect("again")
ok(P._state == "on" and P._session["channel"] == "legacy", "stays on legacy")
ok(sum(1 for _ in open(calls_log)) == n_modern, "the failing core is not started again")
page = H.settings_tree(P._core_page())
ok(any(isinstance(it, H.Text) and it.text == m.T("core_retry_modern") for _d, it in page), "core page offers to retry the new core")
os.remove(os.path.join(cdir, "sbmodern.panic"))
P._retry_modern()
H.wait_for(lambda: P._state == "restart", 10)
ok(P._state == "restart", "retrying the new core asks for a restart (modern not loaded this session)")
tap_restart()
st = do_restart()
ok(st == "on" and P._session["channel"] == "modern" and session_ok(), "restart brings the new core back")

print("8a) the new core panics only on Hysteria2: the probe pinpoints the cause")
P.cores.clear_modern_bad()
open(os.path.join(cdir, "sbmodern.panic_if"), "w").write('"type": "hysteria2"')
P._select(keys()["hy2-fp"])
H.wait_for(lambda: P._state in ("restart", "error"), 25)
probe = (P.cores.modern_bad("singbox") or {}).get("probe") or []
ok([x.split(":")[0] for x in probe] == ["empty", "inbound+direct", "server-outbound", "without-dns"] and
   probe[0].endswith("ok") and probe[1].endswith("ok") and "panic" in probe[2] and "panic" in probe[3],
   f"probe pinpoints the server outbound: {probe}")
ok("probe server-outbound" in P._report(with_log=True), "probe is in the report")
os.remove(os.path.join(cdir, "sbmodern.panic_if"))
P.cores.clear_modern_bad()
tap_restart()
do_restart()
P._select(keys()["vless-plain"])
if P._state == "restart":
    tap_restart(); do_restart()

print("9) when both cores fail: error state; details on tap, copy on long-press")
# make the loaded (modern) core fail AND legacy fail, with modern already marked bad so legacy is chosen
P.cores.mark_modern_bad("singbox", P.cores.meta("singbox", "modern"), "pre-marked")
open(os.path.join(cdir, "sblegacy.fail"), "w").close()
do_restart()                                   # comes up choosing legacy
P.connect("legacy-fails")
ok(P._state == "error", f"error state when legacy fails ({P._state}: {P._state_detail})")
state_row = [it for it in P.create_settings() if isinstance(it, H.Text) and it.text.startswith(m.T("state"))][0]
ok(callable(state_row.on_click) and callable(state_row.on_long_click), "state row: tap and long-press both wired")
H.DIALOGS.clear()
H.COPIED.clear()
state_row.on_click(None)
H.UI.flush()
ok(H.DIALOGS and "permission denied" in (H.DIALOGS[-1]["message"] or ""), "tap shows details with the error")
state_row.on_long_click(None)
H.UI.flush()
ok(H.COPIED and "--- log ---" in H.COPIED[-1], "long-press copies the full report")
ok(not any(s in H.COPIED[-1] for s in (srv.pw, srv.uuid)), "no server secrets in the report")
os.remove(os.path.join(cdir, "sblegacy.fail"))
P.cores.clear_modern_bad()
do_restart()

print("10) disable restores the user's proxy")
P._on_enable(True)
wait_state("on", "error")
P._on_enable(False)
H.wait_for(lambda: len(ours()) == 0 and P._state == "off", 10)
ok(len(ours()) == 0, "Tropa entry removed")
ok(SC.currentProxy is not None and SC.currentProxy.address == "10.0.0.1" and SC.isProxyEnabled(), "user's proxy is current again")

print("11) Telegram restart: same entry, no downloads")
P._on_enable(True)
wait_state("on", "error")
P.on_plugin_unload()
SC.restart()
sys.modules.pop("_tropa_core_process_v2", None)
P = m.TropaPlugin()
P.on_plugin_load()
st = wait_state("on", "error", timeout=30)
ok(st == "on" and session_ok(), f"reconnected after restart ({st}: {P._state_detail})")
ok(len(ours()) == 1 and P._session["port"] == port0 and P._session["user"] == user0, "same single entry, same port and login")
ok(not [u for u in net_calls if "github" in u or ".so" in u], f"no core downloads: {net_calls}")

print("12) left-menu entry opens the plugin settings")
ok("tropa_settings_drawer_menu" in H.MENU_ITEMS, f"drawer item added: {sorted(H.MENU_ITEMS)}")
drawer = H.MENU_ITEMS.get("tropa_settings_drawer_menu")
ok(drawer is not None and drawer.menu_type == H.MenuItemType.DRAWER_MENU and drawer.text == m.T("menu_open"),
   "drawer item is labelled and typed")
H.SETTINGS_OPENED.clear()
drawer.on_click(object())
H.UI.flush()
ok(H.SETTINGS_OPENED and H.SETTINGS_OPENED[-1][0] == "tropa", f"click opens Tropa settings: {H.SETTINGS_OPENED}")
P.on_plugin_unload()
ok("tropa_settings_drawer_menu" not in H.MENU_ITEMS, "menu item removed on unload")

P.on_plugin_unload()
srv.stop()
ok(not H.UI.errors, f"no exceptions on the UI thread {H.UI.errors[:3]}")
ok(not H.UI_VIOLATIONS, f"no proxy changes off the UI thread {H.UI_VIOLATIONS[:3]}")
print("FAILS:", fails if fails else "none")
os._exit(1 if fails else 0)
