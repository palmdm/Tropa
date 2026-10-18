

# ===========================================================================
# Ядра: загрузка, проверка подписи, установка и запуск
# ===========================================================================
CORE_RELEASES_API = "https://api.github.com/repos/itsv1eds/exitFy/releases?per_page=30"
CORE_DL_BASE = "https://github.com/itsv1eds/exitFy/releases/download"
CORE_ABI = "arm64-v8a"
CORE_MIN_ANDROID = 29
CORE_FAMILIES = {
    CORE_SINGBOX: {"prefix": "sb-v", "family": "sing_box", "asset": "libexitfy-sb-arm64-v8a.so"},
    CORE_XRAY: {"prefix": "xray-v", "family": "xray", "asset": "libxray-arm64-v8a.so"},
}
# Проверенные релизы на случай недоступности GitHub API (подпись проверяется всё равно)
CORE_PINNED = {CORE_SINGBOX: "sb-v1.13.20-w4079", CORE_XRAY: "xray-v26.7.28-w10110"}
# Открытый ключ сборщика ядер (ECDSA P-256), опубликован в исходниках сборок
CORE_SIGNER = (0x4206305ba416f256936411dc51eb1d15721f9edf95be7cab5c98eadbfabe02c2,
               0x3e345813dfc5e44f98234f7a8f3c5093ff1487e788ec98c7a3adb68d900e6801)
LEGACY_CORE_URLS = {
    CORE_SINGBOX: ["https://github.com/itsv1eds/itsv1eds/releases/download/lib_singbox/libvless-arm64-v8a.so"],
    CORE_XRAY: ["https://github.com/itsv1eds/itsv1eds/releases/download/lib/libvless-arm64-v8a.so",
                "https://github.com/itsv1eds/itsv1eds/releases/download/lib/libvless.so"],
}
GH_MIRRORS = ("https://ghfast.top/", "https://gh-proxy.com/", "https://ghproxy.net/")
CORE_CHECK_INTERVAL = 24 * 3600

# ---- ECDSA P-256 / SHA-256 на чистом Python -----------------------------------
_P = 0xffffffff00000001000000000000000000000000ffffffffffffffffffffffff
_N = 0xffffffff00000000ffffffffffffffffbce6faada7179e84f3b9cac2fc632551
_B = 0x5ac635d8aa3a93e7b3ebbd55769886bc651d06b0cc53b0f63bce3c3e27d2604b
_G = (0x6b17d1f2e12c4247f8bce6e563a440f277037d812deb33a0f4a13945d898c296,
      0x4fe342e2fe1a7f9b8ee7eb4a7c0f9e162bce33576b315ececbb6406837bf51f5)


def _jac_double(pt):
    if pt is None or pt[1] == 0:
        return None
    x, y, z = pt
    d = z * z % _P
    g = y * y % _P
    b = x * g % _P
    a = 3 * (x - d) * (x + d) % _P
    x3 = (a * a - 8 * b) % _P
    z3 = ((y + z) * (y + z) - g - d) % _P
    y3 = (a * (4 * b - x3) - 8 * g * g) % _P
    return (x3, y3, z3)


def _jac_add(p1, p2):
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    x1, y1, z1 = p1
    x2, y2, z2 = p2
    z1s, z2s = z1 * z1 % _P, z2 * z2 % _P
    u1, u2 = x1 * z2s % _P, x2 * z1s % _P
    s1, s2 = y1 * z2 * z2s % _P, y2 * z1 * z1s % _P
    if u1 == u2:
        return _jac_double(p1) if s1 == s2 else None
    h = (u2 - u1) % _P
    i = 4 * h * h % _P
    j = h * i % _P
    r = 2 * (s2 - s1) % _P
    v = u1 * i % _P
    x3 = (r * r - j - 2 * v) % _P
    y3 = (r * (v - x3) - 2 * s1 * j) % _P
    z3 = ((z1 + z2) * (z1 + z2) - z1s - z2s) * h % _P
    return (x3, y3, z3)


def _scalar_mult(k, point):
    acc, base = None, (point[0], point[1], 1)
    for bit in bin(k)[2:]:
        acc = _jac_double(acc)
        if bit == "1":
            acc = _jac_add(acc, base)
    return acc


def _der_ints(sig):
    def read_len(pos):
        n = sig[pos]
        if n < 0x80:
            return n, pos + 1
        k = n & 0x7F
        return int.from_bytes(sig[pos + 1:pos + 1 + k], "big"), pos + 1 + k
    if len(sig) < 8 or sig[0] != 0x30:
        raise ValueError("not DER")
    _, pos = read_len(1)
    out = []
    for _ in range(2):
        if sig[pos] != 0x02:
            raise ValueError("not DER integer")
        ln, pos = read_len(pos + 1)
        out.append(int.from_bytes(sig[pos:pos + ln], "big"))
        pos += ln
    return out


def ecdsa_verify(message, signature, pubkey=CORE_SIGNER):
    try:
        r, s = _der_ints(bytes(signature))
        if not (0 < r < _N and 0 < s < _N):
            return False
        qx, qy = pubkey
        if (qy * qy - (qx ** 3 - 3 * qx + _B)) % _P:
            return False
        e = int.from_bytes(hashlib.sha256(bytes(message)).digest(), "big")
        w = pow(s, -1, _N)
        pt = _jac_add(_scalar_mult(e * w % _N, _G), _scalar_mult(r * w % _N, pubkey))
        if pt is None:
            return False
        zi = pow(pt[2], -1, _P)
        return pt[0] * zi * zi % _P % _N == r
    except Exception:
        return False


# ---- сеть ---------------------------------------------------------------------
def _gh_variants(url):
    return [url] + [m + url for m in GH_MIRRORS] if url.startswith("https://github.com/") else [url]


def _get_small(url, limit=512 * 1024):
    for u in _gh_variants(url):
        try:
            r = requests.get(u, timeout=(8, 20), headers={"User-Agent": "Tropa"})
            if r.status_code == 200 and r.content and len(r.content) <= limit:
                return r.content
        except Exception:
            continue
    return None


def _tag_order(tag):
    m = re.match(r"^(?:sb|xray)-v(\d+(?:\.\d+)*)-w(\d+)$", str(tag or ""))
    return (tuple(int(x) for x in m.group(1).split(".")), int(m.group(2))) if m else None


def latest_core_tag(core):
    fam = CORE_FAMILIES[core]
    best = CORE_PINNED[core]
    best_key = _tag_order(best)
    try:
        r = requests.get(CORE_RELEASES_API, timeout=(8, 15),
                         headers={"Accept": "application/vnd.github+json", "User-Agent": "Tropa"})
        if r.status_code == 200:
            for rel in r.json() or []:
                if not isinstance(rel, dict) or rel.get("draft") or rel.get("prerelease"):
                    continue
                tag = str(rel.get("tag_name") or "")
                key = _tag_order(tag)
                names = {str(a.get("name") or "") for a in rel.get("assets") or [] if isinstance(a, dict)}
                if tag.startswith(fam["prefix"]) and key and {"manifest.json", "manifest.json.sig", fam["asset"]} <= names:
                    if key > best_key:
                        best, best_key = tag, key
    except Exception:
        pass
    return best


def fetch_core_manifest(core, tag):
    """Подписанный manifest.json релиза -> сведения о файле ядра; иначе (None, причина)."""
    fam = CORE_FAMILIES[core]
    base = f"{CORE_DL_BASE}/{tag}"
    raw, sig = _get_small(base + "/manifest.json"), _get_small(base + "/manifest.json.sig", 4096)
    if not raw or not sig:
        return None, "manifest unavailable"
    if not ecdsa_verify(raw, sig):
        return None, "bad manifest signature"
    try:
        man = json.loads(raw.decode("utf-8"))
        asset = (man.get("assets") or {}).get(CORE_ABI) or {}
        sha = str(asset.get("sha256") or "").lower()
        try:
            sdk = int(Build.VERSION.SDK_INT)
        except Exception:
            sdk = 0
        ok = (man.get("schema") == 3 and man.get("coreApi") == 2 and man.get("configContract") == 1
              and man.get("family") == fam["family"] and man.get("releaseTag") == tag
              and int(man.get("minAndroidApi", 99)) <= sdk and asset.get("name") == fam["asset"]
              and {"StartCore", "StopCore"} <= set(asset.get("exports") or [])
              and re.fullmatch(r"[0-9a-f]{64}", sha) is not None and int(asset.get("size", 0)) > (1 << 20))
        if not ok:
            return None, "unsupported manifest"
        return {"url": f"{base}/{asset['name']}", "sha256": sha, "size": int(asset["size"]), "tag": tag,
                "version": str((man.get("upstream") or {}).get("tag") or "").lstrip("v")}, ""
    except Exception as e:
        return None, f"manifest error: {e}"


def _elf_ok(path):
    try:
        with open(path, "rb") as f:
            head = f.read(20)
        return head[:4] == b"\x7fELF" and head[4] == 2 and struct.unpack_from("<H", head, 18)[0] == 183
    except Exception:
        return False


def download_file(urls, dest, expect_sha=None, expect_size=None, progress=None):
    """Скачать первую доступную копию; принять только целый ELF arm64 с нужным SHA-256/размером.
    Зеркала GitHub используются только для файлов с известным SHA-256 (подписанный манифест):
    непроверяемый файл через чужое зеркало могли бы подменить."""
    tmp = dest + ".part"
    for base_url in urls:
        for url in (_gh_variants(base_url) if expect_sha else [base_url]):
            try:
                r = requests.get(url, stream=True, timeout=(8, 30), headers={"User-Agent": "Tropa"})
                if r.status_code != 200:
                    continue
                total = int(expect_size or r.headers.get("content-length") or 0)
                h, done = hashlib.sha256(), 0
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(65536):
                        if not chunk:
                            continue
                        done += len(chunk)
                        if expect_size and done > expect_size:
                            break
                        f.write(chunk)
                        h.update(chunk)
                        if progress and total:
                            progress(min(1.0, done / float(total)))
                if expect_size and done != expect_size:
                    continue
                if expect_sha and h.hexdigest() != expect_sha:
                    _log(f"hash mismatch from {url}")
                    continue
                if done < (1 << 20) or not _elf_ok(tmp):
                    continue
                os.replace(tmp, dest)
                return h.hexdigest()
            except Exception as e:
                _log(f"download {url}: {e}")
            finally:
                try:
                    if os.path.exists(tmp):
                        os.remove(tmp)
                except Exception:
                    pass
    return None


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---- загрузка библиотеки в процесс ---------------------------------------------
class _DlextInfo(ctypes.Structure):
    _fields_ = [("flags", ctypes.c_uint64), ("reserved_addr", ctypes.c_void_p), ("reserved_size", ctypes.c_size_t),
                ("relro_fd", ctypes.c_int), ("library_fd", ctypes.c_int), ("library_fd_offset", ctypes.c_int64),
                ("library_namespace", ctypes.c_void_p)]


_DLEXT_USE_LIBRARY_FD = 0x10
_RTLD_NOW = 2
_PROCESS_STATE_KEY = "_tropa_core_process_v2"
_PROCESS_STATE_V1 = "_tropa_core_process_state"   # Tropa 0.1 в том же процессе


def _dlopen(path):
    """Загрузить библиотеку ядра локально (RTLD_NOW без RTLD_GLOBAL): символы разных ядер не смешиваются."""
    try:
        libdl = ctypes.CDLL("libdl.so")
        fn = libdl.android_dlopen_ext
        fn.restype = ctypes.c_void_p
        fn.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.POINTER(_DlextInfo)]
        fd = os.open(path, os.O_RDONLY)
        try:
            info = _DlextInfo(flags=_DLEXT_USE_LIBRARY_FD, library_fd=fd)
            handle = fn(path.encode("utf-8"), _RTLD_NOW, ctypes.byref(info))
        finally:
            os.close(fd)
        if handle:
            return ctypes.CDLL(path, handle=handle)
    except Exception as e:
        _log(f"android_dlopen_ext unavailable: {e}")
    return ctypes.CDLL(path, mode=_RTLD_NOW)


_FREE = []


def _take_c_string(ptr):
    """Строка, которую вернуло ядро (malloc), -> str; память освобождаем."""
    if not ptr:
        return ""
    try:
        return ctypes.string_at(ptr).decode("utf-8", "replace")
    finally:
        try:
            if not _FREE:
                free = ctypes.CDLL(None).free
                free.argtypes = [ctypes.c_void_p]
                free.restype = None
                _FREE.append(free)
            _FREE[0](ctypes.c_void_p(ptr))
        except Exception:
            pass


class _NativeCore:
    """Библиотека ядра: StartCore(char*) -> NULL или строка ошибки; StopCore() (api 2 тоже возвращает строку)."""

    def __init__(self, lib, api):
        self.lib, self.api = lib, int(api or 1)
        lib.StartCore.argtypes = [ctypes.c_char_p]
        lib.StartCore.restype = ctypes.c_void_p
        lib.StopCore.argtypes = []
        lib.StopCore.restype = ctypes.c_void_p if self.api >= 2 else None

    def start(self, payload):
        return _take_c_string(self.lib.StartCore(payload))

    def stop(self):
        res = self.lib.StopCore()
        return _take_c_string(res) if isinstance(res, int) else ""


def _open_native(path, info):
    return _NativeCore(_dlopen(path), info.get("api", 1))


def _process_state():
    """Состояние, общее для всех перезагрузок плагина внутри одного процесса Telegram.

    Ключевое ограничение: в процесс загружается не больше одного Go-ядра за всё время его жизни.
    Два Go-рантайма в одном процессе конфликтуют по обработчикам сигналов и могут уронить клиент
    (это и была причина падений при переключении ядер), поэтому смена ядра идёт через перезапуск."""
    import sys
    import types
    st = sys.modules.get(_PROCESS_STATE_KEY)
    if st is not None and getattr(st, "pid", None) == os.getpid():
        return st
    st = types.ModuleType(_PROCESS_STATE_KEY)
    st.pid, st.lock = os.getpid(), threading.RLock()
    st.core = None        # единственный _NativeCore на процесс
    st.key = None         # sha256 загруженной библиотеки
    st.info = None        # сведения о загруженной сборке
    st.running = False    # запущено ли ядро сейчас (был StartCore без StopCore)
    st.stuck = False      # StartCore завис — библиотека заблокирована до перезапуска
    # перенос из Tropa 0.1 (та же единственная библиотека в этом же процессе)
    old = sys.modules.get(_PROCESS_STATE_V1)
    if old is not None and getattr(old, "pid", None) == os.getpid() and getattr(old, "lib", None) is not None:
        info = dict(getattr(old, "info", None) or {})
        try:
            st.core = _NativeCore(old.lib, info.get("api", 1))
            st.key = str(info.get("sha256") or "tropa-0.1")
            st.info, st.running = info, True
        except Exception:
            pass
    sys.modules[_PROCESS_STATE_KEY] = st
    return st


def core_crashed(err):
    """Ошибка самого ядра (паника, зависание, сбой вызова), а не конфига или сервера."""
    s = str(err or "").lower()
    return "panic" in s or "startcore failed" in s or "startcore timeout" in s or "stuck" in s


class CoreSwitchNeedsRestart(Exception):
    """В процесс уже загружено другое ядро; выбранное применится только после перезапуска клиента."""


class CoreRuntime:
    """Одно Go-ядро на процесс Telegram.

    Выгрузить нативную библиотеку нельзя, а два Go-рантайма в одном процессе роняют клиент,
    поэтому первая выбранная сборка загружается и остаётся единственной. Любое другое ядро
    (другой тип, канал или версия) применяется только после перезапуска клиента."""

    opener = staticmethod(_open_native)

    def __init__(self):
        self.state = _process_state()

    def is_loaded(self, sha):
        return bool(sha) and self.state.key == sha

    def loaded(self):
        st = self.state
        return [dict(st.info)] if st.info else []

    def current_info(self):
        return dict(self.state.info) if self.state.info else None

    # running_info и current_info совпадают: ядро в процессе всегда одно
    running_info = current_info

    def loaded_key(self):
        return self.state.key

    def can_activate(self, sha):
        """Можно ли запустить эту сборку без перезапуска клиента."""
        return self.state.key is None or self.state.key == str(sha)

    def activate(self, path, info):
        """Загрузить сборку в процесс, если ядро ещё не загружено. -> 'ok' | 'stuck'.
        Если загружено другое ядро — CoreSwitchNeedsRestart (второе Go-ядро не грузим)."""
        key = str(info.get("sha256") or path)
        with self.state.lock:
            if self.state.key is None:
                self.state.core = type(self).opener(path, info)
                self.state.key, self.state.info = key, dict(info)
                _log(f"core loaded: {info.get('core', '?')} {info.get('channel', '?')} {info.get('tag') or ''}".strip())
            elif self.state.key != key:
                raise CoreSwitchNeedsRestart(
                    f"loaded {self.state.info and self.state.info.get('core')}/"
                    f"{self.state.info and self.state.info.get('channel')}, need {info.get('core')}/{info.get('channel')}")
            return "stuck" if self.state.stuck else "ok"

    def _stop_locked(self):
        st = self.state
        st.running = False
        if st.core is None or st.stuck:
            return ""
        try:
            return st.core.stop() or ""
        except Exception as e:
            return f"StopCore failed: {e}"

    def stop(self):
        with self.state.lock:
            return self._stop_locked()

    stop_current = stop

    def start(self, config, timeout=15.0):
        with self.state.lock:
            st = self.state
            if st.core is None:
                return "core not loaded"
            if st.stuck:
                return "core is stuck after a StartCore timeout"
            self._stop_locked()
            payload = json.dumps(config).encode("utf-8")
            box = {}

            def run():
                try:
                    box["err"] = st.core.start(payload)
                except Exception as e:  # noqa: BLE001
                    box["err"] = f"StartCore failed: {e}"
            t = threading.Thread(target=run, daemon=True)
            t.start()
            t.join(float(timeout))
            if t.is_alive():
                st.stuck = True
                return "StartCore timeout"
            err = str(box.get("err") or "")
            if not err:
                st.running = True
            return err
