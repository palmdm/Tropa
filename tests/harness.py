"""Test harness for Tropa: fakes of the Aprel Gram plugin SDK, Telegram classes and Chaquopy behaviour.

The fakes deliberately reproduce what broke on a real device:
  * java.util.ArrayList is NOT iterable and has no len() (Aprel's Chaquopy build supports
    container protocols only for Java arrays);
  * SharedConfig follows Aprel Gram's own code (addProxy dedup by settings, deleteProxy,
    setCurrentProxy -> setProxyEnable, loadProxyList only once per process);
  * settings are JSON strings kept by the "bridge" and survive plugin reloads and app restarts;
  * run_on_ui_thread posts to a separate UI thread.
"""
import dataclasses
import importlib.util
import json
import os
import queue
import shutil
import sys
import tempfile
import threading
import time
import types
from typing import Any, Callable, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN_PATH = os.path.join(ROOT, "dist", "tropa.plugin")
FAKECORE_DIR = os.path.join(ROOT, "tests", "fakecore")
SING_BOX = os.environ.get("SING_BOX", "/home/claude/bin/sing-box-utls")
SING_BOX_120 = os.environ.get("SING_BOX_120", "/home/claude/bin/sing-box")

WORK = tempfile.mkdtemp(prefix="tropa-test-")
FILES = os.path.join(WORK, "files")
os.makedirs(FILES, exist_ok=True)


# ============================================================ Chaquopy-like Java objects
class JavaArray(list):
    """Java arrays: Chaquopy supports len(), indexing and iteration for them."""


class ArrayList:
    """java.util.ArrayList as Aprel Gram's Chaquopy exposes it: only Java methods."""

    def __init__(self, items=None):
        self._items = list(items or [])

    def size(self):
        return len(self._items)

    def get(self, i):
        if not 0 <= int(i) < len(self._items):
            raise IndexError(f"java.lang.IndexOutOfBoundsException: Index {i} out of bounds for length {len(self._items)}")
        return self._items[int(i)]

    def add(self, *args):
        if len(args) == 1:
            self._items.append(args[0])
            return True
        self._items.insert(int(args[0]), args[1])
        return None

    def remove(self, obj):
        for i, x in enumerate(self._items):
            if x is obj:
                del self._items[i]
                return True
        return False

    def clear(self):
        self._items.clear()

    def toArray(self):
        return JavaArray(self._items)

    def __iter__(self):
        raise TypeError("'ArrayList' object is not iterable")


# ============================================================ UI thread
class UiThread:
    def __init__(self):
        self.q = queue.Queue()
        self.thread = threading.Thread(target=self._loop, name="ui", daemon=True)
        self.errors = []
        self.thread.start()

    def _loop(self):
        while True:
            fn = self.q.get()
            try:
                fn()
            except Exception as e:  # noqa: BLE001
                self.errors.append(repr(e))

    def post(self, fn):
        self.q.put(fn)

    def is_ui(self):
        return threading.current_thread() is self.thread

    def flush(self, timeout=5.0):
        done = threading.Event()
        self.post(done.set)
        return done.wait(timeout)


UI = UiThread()
UI_VIOLATIONS = []


def _require_ui(what):
    if not UI.is_ui():
        UI_VIOLATIONS.append(what)


# ============================================================ Telegram: proxy classes (Aprel Gram behaviour)
class ProxySettings:
    def __init__(self, ptype, address, port, user, password, secret):
        self.type, self.address, self.port = ptype, address, int(port)
        self.user, self.password, self.secret = user, password, secret

    def key(self):
        return (self.type, self.address, self.port, self.user, self.password, self.secret)

    def __eq__(self, other):
        return isinstance(other, ProxySettings) and self.key() == other.key()

    def __hash__(self):
        return hash(self.key())


class ProxyInfo:
    def __init__(self, *args):
        if len(args) == 5:
            address, port, user, password, secret = args
            settings = ProxySettings("MTPROTO" if secret else "SOCKS5", str(address), int(port), str(user),
                                     str(password), str(secret))
        else:
            settings = args[0]
        self.setSettings(settings)
        self.ping, self.available, self.checking, self.availableCheckTime = 0, False, False, 0

    def setSettings(self, s):
        self.settings = s
        self.address, self.port, self.username, self.password, self.secret = s.address, s.port, s.user, s.password, s.secret

    def getAddress(self):
        return self.settings.address

    def getPort(self):
        return self.settings.port

    def getUsername(self):
        return self.settings.user

    def getPassword(self):
        return self.settings.password

    def getSecret(self):
        return self.settings.secret


class SharedConfig:
    proxyList = ArrayList()
    currentProxy = None
    proxyListLoaded = False
    prefs = {"proxy_list": [], "proxy_enabled": False, "current": None}
    apply_calls = 0

    @classmethod
    def loadProxyList(cls):
        if cls.proxyListLoaded:
            return
        cls.proxyListLoaded = True
        cls.proxyList.clear()
        cls.currentProxy = None
        for key in cls.prefs["proxy_list"]:
            info = ProxyInfo(ProxySettings(*key))
            cls.proxyList.add(0, info)
            if cls.currentProxy is None and cls.prefs.get("current") == key:
                cls.currentProxy = info

    @classmethod
    def saveProxyList(cls):
        cls.prefs["proxy_list"] = [cls.proxyList.get(i).settings.key() for i in range(cls.proxyList.size() - 1, -1, -1)]

    @classmethod
    def addProxy(cls, p):
        _require_ui("addProxy")
        cls.loadProxyList()
        for i in range(cls.proxyList.size()):
            x = cls.proxyList.get(i)
            if x.settings == p.settings:
                return x
        cls.proxyList.add(0, p)
        cls.saveProxyList()
        return p

    @classmethod
    def deleteProxy(cls, p):
        _require_ui("deleteProxy")
        if cls.currentProxy is p:
            cls.currentProxy = None
            cls.prefs["proxy_enabled"] = False
            cls.prefs["current"] = None
        cls.proxyList.remove(p)
        cls.saveProxyList()

    @classmethod
    def setCurrentProxy(cls, p):
        _require_ui("setCurrentProxy")
        cls.currentProxy = p
        cls.prefs["current"] = p.settings.key() if p is not None else None
        cls.setProxyEnable(p is not None)

    @classmethod
    def setProxyEnable(cls, enabled):
        if enabled and cls.currentProxy is None:
            enabled = False
        cls.prefs["proxy_enabled"] = bool(enabled)
        cls.apply_calls += 1

    @classmethod
    def isProxyEnabled(cls):
        cls.loadProxyList()
        return bool(cls.prefs["proxy_enabled"]) and cls.currentProxy is not None

    # ---- test helpers
    @classmethod
    def reset(cls):
        cls.proxyList, cls.currentProxy, cls.proxyListLoaded = ArrayList(), None, False
        cls.prefs = {"proxy_list": [], "proxy_enabled": False, "current": None}

    @classmethod
    def restart(cls):
        """Telegram process restart: the list is read back from preferences."""
        cls.proxyList, cls.currentProxy, cls.proxyListLoaded = ArrayList(), None, False

    @classmethod
    def entries(cls):
        cls.loadProxyList()
        return [cls.proxyList.get(i) for i in range(cls.proxyList.size())]


# ============================================================ Android context
class JFile:
    def __init__(self, path):
        self.path = path

    def __str__(self):
        return self.path

    def getAbsolutePath(self):
        return self.path


class NetCaps:
    def __init__(self, transports):
        self.t = set(transports)

    def hasTransport(self, t):
        return int(t) in self.t


class Network:
    def __init__(self, handle, transports):
        self.handle, self.caps = handle, NetCaps(transports)

    def getNetworkHandle(self):
        return self.handle


class ConnectivityManager:
    def __init__(self):
        self.active = Network(100, [1])          # Wi-Fi
        self.all = [self.active]
        self.metered = False

    def getActiveNetwork(self):
        return self.active

    def getNetworkCapabilities(self, net):
        return net.caps if net is not None else None

    def getAllNetworks(self):
        return JavaArray(self.all)

    def isActiveNetworkMetered(self):
        return self.metered

    def set(self, kind, vpn=False):
        transports = {"wifi": [1], "cellular": [0], "none": []}[kind] + ([4] if vpn else [])
        self.active = Network(self.active.handle + 1, transports) if kind != "none" else None
        self.all = [n for n in [self.active] if n]


class ClipItem:
    def __init__(self, text):
        self.text = text

    def coerceToText(self, ctx):
        return self.text


class Clip:
    def __init__(self, text):
        self.items = [ClipItem(text)]

    def getItemCount(self):
        return len(self.items)

    def getItemAt(self, i):
        return self.items[i]


class ClipboardManager:
    def __init__(self):
        self.clip = None

    def getPrimaryClip(self):
        return self.clip

    def setPrimaryClip(self, clip):
        self.clip = clip


class PackageInfo:
    versionName = "1.0.7"


class Intent:
    def __init__(self, pkg):
        self.pkg, self.flags = pkg, 0

    def addFlags(self, f):
        self.flags |= int(f)
        return self


class PackageManager:
    def getPackageInfo(self, pkg, flags):
        return PackageInfo()

    def getLaunchIntentForPackage(self, pkg):
        return Intent(pkg)


STARTED_ACTIVITIES = []


class AppContext:
    def __init__(self):
        self.cm = ConnectivityManager()
        self.clipboard = ClipboardManager()

    def getDir(self, name, mode):
        d = os.path.join(FILES, "app_" + name)
        os.makedirs(d, exist_ok=True)
        return JFile(d)

    def getFilesDir(self):
        return JFile(FILES)

    def getSystemService(self, name):
        return {"connectivity": self.cm, "clipboard": self.clipboard}.get(name)

    def getPackageName(self):
        return "by.aprelteam.gram"

    def getPackageManager(self):
        return PackageManager()

    def startActivity(self, intent):
        STARTED_ACTIVITIES.append(intent)


class System:
    @staticmethod
    def exit(code):
        RESTARTS[0] += 1          # в тесте процесс не убиваем, только фиксируем перезапуск


SETTINGS_OPENED = []


class PluginsController:
    @staticmethod
    def openPluginSettings(*args):
        SETTINGS_OPENED.append(args)


CONTEXT = AppContext()


class ApplicationLoader:
    applicationContext = CONTEXT


class _Version:
    SDK_INT = 34
    RELEASE = "14"


class Build:
    VERSION = _Version
    SUPPORTED_ABIS = JavaArray(["arm64-v8a", "armeabi-v7a"])
    MANUFACTURER = "Test"
    MODEL = "Phone"


class _LooperObj:
    pass


_MAIN_LOOPER = _LooperObj()


class Looper:
    @staticmethod
    def getMainLooper():
        return _MAIN_LOOPER

    @staticmethod
    def myLooper():
        return _MAIN_LOOPER if UI.is_ui() else None


class Locale:
    @staticmethod
    def getDefault():
        return types.SimpleNamespace(getLanguage=lambda: "ru")


# ============================================================ SDK modules
SETTINGS = {}          # what PythonBridge persists: key -> JSON string
RELOADS = [0]
LOGS = []
BULLETINS = []
DIALOGS = []
COPIED = []
HOOKS = []


MENU_ITEMS = {}        # item_id -> MenuItemData
RESTARTS = [0]


class BasePlugin:
    id = "tropa"

    def get_setting(self, key, default=None):
        raw = SETTINGS.get(key)
        if raw is None:
            return default
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return default

    def set_setting(self, key, value, reload_settings=False):
        SETTINGS[key] = json.dumps(value, ensure_ascii=False)
        if reload_settings:
            RELOADS[0] += 1

    def hook_all_methods(self, cls, name, hook):
        HOOKS.append((cls, name, hook))
        return object()

    def hook_method(self, *a, **k):
        HOOKS.append(a)
        return object()

    def add_menu_item(self, data):
        MENU_ITEMS[data.item_id] = data

    def remove_menu_item(self, item_id):
        MENU_ITEMS.pop(item_id, None)

    def log(self, msg):
        LOGS.append(str(msg))


class MethodHook:
    def __init__(self):
        pass


class AppEvent:
    START, STOP, PAUSE, RESUME = "start", "stop", "pause", "resume"


class MenuItemType:
    MESSAGE_CONTEXT_MENU = "MESSAGE_CONTEXT_MENU"
    DRAWER_MENU = "DRAWER_MENU"
    MAIN_MENU = "MAIN_MENU"
    CHAT_ACTION_MENU = "CHAT_ACTION_MENU"
    PROFILE_ACTION_MENU = "PROFILE_ACTION_MENU"


@dataclasses.dataclass
class MenuItemData:
    menu_type: str
    text: str
    on_click: Optional[Callable] = None
    item_id: Optional[str] = None
    icon: Optional[str] = None
    subtext: Optional[str] = None
    condition: Optional[Callable] = None
    priority: int = 0


def _sdk_log(msg):
    LOGS.append(str(msg))


def run_on_ui_thread(fn, delay=0):
    UI.post(fn)


def copy_to_clipboard(text):
    COPIED.append(str(text))
    BULLETINS.append(("copied", ""))


@dataclasses.dataclass
class Header:
    text: str


@dataclasses.dataclass
class Divider:
    text: Optional[str] = None


@dataclasses.dataclass
class Switch:
    key: str
    text: str
    default: bool
    subtext: Optional[str] = None
    icon: Optional[str] = None
    on_change: Optional[Callable] = None
    on_long_click: Optional[Callable] = None
    link_alias: Optional[str] = None


@dataclasses.dataclass
class Selector:
    key: str
    text: str
    default: int
    items: List[str]
    subtext: Optional[str] = None
    icon: Optional[str] = None
    on_change: Optional[Callable] = None
    on_long_click: Optional[Callable] = None
    link_alias: Optional[str] = None


@dataclasses.dataclass
class Input:
    key: str
    text: str
    default: Optional[str] = None
    subtext: Optional[str] = None
    icon: Optional[str] = None
    on_change: Optional[Callable] = None
    on_long_click: Optional[Callable] = None
    link_alias: Optional[str] = None


@dataclasses.dataclass
class Text:
    text: str
    subtext: Optional[str] = None
    icon: Optional[str] = None
    accent: bool = False
    red: bool = False
    on_click: Optional[Callable] = None
    on_long_click: Optional[Callable] = None
    create_sub_fragment: Optional[Callable] = None
    link_alias: Optional[str] = None


@dataclasses.dataclass
class EditText:
    key: str
    hint: str
    default: str = ""
    multiline: bool = False
    max_length: Optional[int] = None
    mask: Optional[str] = None
    on_change: Optional[Callable] = None


@dataclasses.dataclass
class Slider:
    key: str
    text: str
    default: float = 0
    min: float = 0
    max: float = 100
    step: float = 1
    subtext: Optional[str] = None
    icon: Optional[str] = None
    on_change: Optional[Callable] = None
    on_long_click: Optional[Callable] = None
    link_alias: Optional[str] = None


class BulletinHelper:
    @staticmethod
    def show_success(t):
        BULLETINS.append(("ok", t))

    @staticmethod
    def show_error(t):
        BULLETINS.append(("error", t))

    @staticmethod
    def show_info(t):
        BULLETINS.append(("info", t))


class AlertDialogBuilder:
    def __init__(self, context=None, *a, **k):
        self.d = {"title": None, "message": None, "buttons": {}}

    def set_title(self, t):
        self.d["title"] = t
        return self

    def set_message(self, m):
        self.d["message"] = m
        return self

    def set_positive_button(self, t, cb):
        self.d["buttons"]["positive"] = (t, cb)
        return self

    def set_negative_button(self, t, cb):
        self.d["buttons"]["negative"] = (t, cb)
        return self

    def set_neutral_button(self, t, cb):
        self.d["buttons"]["neutral"] = (t, cb)
        return self

    def show(self):
        DIALOGS.append(self.d)
        return self


class _Fragment:
    def getParentActivity(self):
        return object()


def get_last_fragment():
    return _Fragment()


class InstanceProxy:
    def __init__(self, host, port, login, password):
        self.host, self.port, self.login, self.password = host, port, login, password


class Browser:
    opened = []

    @staticmethod
    def openUrl(ctx, url):
        Browser.opened.append(url)


CLASSES = {
    "org.telegram.messenger.SharedConfig$ProxyInfo": ProxyInfo,
    "org.telegram.messenger.voip.Instance": type("Instance", (), {}),
    "org.telegram.messenger.voip.Instance$Proxy": InstanceProxy,
    "org.telegram.messenger.browser.Browser": Browser,
    "by.aprelteam.plugins.PluginsController": PluginsController,
    "com.exteragram.messenger.plugins.PluginsController": PluginsController,
}


def find_class(name):
    return CLASSES.get(name)


def _install_modules():
    def mod(name, **attrs):
        m = types.ModuleType(name)
        m.__dict__.update(attrs)
        sys.modules[name] = m
        return m
    mod("base_plugin", BasePlugin=BasePlugin, MethodHook=MethodHook, AppEvent=AppEvent,
        MenuItemData=MenuItemData, MenuItemType=MenuItemType)
    mod("android_utils", log=_sdk_log, run_on_ui_thread=run_on_ui_thread, copy_to_clipboard=copy_to_clipboard)
    ui = mod("ui")
    ui.settings = mod("ui.settings", Header=Header, Switch=Switch, Selector=Selector, Input=Input, Text=Text,
                      Divider=Divider, EditText=EditText, Slider=Slider)
    ui.bulletin = mod("ui.bulletin", BulletinHelper=BulletinHelper)
    ui.alert = mod("ui.alert", AlertDialogBuilder=AlertDialogBuilder)
    mod("hook_utils", find_class=find_class)
    mod("client_utils", get_last_fragment=get_last_fragment)
    mod("org")
    mod("org.telegram")
    mod("org.telegram.messenger", ApplicationLoader=ApplicationLoader, SharedConfig=SharedConfig)
    mod("android")
    mod("android.os", Build=Build, Looper=Looper)
    mod("java")
    mod("java.util", Locale=Locale)
    mod("java.lang", System=System)


_install_modules()


def load(path=PLUGIN_PATH, name="tropa_plugin"):
    """Import the built plugin file as a module (like Aprel's loader does)."""
    import importlib.machinery
    loader = importlib.machinery.SourceFileLoader(name, path)
    spec = importlib.util.spec_from_loader(name, loader)
    m = importlib.util.module_from_spec(spec)
    loader.exec_module(m)
    return m


# ============================================================ fake cores
def padded_core(src_name, dst_path, pad=(1 << 20) + 4096):
    """Copy a fake core and pad it past the plugin's 1 MB sanity limit (trailing bytes are ignored by dlopen)."""
    shutil.copyfile(os.path.join(FAKECORE_DIR, src_name), dst_path)
    with open(dst_path, "ab") as f:
        f.write(b"\0" * pad)
    return dst_path


def core_env(**extra):
    d = os.path.join(WORK, "fakecore")
    os.makedirs(d, exist_ok=True)
    os.environ["FAKECORE_DIR"] = d
    os.environ["FAKECORE_BIN"] = SING_BOX
    for k, v in extra.items():
        os.environ[k] = v
    return d


def wait_for(cond, timeout=10.0, step=0.05):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return True
        time.sleep(step)
    return cond()


def settings_tree(items, depth=0):
    """Flatten settings items, opening sub-fragments (to exercise every page builder)."""
    out = []
    for it in items:
        out.append((depth, it))
        sub = getattr(it, "create_sub_fragment", None)
        if callable(sub) and depth < 2:
            out.extend(settings_tree(sub(), depth + 1))
    return out
