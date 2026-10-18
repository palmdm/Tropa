"""Telegram proxy entry edge cases: forks without getters, entries read back after a restart,
the user switching or disabling the proxy, a busy port, the port setting."""
import json
import os
import socket
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as H  # noqa: E402
import e2e as E  # noqa: E402
import setup_env as S  # noqa: E402

fails = []


def ok(cond, what):
    print(("  ok   " if cond else "  FAIL ") + what)
    if not cond:
        fails.append(what)


m = H.load()
SC = H.SharedConfig


class Owner(H.BasePlugin):
    pass


def ui(fn):
    box = {}
    H.UI.post(lambda: box.setdefault("v", fn()))
    H.UI.flush()
    return box.get("v")


def ours():
    return [p for p in SC.entries() if m._is_ours(p)]


print("1) fork whose ProxyInfo has only public fields (no getters)")


class FieldsOnly:
    def __init__(self, address, port, user, password, secret):
        self.address, self.port, self.username, self.password, self.secret = address, port, user, password, secret
        self.settings = H.ProxySettings("SOCKS5", address, port, user, password, secret)


H.CLASSES["org.telegram.messenger.SharedConfig$ProxyInfo"] = FieldsOnly
tg = m.TelegramProxy(Owner())
tg.apply(25000, "tropa_aaaaaaaaaa", "p" * 24)
tg.apply(25000, "tropa_aaaaaaaaaa", "p" * 24)
ok(len(ours()) == 1 and ours()[0].port == 25000, "one entry with public fields only")
tg.apply(25001, "tropa_aaaaaaaaaa", "p" * 24)
ok(len(ours()) == 1 and ours()[0].port == 25001, "port change replaces the entry")
H.CLASSES["org.telegram.messenger.SharedConfig$ProxyInfo"] = H.ProxyInfo
tg.remove()
ok(not ours() and not SC.isProxyEnabled(), "removed, proxy off")

print("2) entries read back from storage after a restart are recognised")
SC.reset()
tg.apply(25002, "tropa_bbbbbbbbbb", "q" * 24)
SC.restart()
ok(len(ours()) == 1 and SC.currentProxy is not None and m._is_ours(SC.currentProxy), "restored entry is ours and current")
tg.apply(25002, "tropa_bbbbbbbbbb", "q" * 24)
ok(len(SC.entries()) == 1, "no duplicate after restart")

print("3) the user picks their own proxy while Tropa is on")
mine = ui(lambda: SC.addProxy(H.ProxyInfo("10.1.1.1", 1080, "u", "p", "")))
ui(lambda: SC.setCurrentProxy(mine))
ok(not tg.is_active(25002, "tropa_bbbbbbbbbb"), "Tropa notices it is no longer current")
tg.remove(restore=True)
ok(SC.currentProxy is mine and SC.isProxyEnabled() and not ours(), "user's choice kept, Tropa entry gone")

print("4) the user turns the proxy off in Telegram")
tg.apply(25003, "tropa_cccccccccc", "r" * 24)
ok(tg.is_active(25003, "tropa_cccccccccc"), "active after apply")
ui(lambda: SC.setProxyEnable(False))
ok(not tg.is_active(25003, "tropa_cccccccccc"), "detected as switched off")
tg.remove(restore=False)

print("5) plugin: watchdog turns Tropa off when the proxy is switched off in Telegram")
SC.reset()
H.SETTINGS.clear()
S.install_fake_cores(m)
S.block_network(m)
srv = E.Servers()
http_port = E.start_http()
links = srv.links()
S.set_store([links["vless"], links["hy2"]])
H.SETTINGS["enabled"] = json.dumps(True)
P = m.TropaPlugin()
P.on_plugin_load()
H.wait_for(lambda: P._state in ("on", "error"), 30)
ok(P._state == "on", f"connected ({P._state}: {P._state_detail})")
ui(lambda: SC.setProxyEnable(False))
H.wait_for(lambda: P._state == "off", 15)
ok(P._state == "off" and P.get_setting("enabled", True) is False, "Tropa switched itself off")
ok(not ours(), "and left no entry behind")

print("6) the saved port is taken by another app")
P._on_enable(True)
H.wait_for(lambda: P._state == "on", 20)
port = P._session["port"]
P._on_enable(False)
H.wait_for(lambda: P._state == "off", 10)
blocker = socket.socket()
blocker.bind(("127.0.0.1", port))
blocker.listen(1)
before = len(H.BULLETINS)
P._on_enable(True)
H.wait_for(lambda: P._state in ("on", "error"), 25)
ok(P._state == "on" and P._session["port"] != port, f"moved to another port ({P._session and P._session['port']} vs {port})")
ok(len(ours()) == 1 and ours()[0].port == P._session["port"], "Telegram entry follows the new port")
H.UI.flush()
ok(any(str(port) in str(t) for _k, t in H.BULLETINS[before:]), "user was told")
s = P._session
ok(E.socks_get(s["port"], s["user"], s["pwd"], http_port) == 204, "traffic works on the new port")
blocker.close()

print("7) port setting")
before = len(H.BULLETINS)
P._on_port_input("80")
H.UI.flush()
ok(H.BULLETINS[before:] and H.BULLETINS[-1][0] == "error", "port below 1024 refused")
P._on_port_input("abc")
H.UI.flush()
ok(H.BULLETINS[-1][0] == "error", "non-number refused")
new_port = E.free_ports(1)[0]
P._on_port_input(str(new_port))
H.wait_for(lambda: P._session and P._session["port"] == new_port and P._state == "on", 25)
ok(P._session and P._session["port"] == new_port, f"reconnected on {new_port}")
ok(len(ours()) == 1 and ours()[0].port == new_port, "one entry with the chosen port")
page = P._core_page()
inp = [it for it in page if isinstance(it, H.Input) and it.key == "tg_port_in"]
ok(inp and str(new_port) in inp[0].subtext and json.loads(H.SETTINGS["tg_port_in"]) == str(new_port), "core page shows the port")

print("8) unload called on the UI thread does not hang Telegram")
H.wait_for(lambda: P._state == "on", 20)
t0 = time.time()
ui(lambda: P.on_plugin_unload())
dt = time.time() - t0
ok(dt < 3 and not ours(), f"unload on the UI thread: {dt:.1f}s, entry removed")

srv.stop()
ok(not H.UI.errors, f"no UI-thread exceptions {H.UI.errors[:3]}")
print("FAILS:", fails if fails else "none")
os._exit(1 if fails else 0)
