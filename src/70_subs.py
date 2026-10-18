

# ===========================================================================
# Подписки
# ===========================================================================
ELIX = {"name": "elix", "url": "https://panel.elix.rip/api/sub/MvrYyN9U5XS8AuAp", "bot": "https://t.me/elixrobot"}
SUB_USER_AGENT = "v2rayN/6.23"


def _device_headers(hwid):
    try:
        release = str(Build.VERSION.RELEASE or "")
    except Exception:
        release = ""
    try:
        model = f"{Build.MANUFACTURER} {Build.MODEL}".strip()
    except Exception:
        model = "Android"
    return {"User-Agent": SUB_USER_AGENT, "Accept-Encoding": "gzip", "X-HWID": str(hwid or ""),
            "X-Device-OS": "Android", "X-Ver-OS": release, "X-Device-Model": model}


def _parse_userinfo(value):
    out = {}
    for part in str(value or "").split(";"):
        k, _, v = part.strip().partition("=")
        if k.strip() in ("upload", "download", "total", "expire"):
            try:
                out[k.strip()] = int(float(v.strip()))
            except Exception:
                pass
    return out


def _decode_title(value):
    v = str(value or "").strip()
    if v.lower().startswith("base64:"):
        try:
            return _b64_loose(v[7:]).decode("utf-8", "replace").strip()
        except Exception:
            return ""
    return urllib.parse.unquote(v)


def fetch_subscription(url, hwid):
    """-> (ссылки, {upload, download, total, expire}, заголовок). Бросает исключение при ошибке."""
    r = requests.get(str(url).strip(), headers=_device_headers(hwid), timeout=(8, 25))
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}")
    text = r.content.decode("utf-8", "replace")
    links = find_links(text)
    if not links:
        try:
            links = find_links(_b64_loose(text).decode("utf-8", "replace"))
        except Exception:
            links = []
    if not links:
        raise RuntimeError("no supported servers in the subscription")
    info = _parse_userinfo(r.headers.get("subscription-userinfo"))
    return links, info, _decode_title(r.headers.get("profile-title"))


def describe_userinfo(info):
    if not info:
        return ""
    used = int(info.get("upload", 0)) + int(info.get("download", 0))
    total = int(info.get("total", 0))
    exp = int(info.get("expire", 0))
    total_s = _human_bytes(total) if total > 0 else T("sub_unlimited")
    exp_s = time.strftime("%d.%m.%Y", time.localtime(exp)) if exp > 0 else T("sub_unlimited")
    return T("sub_info", used=_human_bytes(used), total=total_s, exp=exp_s)
