"""Settings pages in every state, subscriptions (refresh failures keep the list), clipboard import."""
import base64
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as H  # noqa: E402
import setup_env as S  # noqa: E402

os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"
fails = []


def ok(cond, what):
    print(("  ok   " if cond else "  FAIL ") + what)
    if not cond:
        fails.append(what)


m = H.load()
S.install_fake_cores(m)

LINKS = [
    "vless://11111111-2222-3333-4444-555555555555@1.2.3.4:443?type=tcp&security=reality&pbk=Aw0gYxk8Wz3XvyNN4SDZK3Tj6M1L8pYlJXCtWMrqU0E&sid=ab12&sni=a.com&fp=chrome#Нидерланды",
    "hy2://pass@5.6.7.8:443?sni=b.com#Германия hy2",
    "tuic://11111111-2222-3333-4444-555555555555:pw@9.9.9.9:443?sni=c.com#Финляндия tuic",
]
SUB = {"body": base64.b64encode("\n".join(LINKS).encode()).decode(), "code": 200}


class Sub(BaseHTTPRequestHandler):
    def do_GET(self):
        body = SUB["body"].encode()
        self.send_response(SUB["code"])
        self.send_header("subscription-userinfo", "upload=100; download=2000; total=10737418240; expire=1893456000")
        self.send_header("profile-title", "base64:" + base64.b64encode("Моя подписка".encode()).decode())
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


httpd = ThreadingHTTPServer(("127.0.0.1", 0), Sub)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
sub_url = f"http://127.0.0.1:{httpd.server_address[1]}/sub"
m.ELIX["url"] = sub_url

S.set_store([])
P = m.TropaPlugin()
P._startup = lambda: None          # pages only: no background connect/refresh
P.on_plugin_load()

KNOWN = (H.Header, H.Divider, H.Switch, H.Selector, H.Input, H.Text, H.EditText, H.Slider)


def check_pages(label):
    try:
        tree = H.settings_tree(P.create_settings())
    except Exception as e:  # noqa: BLE001
        ok(False, f"{label}: pages raise {type(e).__name__}: {e}")
        return []
    bad = [type(it).__name__ for _d, it in tree if not isinstance(it, KNOWN)]
    ok(not bad, f"{label}: only SDK widgets ({bad})")
    pages = {}
    for d, it in tree:
        pages.setdefault(d, []).append(it)
    for d, items in pages.items():
        ks = [it.key for it in items if hasattr(it, "key")]
        ok(len(ks) == len(set(ks)) or d > 0, f"{label}: no duplicate keys on page {d}")
    for _d, it in tree:
        sub = getattr(it, "subtext", None)
        if sub is not None and not isinstance(sub, str):
            ok(False, f"{label}: non-string subtext {sub!r}")
    return tree


print("1) empty, then the elix subscription")
tree = check_pages("empty")
ok(any(isinstance(it, H.Divider) and it.text == m.T("no_servers") for _d, it in tree), "empty list explained")
P.refresh_source(notify=True)
H.UI.flush()
ok(len(P._entries()) == 3, f"elix servers loaded: {len(P._entries())}")
ok(P.store["elix"]["info"].get("total") == 10737418240, "traffic info parsed")
tree = check_pages("elix")
names = [it.text for _d, it in tree if isinstance(it, H.Text)]
ok(any("Германия hy2" in t for t in names) and any("Финляндия tuic" in t for t in names), "Hysteria2/TUIC listed")

print("2) refresh failures keep the list (no flicker)")
SUB["code"] = 500
P.refresh_source(notify=True)
H.UI.flush()
ok(len(P._entries()) == 3, "HTTP error: list kept")
ok(H.BULLETINS[-1][0] == "error", "error shown")
SUB["code"], SUB["body"] = 200, "<html>maintenance</html>"
P.refresh_source(notify=False)
ok(len(P._entries()) == 3, "garbage answer: list kept")
SUB["body"] = ""
P.refresh_source(notify=False)
ok(len(P._entries()) == 3, "empty answer: list kept")
SUB["body"] = base64.b64encode("\n".join(LINKS).encode()).decode()
H.SETTINGS["core_type"] = json.dumps(1)
names = [it.text for _d, it in check_pages("xray") if isinstance(it, H.Text)]
ok(sum(1 for t in names if "только sing-box" in t) == 2, f"Xray selected: Hysteria2/TUIC stay, marked: {[t for t in names if 'sing' in t]}")
H.SETTINGS["core_type"] = json.dumps(0)

print("3) states: state row carries detail + hint, tap and long-press wired, restart row only on restart")
for st, detail in (("off", ""), ("starting", "Скачивание ядра sing-box новое… 42%"), ("on", "Нидерланды"),
                   ("paused", "включён VPN"), ("error", "Ядро не запустилось: SB core start panic: runtime error: x"),
                   ("restart", "Чтобы запустить ядро Xray, нужно перезапустить клиент.")):
    P._state, P._state_detail = st, detail
    P._pending_restart = detail if st == "restart" else ""
    tree = check_pages(st)
    rows = [it for _d, it in tree if isinstance(it, H.Text) and it.text.startswith(m.T("state"))]
    ok(rows and detail in (rows[0].subtext or "") and m.T("state_hint") in (rows[0].subtext or ""), f"{st}: state row shows detail + hint")
    ok(rows and callable(rows[0].on_click) and callable(rows[0].on_long_click), f"{st}: tap and long-press wired")
    has_restart = any(isinstance(it, H.Text) and it.text == m.T("restart_now") for _d, it in tree)
    ok(has_restart == (st == "restart"), f"{st}: restart row only in the restart state")
P._pending_restart = ""

print("4) quick-test button follows the method")
P._test_result = ("tcp", "Ответили 3 из 3 · лучший 40 мс — Нидерланды")
H.SETTINGS["ping_method"] = json.dumps(0)
ok("Ответили 3" in P._test_row().subtext, "result shown for its method")
P._set_choice("ping_method", 3)
ok(P._test_row().subtext.startswith("ICMP") and "Ответили" not in P._test_row().subtext, "new method, old result hidden")
lat = P._latency_page()
ticks = [it.text for it in lat if isinstance(it, H.Text) and it.text.endswith("✓")]
ok("ICMP Ping  ✓" in ticks, f"check mark on the chosen method: {ticks}")

print("5) core page states")
H.SETTINGS["core_modern_bad"] = json.dumps(json.dumps({"singbox": {"tag": "sb-v1.13.20-w4079", "err": "SB core start panic: runtime error", "ts": 1}}))
page = P._core_page()
ok(any(isinstance(it, H.Text) and it.text == m.T("core_retry_modern") for it in page), "retry row when the new core failed")
ok(any(isinstance(it, H.Text) and "legacy" in it.text for it in page), "shows that legacy is used")
H.SETTINGS["core_modern_bad"] = json.dumps("{}")
H.SETTINGS["core_meta2"] = json.dumps("{}")
page = P._core_page()
row = [it for it in page if isinstance(it, H.Text) and it.text.startswith(m.T("core_installed"))][0]
ok(row.subtext == m.T("core_autodl"), f"not installed: {row.subtext}")
ok(any(isinstance(it, H.Input) and it.key == "tg_port_in" for it in page), "port setting present")

print("6) own keys and subscriptions")
P._on_add_input("смотри vless://11111111-2222-3333-4444-555555555555@1.1.1.1:443?security=tls&sni=x.com#Мой ключ и мусор")
ok(len(P.store["own"]["keys"]) == 1 and P._source() == "own", "key added, source switched to own")
P._add_subscription(sub_url)
ok(len(P.store["own"]["subs"]) == 1 and P.store["own"]["subs"][0]["name"] == "Моя подписка", "subscription added with its title")
tree = check_pages("own")
own = H.settings_tree(P._own_page())
ok(any(isinstance(it, H.Text) and "Мой" in it.text for _d, it in own), "own key listed (free text: the name ends at a space)")
P._on_add_input("trojan://pw@3.3.3.3:443?sni=t.com#Ключ с пробелами")
ok(any((P._node(e) or {}).get("name") == "Ключ с пробелами" for e in P.store["own"]["keys"]), "a pasted key keeps a name with spaces")

print("7) clipboard import")
H.SETTINGS["clip_import"] = json.dumps(True)
H.CONTEXT.clipboard.clip = H.Clip("trojan://pw@2.2.2.2:443?sni=t.com#Из буфера")
H.DIALOGS.clear()
P._check_clipboard()
H.UI.flush()
ok(H.DIALOGS and "1" in (H.DIALOGS[-1]["message"] or ""), "offer to add the copied key")
H.DIALOGS[-1]["buttons"]["positive"][1](None, -1)
H.wait_for(lambda: any("Из буфера" in (P._node(e) or {}).get("name", "") for e in P.store["own"]["keys"]), 5)
ok(any("Из буфера" in (P._node(e) or {}).get("name", "") for e in P.store["own"]["keys"]), "copied key added")
H.DIALOGS.clear()
P._check_clipboard()
H.UI.flush()
ok(not H.DIALOGS, "not offered twice")

print("8) diagnostics via the state row (long-press copies, dialog shows and clears)")
P._state, P._state_detail = "error", "x"
P._save_error("short", "boom detail here")
H.COPIED.clear()
row = [it for _d, it in H.settings_tree(P.create_settings()) if isinstance(it, H.Text) and it.text.startswith(m.T("state"))][0]
row.on_long_click(None)
H.UI.flush()
ok(H.COPIED and "Tropa 0.3" in H.COPIED[-1] and "--- log ---" in H.COPIED[-1], "long-press copies the full report")
H.DIALOGS.clear()
row.on_click(None)
H.UI.flush()
ok(H.DIALOGS and "boom detail here" in (H.DIALOGS[-1]["message"] or ""), "tap shows details with the error")
ok("neutral" in H.DIALOGS[-1]["buttons"], "dialog has a clear-log button")
H.DIALOGS[-1]["buttons"]["neutral"][1](None, -3)
H.UI.flush()
ok(P._last_error() is None, "clear wipes the last error")

httpd.shutdown()
ok(not H.UI.errors, f"no UI-thread exceptions {H.UI.errors[:3]}")
print("FAILS:", fails if fails else "none")
os._exit(1 if fails else 0)
