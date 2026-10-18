

# ===========================================================================
# Разбор ссылок на серверы
# ===========================================================================
LINK_SCHEMES = ("vless://", "vmess://", "trojan://", "ss://", "hy2://", "hysteria2://", "tuic://")
UDP_PROTOCOLS = ("hy2", "tuic")
_LINK_RE = re.compile(r"(?:vless|vmess|trojan|ss|hy2|hysteria2|tuic)://[^\s\"'<>]+", re.IGNORECASE)


class LinkError(ValueError):
    pass


def _b64_loose(text):
    s = re.sub(r"\s+", "", str(text or ""))
    if not s:
        raise LinkError("empty base64")
    s = s.replace("-", "+").replace("_", "/")
    s += "=" * (-len(s) % 4)
    return base64.b64decode(s, validate=False)


def _q(params, *names, default=""):
    for name in names:
        vals = params.get(name)
        if vals and str(vals[0]).strip() != "":
            return str(vals[0]).strip()
    return default


def _truthy(value):
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


def _port_from(text):
    m = re.match(r"^\s*(\d{1,5})", str(text or ""))
    if not m:
        raise LinkError("bad port")
    port = int(m.group(1))
    if not 0 < port < 65536:
        raise LinkError("bad port")
    return port


def _split_netloc(netloc):
    """'user@host:port' -> (user, host, port_text). Хост IPv6 — в скобках."""
    userinfo, _, hostport = netloc.rpartition("@")
    if hostport.startswith("["):
        end = hostport.find("]")
        if end < 0:
            raise LinkError("bad ipv6 host")
        host, rest = hostport[1:end], hostport[end + 1:]
        port_text = rest[1:] if rest.startswith(":") else ""
    else:
        host, _, port_text = hostport.rpartition(":")
        if not host:
            host, port_text = hostport, ""
    host = host.strip()
    if not host:
        raise LinkError("empty host")
    return urllib.parse.unquote(userinfo), host, port_text


def _blank_node(proto, uri):
    return {
        "proto": proto, "uri": uri, "name": "", "host": "", "port": 0,
        "id": "", "password": "", "method": "", "flow": "", "scy": "", "aid": 0,
        "net": "tcp", "path": "", "hosthdr": "", "service": "", "mode": "", "header": "",
        "security": "none", "sni": "", "alpn": [], "fp": "", "pbk": "", "sid": "", "spx": "",
        "insecure": False, "obfs": "", "obfs_password": "", "cc": "", "plugin": "",
    }


def _apply_stream_params(node, params):
    node["net"] = (_q(params, "type", "net", default="tcp") or "tcp").lower()
    node["path"] = urllib.parse.unquote(_q(params, "path"))
    node["hosthdr"] = _q(params, "host")
    node["service"] = urllib.parse.unquote(_q(params, "serviceName", "service_name"))
    node["mode"] = _q(params, "mode")
    node["header"] = _q(params, "headerType").lower()
    node["sni"] = _q(params, "sni", "peer", "servername")
    alpn = urllib.parse.unquote(_q(params, "alpn"))
    node["alpn"] = [a.strip() for a in alpn.split(",") if a.strip()]
    node["fp"] = _q(params, "fp", "fingerprint").lower()
    node["pbk"] = _q(params, "pbk", "publicKey")
    node["sid"] = _q(params, "sid", "shortId")
    node["spx"] = urllib.parse.unquote(_q(params, "spx", "spiderX"))
    node["insecure"] = _truthy(_q(params, "allowInsecure", "insecure", "allow_insecure"))


def _parse_url_style(uri, proto):
    body = uri.split("://", 1)[1]
    body, _, frag = body.partition("#")
    body, _, query = body.partition("?")
    netloc = body.split("/", 1)[0]
    user, host, port_text = _split_netloc(netloc)
    node = _blank_node(proto, uri)
    node["host"], node["port"] = host, _port_from(port_text)
    node["name"] = urllib.parse.unquote(frag).strip()
    params = urllib.parse.parse_qs(query, keep_blank_values=True)
    return node, user, params


def _parse_vless(uri):
    node, user, params = _parse_url_style(uri, "vless")
    if not user:
        raise LinkError("vless without id")
    node["id"] = user
    node["flow"] = _q(params, "flow")
    _apply_stream_params(node, params)
    node["security"] = (_q(params, "security", default="none") or "none").lower()
    return node


def _parse_trojan(uri):
    node, user, params = _parse_url_style(uri, "trojan")
    if not user:
        raise LinkError("trojan without password")
    node["password"] = user
    _apply_stream_params(node, params)
    node["security"] = (_q(params, "security", default="tls") or "tls").lower()
    return node


def _parse_hy2(uri):
    node, user, params = _parse_url_style(uri, "hy2")
    node["password"] = user
    node["sni"] = _q(params, "sni", "peer")
    node["insecure"] = _truthy(_q(params, "insecure", "allowInsecure"))
    node["obfs"] = _q(params, "obfs").lower()
    node["obfs_password"] = urllib.parse.unquote(_q(params, "obfs-password", "obfs_password"))
    alpn = urllib.parse.unquote(_q(params, "alpn"))
    node["alpn"] = [a.strip() for a in alpn.split(",") if a.strip()]
    node["security"] = "tls"
    return node


def _parse_tuic(uri):
    node, user, params = _parse_url_style(uri, "tuic")
    uid, _, pw = user.partition(":")
    if not uid:
        raise LinkError("tuic without uuid")
    node["id"], node["password"] = uid, pw or _q(params, "password")
    node["cc"] = _q(params, "congestion_control", "congestion", default="bbr").lower()
    node["sni"] = _q(params, "sni")
    node["insecure"] = _truthy(_q(params, "allow_insecure", "insecure", "allowInsecure"))
    alpn = urllib.parse.unquote(_q(params, "alpn"))
    node["alpn"] = [a.strip() for a in alpn.split(",") if a.strip()]
    node["security"] = "tls"
    return node


def _parse_vmess(uri):
    payload = uri.split("://", 1)[1].split("#", 1)[0]
    try:
        obj = json.loads(_b64_loose(payload).decode("utf-8", "replace"))
    except Exception:
        raise LinkError("vmess payload is not base64 json")
    if not isinstance(obj, dict) or not obj.get("add") or not obj.get("id"):
        raise LinkError("vmess without address or id")
    node = _blank_node("vmess", uri)
    node["host"] = str(obj.get("add")).strip().strip("[]")
    node["port"] = _port_from(obj.get("port"))
    node["id"] = str(obj.get("id")).strip()
    node["name"] = str(obj.get("ps") or "").strip()
    try:
        node["aid"] = int(obj.get("aid") or 0)
    except Exception:
        node["aid"] = 0
    node["scy"] = str(obj.get("scy") or "auto").lower()
    net = str(obj.get("net") or "tcp").lower()
    node["net"] = "http" if net == "h2" else net
    node["header"] = str(obj.get("type") or "").lower() if net == "tcp" else ""
    node["hosthdr"] = str(obj.get("host") or "")
    node["path"] = str(obj.get("path") or "")
    if node["net"] == "grpc":
        node["service"] = node["path"]
    node["security"] = "tls" if str(obj.get("tls") or "").lower() == "tls" else "none"
    node["sni"] = str(obj.get("sni") or "")
    node["fp"] = str(obj.get("fp") or "").lower()
    alpn = str(obj.get("alpn") or "")
    node["alpn"] = [a.strip() for a in alpn.split(",") if a.strip()]
    node["insecure"] = _truthy(obj.get("allowInsecure") or obj.get("insecure"))
    return node


def _parse_ss(uri):
    body = uri.split("://", 1)[1]
    body, _, frag = body.partition("#")
    body, _, query = body.partition("?")
    body = body.rstrip("/")
    if "@" in body:
        userinfo, _, hostport = body.rpartition("@")
        userinfo = urllib.parse.unquote(userinfo)
        if ":" in userinfo:
            method, _, password = userinfo.partition(":")
        else:
            decoded = _b64_loose(userinfo).decode("utf-8", "replace")
            method, _, password = decoded.partition(":")
        _u, host, port_text = _split_netloc("x@" + hostport)
    else:
        decoded = _b64_loose(body).decode("utf-8", "replace")
        creds, _, hostport = decoded.rpartition("@")
        method, _, password = creds.partition(":")
        _u, host, port_text = _split_netloc("x@" + hostport)
    if not method or not password:
        raise LinkError("ss without method or password")
    node = _blank_node("ss", uri)
    node["host"], node["port"] = host, _port_from(port_text)
    node["method"], node["password"] = method.strip().lower(), password
    node["name"] = urllib.parse.unquote(frag).strip()
    params = urllib.parse.parse_qs(query, keep_blank_values=True)
    node["plugin"] = urllib.parse.unquote(_q(params, "plugin"))
    return node


_PARSERS = {
    "vless": _parse_vless, "trojan": _parse_trojan, "vmess": _parse_vmess, "ss": _parse_ss,
    "hy2": _parse_hy2, "hysteria2": _parse_hy2, "tuic": _parse_tuic,
}


def parse_link(uri):
    """Ссылка -> узел (dict) или None, если ссылка не поддерживается или испорчена."""
    s = str(uri or "").strip()
    scheme = s.split("://", 1)[0].lower() if "://" in s else ""
    parser = _PARSERS.get(scheme)
    if not parser:
        return None
    try:
        node = parser(s)
    except Exception:
        return None
    if not node.get("name"):
        node["name"] = f"{node['proto']} · {node['host']}"
    return node


def _whole_line_link(line):
    """Строка целиком — одна ссылка (имя после # может содержать пробелы, как в подписках)."""
    scheme = line.split("://", 1)[0].lower() if "://" in line else ""
    if scheme not in _PARSERS or "://" in line.partition("#")[2] or " " in line.partition("#")[0]:
        return None
    return line if parse_link(line) is not None else None


def find_links(text):
    """Все ссылки на серверы в тексте (подписке, буфере обмена), без повторов, в исходном порядке."""
    out, seen = [], set()
    for line in str(text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        whole = _whole_line_link(line)
        found = [whole] if whole else [m.group(0).rstrip(".,;)") for m in _LINK_RE.finditer(line)]
        for link in found:
            if link not in seen and parse_link(link) is not None:
                seen.add(link)
                out.append(link)
    return out


def node_key(node_or_uri):
    """Ключ для дедупликации: протокол + адрес + учётные данные + транспорт, без имени."""
    node = node_or_uri if isinstance(node_or_uri, dict) else parse_link(node_or_uri)
    if not node:
        return str(node_or_uri or "")
    parts = [node["proto"], node["host"].lower(), str(node["port"]), node["id"], node["password"],
             node["method"], node["net"], node["path"], node["service"], node["security"], node["sni"], node["pbk"]]
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:20]
