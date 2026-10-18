

# ===========================================================================
# Конфигурации ядер
# ===========================================================================
CORE_SINGBOX = "singbox"
CORE_XRAY = "xray"
CORE_TYPES = (CORE_SINGBOX, CORE_XRAY)
CORE_TITLES = {CORE_SINGBOX: "sing-box", CORE_XRAY: "Xray"}
_SB_FINGERPRINTS = ("chrome", "firefox", "edge", "safari", "360", "qq", "ios", "android", "random", "randomized")


class UnsupportedNode(ValueError):
    pass


# ---- sing-box ---------------------------------------------------------------
# Форма конфига совпадает с той, что сборщик новых ядер сам отдаёт своему ядру:
# лог выключен (level=panic), DNS 1.1.1.1/8.8.8.8 и явный default_domain_resolver.
SB_LOG = {"level": "panic"}
SB_DNS = {"servers": [{"type": "udp", "tag": "dns-a", "server": "1.1.1.1"},
                      {"type": "udp", "tag": "dns-b", "server": "8.8.8.8"}]}


def _sb_tls(node, required=False, quic=False):
    sec = node["security"]
    if sec not in ("tls", "reality") and not required:
        return None
    tls = {"enabled": True, "server_name": node["sni"] or (node["hosthdr"] if sec == "tls" else "") or node["host"]}
    if node["insecure"]:
        tls["insecure"] = True
    if node["alpn"]:
        tls["alpn"] = list(node["alpn"])
    if quic:
        # Hysteria2 и TUIC: TLS внутри QUIC делает сам sing-box, uTLS и Reality к нему неприменимы
        return tls
    fp = node["fp"] if node["fp"] in _SB_FINGERPRINTS else ("chrome" if node["fp"] else "")
    if sec == "reality":
        if not node["pbk"]:
            raise UnsupportedNode("reality without public key")
        tls["reality"] = {"enabled": True, "public_key": node["pbk"], "short_id": node["sid"]}
        fp = fp or "chrome"
    if fp:
        tls["utls"] = {"enabled": True, "fingerprint": fp}
    return tls


def _sb_transport(node):
    net = node["net"]
    if net in ("", "tcp", "raw"):
        if node["header"] not in ("", "none"):
            raise UnsupportedNode("tcp header obfuscation")
        return None
    path = node["path"] or "/"
    if net == "ws":
        tr = {"type": "ws", "path": path}
        m = re.search(r"[?&]ed=(\d+)", path)
        if m:
            tr["path"] = re.sub(r"[?&]ed=\d+", "", path) or "/"
            tr["max_early_data"] = int(m.group(1))
            tr["early_data_header_name"] = "Sec-WebSocket-Protocol"
        if node["hosthdr"]:
            tr["headers"] = {"Host": node["hosthdr"]}
        return tr
    if net == "grpc":
        return {"type": "grpc", "service_name": node["service"]}
    if net == "httpupgrade":
        tr = {"type": "httpupgrade", "path": path}
        if node["hosthdr"]:
            tr["host"] = node["hosthdr"]
        return tr
    if net in ("http", "h2"):
        tr = {"type": "http", "path": path}
        if node["hosthdr"]:
            tr["host"] = [h.strip() for h in node["hosthdr"].split(",") if h.strip()]
        return tr
    raise UnsupportedNode(f"transport {net}")


def sb_outbound(node, tag="proxy"):
    p = node["proto"]
    ob = {"tag": tag, "server": node["host"], "server_port": int(node["port"])}
    if p in ("vless", "vmess", "trojan"):
        if p == "vless":
            ob.update(type="vless", uuid=node["id"], packet_encoding="xudp")
            if node["flow"]:
                ob["flow"] = node["flow"]
        elif p == "vmess":
            ob.update(type="vmess", uuid=node["id"], security=node["scy"] or "auto",
                      alter_id=int(node["aid"] or 0), packet_encoding="xudp")
        else:
            ob.update(type="trojan", password=node["password"])
        tls = _sb_tls(node)
        if tls:
            ob["tls"] = tls
        tr = _sb_transport(node)
        if tr:
            ob["transport"] = tr
    elif p == "ss":
        if node["plugin"]:
            raise UnsupportedNode("shadowsocks plugin")
        ob.update(type="shadowsocks", method=node["method"], password=node["password"])
    elif p == "hy2":
        ob.update(type="hysteria2", password=node["password"], tls=_sb_tls(node, required=True, quic=True))
        if node["obfs"] == "salamander":
            if not node["obfs_password"]:
                raise UnsupportedNode("salamander without password")
            ob["obfs"] = {"type": "salamander", "password": node["obfs_password"]}
    elif p == "tuic":
        ob.update(type="tuic", uuid=node["id"], password=node["password"],
                  congestion_control=node["cc"] or "bbr", tls=_sb_tls(node, required=True, quic=True))
        ob["tls"].setdefault("alpn", ["h3"])
    else:
        raise UnsupportedNode(p)
    return ob


def sb_inbound(tag, port, user, password):
    return {"type": "mixed", "tag": tag, "listen": LOCAL_HOST, "listen_port": int(port),
            "users": [{"username": user, "password": password}]}


def sb_config(inbounds, outbounds, rules=None, final=None):
    outbounds = list(outbounds)
    route = {"default_domain_resolver": "dns-a"}
    final = final or (outbounds[0]["tag"] if outbounds else "")
    if final:
        route["final"] = final
    if rules:
        route["rules"] = list(rules)
    return {"log": dict(SB_LOG), "dns": json.loads(json.dumps(SB_DNS)), "inbounds": list(inbounds),
            "outbounds": outbounds, "route": route}


# ---- Xray -------------------------------------------------------------------
def _xr_stream(node):
    net = node["net"] or "tcp"
    net = "raw" if net == "tcp" else net
    st = {"network": "http" if net == "h2" else net}
    path = node["path"] or "/"
    if net == "raw":
        if node["header"] == "http":
            st["rawSettings"] = {"header": {"type": "http", "request": {"path": [path],
                                 "headers": {"Host": [node["hosthdr"]] if node["hosthdr"] else []}}}}
    elif net == "ws":
        ws = {"path": path}
        if node["hosthdr"]:
            ws["host"] = node["hosthdr"]
        st["wsSettings"] = ws
    elif net == "grpc":
        st["grpcSettings"] = {"serviceName": node["service"]}
    elif net == "httpupgrade":
        st["httpupgradeSettings"] = {"path": path, "host": node["hosthdr"]}
    elif net == "xhttp":
        xh = {"path": path, "host": node["hosthdr"]}
        if node["mode"]:
            xh["mode"] = node["mode"]
        st["xhttpSettings"] = xh
    else:
        raise UnsupportedNode(f"transport {net}")
    sec = node["security"]
    if sec == "tls":
        tls = {"serverName": node["sni"] or node["hosthdr"] or node["host"]}
        if node["alpn"]:
            tls["alpn"] = list(node["alpn"])
        if node["fp"]:
            tls["fingerprint"] = node["fp"]
        if node["insecure"]:
            tls["allowInsecure"] = True
        st["security"], st["tlsSettings"] = "tls", tls
    elif sec == "reality":
        if not node["pbk"]:
            raise UnsupportedNode("reality without public key")
        st["security"] = "reality"
        st["realitySettings"] = {"serverName": node["sni"] or node["host"], "publicKey": node["pbk"],
                                 "shortId": node["sid"], "fingerprint": node["fp"] or "chrome",
                                 "spiderX": node["spx"] or ""}
    return st


def xr_outbound(node, tag="proxy"):
    p = node["proto"]
    if p == "vless":
        user = {"id": node["id"], "encryption": "none"}
        if node["flow"]:
            user["flow"] = node["flow"]
        ob = {"protocol": "vless", "settings": {"vnext": [{"address": node["host"], "port": int(node["port"]), "users": [user]}]}}
    elif p == "vmess":
        ob = {"protocol": "vmess", "settings": {"vnext": [{"address": node["host"], "port": int(node["port"]),
              "users": [{"id": node["id"], "alterId": int(node["aid"] or 0), "security": node["scy"] or "auto"}]}]}}
    elif p == "trojan":
        ob = {"protocol": "trojan", "settings": {"servers": [{"address": node["host"], "port": int(node["port"]),
              "password": node["password"]}]}}
    elif p == "ss":
        if node["plugin"]:
            raise UnsupportedNode("shadowsocks plugin")
        ob = {"protocol": "shadowsocks", "settings": {"servers": [{"address": node["host"], "port": int(node["port"]),
              "method": node["method"], "password": node["password"]}]}}
        ob["tag"] = tag
        return ob
    else:
        raise UnsupportedNode(f"{p} in Xray")
    ob["streamSettings"] = _xr_stream(node)
    ob["tag"] = tag
    return ob


def xr_inbound(tag, port, user, password):
    return {"tag": tag, "protocol": "socks", "listen": LOCAL_HOST, "port": int(port),
            "settings": {"auth": "password", "accounts": [{"user": user, "pass": password}], "udp": True}}


def xr_config(inbounds, outbounds, rules=None, balancer=None, probe_url=None):
    cfg = {"log": {"loglevel": "error"}, "inbounds": list(inbounds),
           "outbounds": list(outbounds) + [{"tag": "direct", "protocol": "freedom"}]}
    routing = {"domainStrategy": "AsIs", "rules": list(rules or [])}
    if balancer:
        routing["balancers"] = [balancer]
        cfg["observatory"] = {"subjectSelector": list(balancer["selector"]), "probeURL": probe_url,
                              "probeInterval": "3m", "enableConcurrency": True}
    cfg["routing"] = routing
    return cfg


# ---- общий интерфейс -----------------------------------------------------------
def build_outbound(core, node, tag):
    return xr_outbound(node, tag) if core == CORE_XRAY else sb_outbound(node, tag)


def node_supported(core, node):
    try:
        build_outbound(core, node, "probe")
        return True
    except Exception:
        return False


def build_main_config(core, nodes, port, user, password, auto_url=None):
    """Рабочий конфиг: вход для Telegram -> один сервер, либо автовыбор лучшего из нескольких."""
    nodes = [n for n in nodes if n]
    if not nodes:
        raise UnsupportedNode("no servers")
    if core == CORE_XRAY:
        inbound = xr_inbound("tg-in", port, user, password)
        if len(nodes) == 1 or not auto_url:
            return xr_config([inbound], [xr_outbound(nodes[0], "proxy")])
        outs = [xr_outbound(n, f"auto-{i}") for i, n in enumerate(nodes)]
        balancer = {"tag": "best", "selector": ["auto-"], "strategy": {"type": "leastPing"}}
        rules = [{"type": "field", "inboundTag": ["tg-in"], "balancerTag": "best"}]
        return xr_config([inbound], outs, rules=rules, balancer=balancer, probe_url=auto_url)
    inbound = sb_inbound("tg-in", port, user, password)
    if len(nodes) == 1 or not auto_url:
        return sb_config([inbound], [sb_outbound(nodes[0], "proxy")], final="proxy")
    outs = [sb_outbound(n, f"auto-{i}") for i, n in enumerate(nodes)]
    group = {"type": "urltest", "tag": "proxy", "outbounds": [o["tag"] for o in outs],
             "url": auto_url, "interval": "3m", "tolerance": 80}
    return sb_config([inbound], outs + [group], final="proxy")


def add_test_pairs(core, config, pairs, user, password):
    """Пары «вход -> сервер» для HTTP-теста. pairs: [(i, port, node)].
    config — рабочий конфиг (тест идёт, не прерывая Telegram) или None (отдельный конфиг теста)."""
    standalone = config is None
    if standalone:
        cfg = xr_config([], []) if core == CORE_XRAY else sb_config([], [])
    else:
        cfg = json.loads(json.dumps(config))
    ins, outs, rules = [], [], []
    for i, port, node in pairs:
        in_tag, out_tag = f"t-in-{i}", f"t-out-{i}"
        outs.append(build_outbound(core, node, out_tag))
        if core == CORE_XRAY:
            ins.append(xr_inbound(in_tag, port, user, password))
            rules.append({"type": "field", "inboundTag": [in_tag], "outboundTag": out_tag})
        else:
            ins.append(sb_inbound(in_tag, port, user, password))
            rules.append({"inbound": [in_tag], "outbound": out_tag})
    cfg["inbounds"] = list(cfg.get("inbounds") or []) + ins
    direct = [o for o in cfg.get("outbounds") or [] if o.get("tag") == "direct"]
    others = [o for o in cfg.get("outbounds") or [] if o.get("tag") != "direct"]
    cfg["outbounds"] = others + outs + direct
    if core == CORE_XRAY:
        routing = dict(cfg.get("routing") or {"domainStrategy": "AsIs"})
        routing["rules"] = rules + list(routing.get("rules") or [])
        cfg["routing"] = routing
    else:
        route = dict(cfg.get("route") or {})
        route["rules"] = rules + list(route.get("rules") or [])
        if standalone and outs:
            route["final"] = outs[0]["tag"]
        cfg["route"] = route
    return cfg
