

CORE_CHANNELS = ("modern", "legacy")


class CoreManager:
    """Ядра на устройстве: новые подписанные сборки по умолчанию, legacy — по выбору или как запасной вариант.

    Каждая сборка хранится в своём файле (<тип>-<канал>.so), поэтому переключение типа ядра или
    канала не скачивает ничего повторно. Обновление уже загруженного в процесс ядра ставится
    рядом (.next) и применяется при следующем запуске Telegram."""

    def __init__(self, plugin):
        self.plugin = plugin
        self.runtime = CoreRuntime()
        self._dl_lock = threading.Lock()
        self.downloading = None          # (тип, канал), пока идёт загрузка
        self.update_pending = False
        self.last_error = ""
        try:
            self._migrate_v1()
        except Exception as e:
            _log(f"core migrate: {e}")

    # ---- файлы и метаданные ----
    def _dir(self):
        # getDir(<id плагина>) Aprel Gram считает собственной папкой плагина
        d = os.path.join(str(ApplicationLoader.applicationContext.getDir("tropa", 0)), "cores")
        os.makedirs(d, exist_ok=True)
        return d

    def path(self, core, channel):
        return os.path.join(self._dir(), f"{core}-{channel}.so")

    def _json_setting(self, key, default):
        try:
            data = json.loads(self.plugin.get_setting(key, "") or "null")
        except Exception:
            data = None
        return data if isinstance(data, type(default)) else default

    def _meta_all(self):
        return self._json_setting("core_meta2", {})

    def meta(self, core, channel):
        info = self._meta_all().get(f"{core}:{channel}")
        try:
            p = self.path(core, channel)
            if isinstance(info, dict) and os.path.exists(p):
                size = os.path.getsize(p)
                if size > (1 << 20) and (not info.get("size") or int(info["size"]) == size):
                    return info
        except Exception:
            pass
        return None

    def _set_meta(self, core, channel, info):
        data = self._meta_all()
        if info is None:
            data.pop(f"{core}:{channel}", None)
        else:
            data[f"{core}:{channel}"] = dict(info, core=core, channel=channel)
        self.plugin.set_setting("core_meta2", json.dumps(data), reload_settings=False)

    def _nexts(self):
        return self._json_setting("core_next", {})

    def _set_next(self, core, channel, info):
        data = self._nexts()
        if info is None:
            data.pop(f"{core}:{channel}", None)
        else:
            data[f"{core}:{channel}"] = dict(info, core=core, channel=channel)
        self.plugin.set_setting("core_next", json.dumps(data), reload_settings=False)

    def _migrate_v1(self):
        """Tropa 0.1 хранил одно ядро каждого типа в <тип>.so, без разделения на каналы."""
        old = self._json_setting("core_meta", {})
        if not old:
            return
        for core, info in old.items():
            if core not in CORE_TYPES or not isinstance(info, dict):
                continue
            ch = info.get("channel") if info.get("channel") in CORE_CHANNELS else "legacy"
            src, dst = os.path.join(self._dir(), f"{core}.so"), self.path(core, ch)
            if os.path.exists(src) and not os.path.exists(dst):
                os.replace(src, dst)
            if os.path.exists(dst) and not self.meta(core, ch):
                self._set_meta(core, ch, dict(info, size=os.path.getsize(dst)))
            for leftover in (src, src + ".next", src + ".new"):
                try:
                    if os.path.exists(leftover):
                        os.remove(leftover)
                except Exception:
                    pass
        self.plugin.set_setting("core_meta", "", reload_settings=False)
        self.plugin.set_setting("core_staged", "", reload_settings=False)
        _log("cores migrated from Tropa 0.1 layout")

    # ---- каналы ----
    def modern_supported(self):
        try:
            sdk = int(Build.VERSION.SDK_INT)
            abis = [str(a) for a in _jlist(Build.SUPPORTED_ABIS)]
        except Exception:
            sdk, abis = 0, []
        return sdk >= CORE_MIN_ANDROID and bool(abis) and abis[0] == CORE_ABI and ctypes.sizeof(ctypes.c_void_p) == 8

    def user_channel(self):
        if bool(self.plugin.get_setting("core_legacy", False)) or not self.modern_supported():
            return "legacy"
        return "modern"

    def modern_bad(self, core):
        rec = self._json_setting("core_modern_bad", {}).get(core)
        return rec if isinstance(rec, dict) else None

    def mark_modern_bad(self, core, info, err, probe=None):
        data = self._json_setting("core_modern_bad", {})
        data[core] = {"tag": str((info or {}).get("tag") or ""), "err": str(err or "")[:2000], "ts": int(time.time()),
                      "probe": list(probe or [])}
        self.plugin.set_setting("core_modern_bad", json.dumps(data), reload_settings=False)
        _log(f"modern {core} core disabled after: {_short(err, 300)}")

    def clear_modern_bad(self, core=None):
        data = self._json_setting("core_modern_bad", {})
        if core is None:
            data = {}
        else:
            data.pop(core, None)
        self.plugin.set_setting("core_modern_bad", json.dumps(data), reload_settings=False)

    def channel(self, core):
        """Канал, который реально используется: выбор пользователя, но без сборки, которая уже падала."""
        ch = self.user_channel()
        if ch == "modern":
            bad = self.modern_bad(core)
            if bad:
                have = self.meta(core, "modern")
                if have is None or not bad.get("tag") or have.get("tag") == bad.get("tag"):
                    return "legacy"
        return ch

    def label(self, core, info=None, channel=None):
        title = CORE_TITLES.get(core, core)
        if info is None:
            info = self.meta(core, channel or self.channel(core))
        if not info:
            return f"{title} · {T('core_none')}"
        if info.get("channel") == "modern":
            return f"{title} {info.get('version') or ''}".strip() + f" · {T('core_ch_new')}"
        return f"{title} · {T('core_ch_legacy')}"

    # ---- загрузка и установка ----
    def _download(self, core, channel, dest, progress=None):
        if channel == "modern":
            tag = latest_core_tag(core)
            man, err = fetch_core_manifest(core, tag)
            if man is None and tag != CORE_PINNED[core]:
                _log(f"core {tag}: {err}; trying pinned release")
                man, err = fetch_core_manifest(core, CORE_PINNED[core])
            if man is None:
                self.last_error = f"modern {core}: {err}"
                _log(self.last_error)
                return None
            sha = download_file([man["url"]], dest, man["sha256"], man["size"], progress)
            if not sha:
                self.last_error = f"modern {core}: download failed"
                return None
            return {"core": core, "channel": "modern", "tag": man["tag"], "version": man["version"],
                    "sha256": sha, "api": 2, "size": man["size"]}
        sha = download_file(LEGACY_CORE_URLS[core], dest, None, None, progress)
        if not sha:
            self.last_error = f"legacy {core}: download failed"
            return None
        return {"core": core, "channel": "legacy", "tag": "", "version": "", "sha256": sha, "api": 1,
                "size": os.path.getsize(dest)}

    def _promote_next(self, core, channel):
        """Поставить заранее скачанное обновление, если старая версия ещё не загружена в процесс."""
        key = f"{core}:{channel}"
        rec = self._nexts().get(key)
        nxt = self.path(core, channel) + ".next"
        if not rec:
            if os.path.exists(nxt):
                try:
                    os.remove(nxt)
                except Exception:
                    pass
            return False
        cur = self.meta(core, channel)
        if cur and self.runtime.is_loaded(cur.get("sha256")):
            return False
        ok = os.path.exists(nxt) and file_sha256(nxt) == rec.get("sha256")
        if ok:
            os.replace(nxt, self.path(core, channel))
            self._set_meta(core, channel, rec)
            if channel == "modern":
                self.clear_modern_bad(core)
            _log(f"core update applied: {core} {channel} {rec.get('tag') or ''}".strip())
        else:
            try:
                if os.path.exists(nxt):
                    os.remove(nxt)
            except Exception:
                pass
        self._set_next(core, channel, None)
        return ok

    def ensure_installed(self, core, channel, progress=None):
        """Вернуть сведения об установленной сборке, скачав её при необходимости."""
        have = self.meta(core, channel)
        if have:
            return have
        with self._dl_lock:          # параллельный запрос дождётся уже идущей загрузки
            self._promote_next(core, channel)
            have = self.meta(core, channel)
            if have:
                return have
            self.downloading = (core, channel)
            try:
                info = self._download(core, channel, self.path(core, channel), progress)
            finally:
                self.downloading = None
            if info:
                self._set_meta(core, channel, info)
                if channel == "modern":
                    bad = self.modern_bad(core)
                    if bad and bad.get("tag") != info.get("tag"):
                        self.clear_modern_bad(core)
            return info

    def promote_all(self, core=None):
        """Применить скачанные заранее обновления (те, чьи старые версии не загружены в процесс)."""
        for c in ([core] if core else CORE_TYPES):
            for ch in CORE_CHANNELS:
                try:
                    self._promote_next(c, ch)
                except Exception as e:
                    _log(f"core update apply: {e}")

    def wanted(self, core):
        """Какую сборку (core, channel) нужно запустить для выбранного ядра, с учётом отметки «падает»."""
        return core, self.channel(core)

    def needs_restart_for(self, core):
        """Нужен ли перезапуск клиента, чтобы запустить выбранное ядро (в процесс загружено другое)."""
        c, ch = self.wanted(core)
        info = self.meta(c, ch)
        sha = info.get("sha256") if info else None
        if sha is None:
            # ещё не скачано: если ничего не загружено — скачаем и запустим без перезапуска
            return self.runtime.loaded_key() is not None
        return not self.runtime.can_activate(sha)

    def prepare(self, core, progress=None, channel=None):
        """Скачать (если нужно) и загрузить ядро нужного канала. -> (info | None, текст ошибки).
        Если в процесс уже загружено другое ядро, текст ошибки = T('core_need_restart')
        и info = None: вызывающий предлагает перезапуск, второе Go-ядро не грузится."""
        self.promote_all(core)        # новая сборка может снять отметку «падает» с нового канала
        channel = channel or self.channel(core)
        # нельзя грузить вторую сборку: если уже загружена другая, нужен перезапуск
        have = self.meta(core, channel)
        if have and not self.runtime.can_activate(have.get("sha256")):
            return None, T("core_need_restart")
        if have is None and self.runtime.loaded_key() is not None:
            # нужная сборка не скачана, а в процессе уже другое ядро — скачивать смысла нет
            return None, T("core_need_restart")
        info = self.ensure_installed(core, channel, progress)
        if info is None and channel == "modern":
            if self.runtime.loaded_key() is not None:
                return None, T("core_need_restart")
            _log(f"modern {core} core unavailable, using legacy")
            info = self.ensure_installed(core, "legacy", progress)
        if info is None:
            return None, self.last_error or T("core_dl_fail")
        ch = info.get("channel") or channel
        try:
            status = self.runtime.activate(self.path(core, ch), info)
        except CoreSwitchNeedsRestart as e:
            _log(f"core switch needs restart: {e}")
            return None, T("core_need_restart")
        except Exception as e:
            _log(f"core load failed: {e}")
            return None, f"load {core} {ch}: {e}"
        if status == "stuck":
            return None, T("core_stuck")
        return info, ""

    def check_updates(self, core, force=False, quiet=False):
        """Проверить обновление сборки выбранного канала. Возвращает текст для пользователя или ''."""
        channel = self.user_channel()
        have = self.meta(core, channel)
        if not force:
            last = int(self.plugin.get_setting("core_check_ts", 0) or 0)
            if time.time() - last < CORE_CHECK_INTERVAL:
                return ""
        self.plugin.set_setting("core_check_ts", int(time.time()), reload_settings=False)
        if channel == "modern":
            tag = latest_core_tag(core)
            if have:
                cur, new = _tag_order(have.get("tag")), _tag_order(tag)
                if cur and (not new or new <= cur):
                    return "" if quiet else T("core_uptodate")
            nxt = self._nexts().get(f"{core}:modern")
            if nxt and nxt.get("tag") == tag:
                return T("core_staged", name=self.label(core, nxt))
        elif have and not force:
            return ""
        if not have and not force:
            return ""     # ещё не скачано — скачается при подключении
        if not force and self.plugin._network_metered():
            self.update_pending = True
            return T("core_metered")
        if not self._dl_lock.acquire(False):
            return T("core_busy")
        try:
            loaded = bool(have) and self.runtime.is_loaded(have.get("sha256"))
            dest = self.path(core, channel) + (".next" if loaded else ".new")
            self.downloading = (core, channel)
            try:
                info = self._download(core, channel, dest)
            finally:
                self.downloading = None
            if not info:
                return T("core_dl_fail")
            self.update_pending = False
            if have and info.get("sha256") == have.get("sha256"):
                try:
                    os.remove(dest)
                except Exception:
                    pass
                return "" if quiet else T("core_uptodate")
            if loaded:
                self._set_next(core, channel, info)
                return T("core_staged", name=self.label(core, info))
            os.replace(dest, self.path(core, channel))
            self._set_meta(core, channel, info)
            if channel == "modern":
                self.clear_modern_bad(core)
            return T("core_ready", name=self.label(core, info))
        finally:
            self._dl_lock.release()

    def summary_lines(self):
        """Строки для отчёта: что установлено, что загружено в процесс, что отключено."""
        out = []
        loaded = {i.get("sha256") for i in self.runtime.loaded()}
        running = (self.runtime.running_info() or {}).get("sha256")
        for core in CORE_TYPES:
            for ch in CORE_CHANNELS:
                m = self.meta(core, ch)
                if not m:
                    continue
                flags = []
                if m.get("sha256") in loaded:
                    flags.append("loaded")
                if m.get("sha256") == running:
                    flags.append("running")
                out.append(f"{core}/{ch}: {m.get('tag') or m.get('version') or 'build'} "
                           f"sha={str(m.get('sha256'))[:12]} {' '.join(flags)}".strip())
            bad = self.modern_bad(core)
            if bad:
                out.append(f"{core}/modern disabled ({bad.get('tag')}): {_short(bad.get('err'), 400)}")
                for line in bad.get("probe") or []:
                    out.append(f"  probe {line}")
        return out or ["no cores installed"]
