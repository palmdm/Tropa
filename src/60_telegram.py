

# ===========================================================================
# Связка с Telegram: прокси в настройках клиента и звонки
# ===========================================================================
TG_USER_PREFIX = "tropa_"


def _pget(info, getter, field, default):
    """Поле ProxyInfo: геттер (Aprel Gram) или публичное поле (другие форки)."""
    try:
        fn = getattr(info, getter, None)
        if callable(fn):
            value = fn()
            if value is not None:
                return value
    except Exception:
        pass
    try:
        value = getattr(info, field)
        return default if value is None else value
    except Exception:
        return default


def _proxy_fields(info):
    return (str(_pget(info, "getAddress", "address", "")), int(_pget(info, "getPort", "port", 0) or 0),
            str(_pget(info, "getUsername", "username", "")), str(_pget(info, "getPassword", "password", "")),
            str(_pget(info, "getSecret", "secret", "")))


def _is_ours(info):
    try:
        addr, _port, user, _pwd, secret = _proxy_fields(info)
        return addr == LOCAL_HOST and user.startswith(TG_USER_PREFIX) and not secret
    except Exception:
        return False


def _same_endpoint(info, port, user, password):
    try:
        return _proxy_fields(info)[:4] == (LOCAL_HOST, int(port), str(user), str(password))
    except Exception:
        return False


def _proxy_enabled():
    try:
        return bool(SharedConfig.isProxyEnabled())
    except Exception:
        return False


def telegram_proxies():
    """Список прокси Telegram как список Python (см. _jlist: java.util нельзя перебирать напрямую)."""
    try:
        SharedConfig.loadProxyList()
    except Exception:
        pass
    return _jlist(SharedConfig.proxyList)


class TelegramProxy:
    """Держит в списке прокси Telegram ровно одну запись Tropa (127.0.0.1, постоянные порт и логин)
    и делает её текущей. Чужие прокси не трогает, прежний текущий прокси возвращает при выключении."""

    def __init__(self, plugin):
        self.plugin = plugin

    def apply(self, port, user, password):
        def work():
            info_cls = find_class("org.telegram.messenger.SharedConfig$ProxyInfo")
            if info_cls is None:
                raise RuntimeError("SharedConfig.ProxyInfo is unavailable")
            proxies = telegram_proxies()
            cur = SharedConfig.currentProxy
            if cur is not None and _proxy_enabled() and not _is_ours(cur):
                self.plugin.set_setting("tg_prev_proxy", json.dumps(_proxy_fields(cur)), reload_settings=False)
            mine = next((p for p in proxies if _same_endpoint(p, port, user, password)), None)
            if mine is None:
                mine = SharedConfig.addProxy(info_cls(LOCAL_HOST, int(port), str(user), str(password), ""))
            if mine is None:
                raise RuntimeError("addProxy returned nothing")
            SharedConfig.setCurrentProxy(mine)
            removed = 0
            for p in telegram_proxies():
                if _is_ours(p) and not _same_endpoint(p, port, user, password):
                    SharedConfig.deleteProxy(p)
                    removed += 1
            return removed
        removed = _ui_sync(work, 8.0) or 0
        if removed:
            _log(f"removed {removed} old Tropa entries from the Telegram proxy list")
        return removed

    def remove(self, restore=True):
        def work():
            prev = None
            try:
                prev = tuple(json.loads(self.plugin.get_setting("tg_prev_proxy", "") or "null") or ()) or None
            except Exception:
                prev = None
            proxies = telegram_proxies()
            cur = SharedConfig.currentProxy
            switched = False
            if restore and prev:
                for p in proxies:
                    if not _is_ours(p) and _proxy_fields(p) == tuple(prev):
                        SharedConfig.setCurrentProxy(p)
                        switched = True
                        break
            if not switched and cur is not None and _is_ours(cur):
                SharedConfig.setCurrentProxy(None)      # выключает прокси в Telegram
            for p in telegram_proxies():
                if _is_ours(p):
                    SharedConfig.deleteProxy(p)
        try:
            _ui_sync(work, 8.0)
        finally:
            self.plugin.set_setting("tg_prev_proxy", "", reload_settings=False)

    def has_ours(self):
        try:
            return any(_is_ours(p) for p in telegram_proxies())
        except Exception:
            return False

    def is_active(self, port, user):
        """Включён ли в Telegram именно наш прокси (False — пользователь выключил или сменил его)."""
        try:
            cur = SharedConfig.currentProxy
            if cur is None or not _proxy_enabled():
                return False
            fields = _proxy_fields(cur)
            return _is_ours(cur) and fields[1] == int(port) and fields[2] == str(user)
        except Exception:
            return True


class CallProxyHook(MethodHook):
    """Подставляет локальный SOCKS5 в Instance.makeInstance (5-й аргумент — прокси звонка)."""

    def __init__(self, plugin):
        super().__init__()
        self.plugin = plugin

    def before_hooked_method(self, param):
        try:
            proxy = self.plugin._call_proxy_object()
            if proxy is not None and param.args is not None and len(param.args) > 4:
                param.args[4] = proxy
        except Exception as e:
            _log(f"call proxy hook: {e}")
