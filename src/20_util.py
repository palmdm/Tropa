

# ===========================================================================
# Вспомогательные функции
# ===========================================================================
LOCAL_HOST = "127.0.0.1"
_LOG_LINES = collections.deque(maxlen=400)
_URL_RE = re.compile(r"(https?://[^/\s'\"]+)[^\s'\"]*", re.I)
_URL_PATH_RE = re.compile(r"(url: )/\S+", re.I)
_KEY_RE = re.compile(r"\b(vless|vmess|trojan|ss|hy2|hysteria2|tuic)://\S+", re.I)


def _redact(text):
    """Убрать из текста то, что может быть секретом: пути и параметры ссылок подписок, ключи серверов."""
    s = _KEY_RE.sub(lambda m: m.group(1) + "://…", str(text))
    s = _URL_RE.sub(lambda m: m.group(1) + ("/…" if len(m.group(0)) > len(m.group(1)) + 1 else ""), s)
    return _URL_PATH_RE.sub(lambda m: m.group(1) + "/…", s)


def _log(msg):
    """Журнал: в лог клиента и в память (для «Диагностики»). Ссылки и ключи маскируются."""
    msg = _redact(msg)
    try:
        _LOG_LINES.append(f"{time.strftime('%H:%M:%S')} {msg}")
    except Exception:
        pass
    try:
        _sdk_log(f"[tropa] {msg}")
    except Exception:
        pass


def log_lines(n=200):
    return list(_LOG_LINES)[-int(n):]


def clear_log():
    _LOG_LINES.clear()


def _now():
    try:
        return time.monotonic()
    except Exception:
        return time.time()


def _bg(fn, *args, **kwargs):
    t = threading.Thread(target=fn, args=args, kwargs=kwargs, daemon=True)
    t.start()
    return t


def _ui(fn):
    try:
        run_on_ui_thread(fn)
    except Exception as e:
        _log(f"ui call failed: {e}")


def _on_ui_thread():
    try:
        from android.os import Looper
        main = Looper.getMainLooper()
        return main is not None and Looper.myLooper() == main
    except Exception:
        return False


def _ui_sync(fn, timeout=4.0):
    """Выполнить fn на UI-потоке и дождаться результата (исключение пробрасывается).
    Если уже на UI-потоке — выполнить сразу (ожидание самого себя повесило бы интерфейс)."""
    if _on_ui_thread():
        return fn()
    box = {}
    done = threading.Event()

    def runner():
        try:
            box["value"] = fn()
        except Exception as e:  # noqa: BLE001 - передаём вызывающему
            box["error"] = e
        finally:
            done.set()
    try:
        run_on_ui_thread(runner)
    except Exception as e:
        raise RuntimeError(f"ui thread unavailable: {e}")
    if not done.wait(float(timeout)):
        raise TimeoutError("ui thread timeout")
    if "error" in box:
        raise box["error"]
    return box.get("value")


def _notify(kind, text):
    def show():
        try:
            if kind == "ok":
                BulletinHelper.show_success(str(text))
            elif kind == "error":
                BulletinHelper.show_error(str(text))
            else:
                BulletinHelper.show_info(str(text))
        except Exception:
            pass
    _ui(show)


def _short(text, n=160):
    """Одна строка не длиннее n символов — для подписей в настройках и всплывающих сообщений."""
    s = " ".join(str(text or "").split())
    return s if len(s) <= n else s[:max(1, n - 1)] + "…"


def _jlist(obj):
    """Java-коллекция или Java-массив -> список Python.

    В Chaquopy, на котором работает Aprel Gram, объекты java.util (ArrayList, LinkedList…)
    нельзя перебирать в for, передавать в list() или len(): итерируются только Java-массивы.
    Поэтому коллекции читаем через size()/get(i)."""
    if obj is None:
        return []
    size = getattr(obj, "size", None)
    if callable(size):
        try:
            return [obj.get(i) for i in range(int(size()))]
        except Exception:
            pass
    to_array = getattr(obj, "toArray", None)
    if callable(to_array):
        try:
            arr = to_array()
            return [arr[i] for i in range(len(arr))]
        except Exception:
            pass
    try:
        return list(obj)
    except Exception:
        return []


def _copy_text(text):
    """Скопировать текст в буфер обмена (с сообщением «Скопировано»)."""
    try:
        from android_utils import copy_to_clipboard
        copy_to_clipboard(str(text))
        return True
    except Exception:
        pass
    try:
        from android.content import ClipData
        cm = ApplicationLoader.applicationContext.getSystemService("clipboard")
        cm.setPrimaryClip(ClipData.newPlainText("Tropa", str(text)))
        _notify("ok", T("copied"))
        return True
    except Exception as e:
        _log(f"copy failed: {e}")
        _notify("error", T("copy_failed"))
        return False


def _rand_token(n=16):
    alphabet = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    rng = random.SystemRandom()
    return "".join(rng.choice(alphabet) for _ in range(int(n)))


def restart_client():
    """Перезапустить клиент (как это делает сам Aprel Gram: запустить заново и выйти).
    Нужно, чтобы сменить загруженное в процесс ядро: второе Go-ядро в одном процессе ненадёжно."""
    def do():
        try:
            ctx = ApplicationLoader.applicationContext
            intent = ctx.getPackageManager().getLaunchIntentForPackage(ctx.getPackageName())
            # FLAG_ACTIVITY_NEW_TASK | FLAG_ACTIVITY_CLEAR_TOP = 0x14000000
            intent.addFlags(0x14000000)
            ctx.startActivity(intent)
        except Exception as e:
            _log(f"restart: relaunch failed: {e}")
        try:
            from java.lang import System as _JSystem
            _JSystem.exit(0)
        except Exception:
            try:
                os._exit(0)
            except Exception:
                pass
    _ui(do)


def open_plugin_settings(plugin_id):
    """Открыть страницу настроек плагина (для пункта в меню Telegram)."""
    def do():
        for name in ("by.aprelteam.plugins.PluginsController",
                     "com.exteragram.messenger.plugins.PluginsController"):
            pc = find_class(name)
            if pc is None:
                continue
            try:
                pc.openPluginSettings(plugin_id)
                return
            except Exception:
                pass
            try:
                frag = get_last_fragment() if get_last_fragment else None
                if frag is not None:
                    pc.openPluginSettings(plugin_id, frag)
                    return
            except Exception:
                pass
        _log("open plugin settings: no controller")
    _ui(do)


def _free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind((LOCAL_HOST, 0))
        return int(s.getsockname()[1])
    finally:
        s.close()


def _free_ports(n):
    held, ports = [], []
    try:
        for _ in range(int(n)):
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            held.append(s)
            s.bind((LOCAL_HOST, 0))
            ports.append(int(s.getsockname()[1]))
    finally:
        for s in held:
            try:
                s.close()
            except Exception:
                pass
    return ports


def _port_free(port):
    """Свободен ли порт для прослушивания (как его займёт ядро: с SO_REUSEADDR)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((LOCAL_HOST, int(port)))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _port_open(port, timeout=0.3):
    try:
        with socket.create_connection((LOCAL_HOST, int(port)), timeout=float(timeout)):
            return True
    except Exception:
        return False


def _human_bytes(n):
    try:
        n = float(n)
    except Exception:
        return "?"
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if n < 1024 or unit == "ТБ":
            return f"{n:.0f} {unit}" if unit in ("Б", "КБ") else f"{n:.1f} {unit}"
        n /= 1024.0
    return "?"
