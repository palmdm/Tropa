

# ===========================================================================
# Плагин
# ===========================================================================
_STATE_ICONS = {"off": "msg_block", "starting": "msg_recent", "on": "msg_check", "paused": "settings_power",
                "error": "msg_info", "restart": "msg_retry"}
_STATE_LABELS = {"off": "st_off", "starting": "st_starting", "on": "st_on", "paused": "st_paused",
                 "error": "st_error", "restart": "st_restart"}
AUTO_BEST_MAX = 8
PORT_RANGE = (20000, 59999)


def _other_core(core):
    return CORE_XRAY if core == CORE_SINGBOX else CORE_SINGBOX


class TropaPlugin(BasePlugin):

    # ---------------------------------------------------------------- жизненный цикл
    def on_plugin_load(self):
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._session = None
        self._state, self._state_detail = "off", ""
        self._paused, self._pause_reason = False, ""
        self._testing, self._test_status = False, ""
        self._test_result = ("", "")          # (метод, итог) последнего быстрого теста
        self._test_cancel = threading.Event()
        self._prog = [0, 0, 0.0]
        self._parsed = {}
        self._ui_pending = False
        self._loaded_at = _now()
        self._dl_shown = 0.0
        self._call_hook = None
        self._menu_added = False
        self._pending_restart = ""        # причина ожидаемого перезапуска (смена ядра)
        self._refreshing = False
        self.store = self._store_load()
        if not self.get_setting("hwid", ""):
            self.set_setting("hwid", os.urandom(8).hex(), reload_settings=False)
        self.cores = CoreManager(self)
        self.tg = TelegramProxy(self)
        _log(f"Tropa {__version__} loaded")
        _bg(self._startup)

    def _startup(self):
        self.cores.promote_all()
        self._add_menu_items()
        self._install_call_hook()
        _bg(self._monitor_loop)
        _bg(self._watchdog_loop)
        if bool(self.get_setting("enabled", False)):
            self.connect("startup")
        else:
            self._cleanup_stale_proxy()
        src = self._source_data()
        if not src["nodes_count"] or time.time() - src["updated"] > 12 * 3600:
            self.refresh_source(notify=False)
            if self._session is None and bool(self.get_setting("enabled", False)) and not self._paused:
                self.connect("servers")
        if self._stop.wait(25):
            return
        try:
            msg = self.cores.check_updates(self._core(), quiet=True)
            if msg:
                self._notice(msg)
        except Exception as e:
            _log(f"core update check: {e}")
        self._reload_ui()

    def on_plugin_unload(self):
        self._stop.set()
        self._test_cancel.set()
        self._remove_menu_items()
        got = self._lock.acquire(True, 3.0)      # не ждать долгую загрузку ядра (возможно, мы на UI-потоке)
        try:
            self._teardown(restore=True)
        except Exception as e:
            _log(f"unload: {e}")
        finally:
            if got:
                self._lock.release()

    # ---------------------------------------------------------------- пункт в меню Telegram
    def _plugin_id(self):
        return str(getattr(self, "id", "") or getattr(self, "plugin_id", "") or __id__)

    def _add_menu_items(self):
        if self._menu_added or MenuItemData is None or MenuItemType is None:
            return
        pid = self._plugin_id()
        for menu in ("DRAWER_MENU", "CHAT_ACTION_MENU"):
            mtype = getattr(MenuItemType, menu, None)
            if mtype is None:
                continue
            try:
                self.add_menu_item(MenuItemData(
                    menu_type=mtype, item_id=f"tropa_settings_{menu.lower()}",
                    text=T("menu_open"), icon="msg_settings", priority=1,
                    on_click=lambda ctx, p=pid: open_plugin_settings(p)))
            except Exception as e:
                _log(f"add menu item {menu}: {e}")
        self._menu_added = True

    def _remove_menu_items(self):
        for menu in ("DRAWER_MENU", "CHAT_ACTION_MENU"):
            try:
                self.remove_menu_item(f"tropa_settings_{menu.lower()}")
            except Exception:
                pass
        self._menu_added = False

    def on_app_event(self, event_type):
        try:
            if AppEvent is not None and event_type == AppEvent.RESUME:
                _bg(self._on_resume)
        except Exception:
            pass

    def _on_resume(self):
        time.sleep(0.6)
        self._apply_rules()
        if bool(self.get_setting("enabled", False)) and self._session is None \
                and not self._paused and self._state != "starting":
            self.connect("resume")
        self._check_clipboard()

    # ---------------------------------------------------------------- хранилище
    def _store_load(self):
        try:
            data = json.loads(self.get_setting("store", "") or "{}")
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}
        data.setdefault("elix", {}).setdefault("nodes", [])
        data["elix"].setdefault("info", {})
        data["elix"].setdefault("updated", 0)
        own = data.setdefault("own", {})
        own.setdefault("subs", [])
        own.setdefault("keys", [])
        data.setdefault("active", {}).setdefault("elix", "")
        data["active"].setdefault("own", "")
        data.setdefault("pings", {})
        data.setdefault("clip_seen", "")
        return data

    def _store_save(self):
        try:
            pings = self.store.get("pings", {})
            if len(pings) > 2000:
                keep = sorted(pings.items(), key=lambda kv: kv[1].get("ts", 0), reverse=True)[:1500]
                self.store["pings"] = dict(keep)
            self.set_setting("store", json.dumps(self.store, ensure_ascii=False), reload_settings=False)
        except Exception as e:
            _log(f"store save: {e}")

    def _source(self):
        return "own" if int(self.get_setting("source", 0) or 0) == 1 else "elix"

    def _entries(self, source=None):
        src = source or self._source()
        if src == "elix":
            return list(self.store["elix"]["nodes"])
        out = []
        for sub in self.store["own"]["subs"]:
            out.extend(sub.get("nodes") or [])
        out.extend(self.store["own"]["keys"])
        return out

    def _source_data(self):
        if self._source() == "elix":
            e = self.store["elix"]
            return {"nodes_count": len(e["nodes"]), "updated": int(e.get("updated") or 0)}
        subs = self.store["own"]["subs"]
        upd = min([int(s.get("updated") or 0) for s in subs] or [int(time.time())])
        return {"nodes_count": len(self._entries("own")), "updated": upd}

    def _node(self, entry):
        uri = entry.get("uri", "")
        node = self._parsed.get(uri)
        if node is None:
            node = parse_link(uri)
            if node is None:
                return None
            if len(self._parsed) > 4000:
                self._parsed.clear()
            self._parsed[uri] = node
        if entry.get("name"):
            node = dict(node, name=entry["name"])
        return node

    def _unique(self, entries):
        out, seen = [], set()
        for e in entries:
            node = self._node(e)
            if not node:
                continue
            k = node_key(node)
            if k not in seen:
                seen.add(k)
                out.append((k, node))
        return out

    def _active_key(self):
        return self.store["active"].get(self._source(), "")

    def _ping(self, key):
        return self.store["pings"].get(key)

    def _ping_failed(self, key):
        p = self._ping(key)
        return bool(p) and isinstance(p.get("ms"), int) and p["ms"] <= 0

    # ---------------------------------------------------------------- настройки
    def _core(self):
        return CORE_XRAY if int(self.get_setting("core_type", 0) or 0) == 1 else CORE_SINGBOX

    def _int(self, key, default, lo, hi):
        try:
            v = int(round(float(self.get_setting(key, default))))
        except Exception:
            v = int(default)
        return max(lo, min(hi, v))

    def _ping_method(self):
        return PING_METHODS[self._int("ping_method", 0, 0, len(PING_METHODS) - 1)]

    def _ping_display(self):
        return PING_DISPLAYS[self._int("ping_display", 0, 0, len(PING_DISPLAYS) - 1)]

    def _ping_timeout(self):
        return self._int("ping_timeout", 3, 1, 10)

    def _ping_url(self):
        return normalize_url(self.get_setting("ping_url", PING_URL_DEFAULT))

    def _network_metered(self):
        try:
            cm = ApplicationLoader.applicationContext.getSystemService("connectivity")
            return bool(cm.isActiveNetworkMetered())
        except Exception:
            return True

    # ---------------------------------------------------------------- состояние, ошибки, отчёт
    def _set_state(self, state, detail=""):
        if state != "restart":
            self._pending_restart = ""
        self._state, self._state_detail = state, str(detail or "")
        self._reload_ui()

    def _save_error(self, short, full):
        try:
            rec = {"ts": int(time.time()), "short": _redact(short), "full": _redact(full or short)[:8000]}
            self.set_setting("last_error", json.dumps(rec, ensure_ascii=False), reload_settings=False)
        except Exception:
            pass

    def _fail(self, short, full=None):
        """Ошибка: короткий текст — в «Состояние», полный — в «Подробности ошибки» и отчёт."""
        full = str(full or short)
        self._save_error(short, full)
        _log(f"error: {_short(full, 600)}")
        self._set_state("error", short)

    def _last_error(self):
        try:
            rec = json.loads(self.get_setting("last_error", "") or "null")
        except Exception:
            rec = None
        return rec if isinstance(rec, dict) else None

    def _report(self, with_log=True):
        lines = [f"Tropa {__version__} · {time.strftime('%Y-%m-%d %H:%M:%S')}"]
        try:
            abis = ",".join(str(a) for a in _jlist(Build.SUPPORTED_ABIS))
            lines.append(f"Android {Build.VERSION.RELEASE} (SDK {Build.VERSION.SDK_INT}) · {abis}")
        except Exception:
            pass
        try:
            ctx = ApplicationLoader.applicationContext
            pkg = str(ctx.getPackageName())
            lines.append(f"{pkg} {ctx.getPackageManager().getPackageInfo(pkg, 0).versionName}")
        except Exception:
            pass
        lines.append(f"{T('state')}: {T(_STATE_LABELS.get(self._state, 'st_off'))}"
                     + (f" — {self._state_detail}" if self._state_detail else ""))
        core = self._core()
        lines.append(f"core: {core} · channel {self.cores.channel(core)} (chosen {self.cores.user_channel()})")
        try:
            lines += self.cores.summary_lines()
        except Exception as e:
            lines.append(f"cores: {e}")
        err = self._last_error()
        if err:
            when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(err.get("ts") or 0)))
            lines += ["", f"{T('diag_last_error')} ({when}):", str(err.get("full") or err.get("short") or "")]
        if with_log:
            lines += ["", "--- log ---"] + log_lines(150)
        return "\n".join(lines)

    def _show_details(self):
        brief = self._report(with_log=False)

        def show():
            try:
                if AlertDialogBuilder is None:
                    raise RuntimeError("no dialogs")
                frag = get_last_fragment() if get_last_fragment else None
                act = frag.getParentActivity() if frag is not None else None
                b = AlertDialogBuilder(act) if act is not None else AlertDialogBuilder()
                b.set_title(T("err_title"))
                b.set_message(brief + "\n\n" + T("diag_copy_hint"))
                b.set_positive_button(T("copy"), lambda *a: _copy_text(self._report(with_log=True)))
                b.set_neutral_button(T("diag_clear"), lambda *a: self._clear_diag())
                b.set_negative_button(T("close"), lambda *a: None)
                b.show()
            except Exception as e:
                _log(f"details dialog: {e}")
                _copy_text(self._report(with_log=True))
        _ui(show)

    def _clear_diag(self):
        clear_log()
        self.set_setting("last_error", "", reload_settings=False)
        if self._state == "error":
            self._set_state("off")
        _notify("info", T("diag_cleared"))
        self._reload_ui()

    def _reload_ui(self):
        if self._ui_pending:
            return
        self._ui_pending = True

        def do():
            self._ui_pending = False
            try:
                self.set_setting("_ui_tick", int(time.time() * 1000), reload_settings=True)
            except Exception:
                pass
        _ui(do)

    def _notice(self, text):
        if text and _now() - self._loaded_at > 8:
            _notify("info", text)

    def _notice_now(self, text):
        if text:
            _notify("info", text)

    # ---------------------------------------------------------------- локальный прокси для Telegram
    def _pick_port(self):
        rng = random.SystemRandom()
        for _ in range(60):
            port = rng.randint(*PORT_RANGE)
            if _port_free(port):
                return port
        return _free_port()

    def _endpoint(self, ensure_free=False):
        """Постоянные порт и логин локального прокси: запись в списке прокси Telegram всегда одна."""
        port = self._int("tg_port", 0, 0, 65535)
        user = str(self.get_setting("tg_user", "") or "")
        pwd = str(self.get_setting("tg_pass", "") or "")
        dirty = False
        if not 1024 <= port <= 65535:
            port, dirty = self._pick_port(), True
        if not (user.startswith(TG_USER_PREFIX) and len(user) >= len(TG_USER_PREFIX) + 8):
            user, dirty = TG_USER_PREFIX + _rand_token(10), True
        if len(pwd) < 16:
            pwd, dirty = _rand_token(24), True
        if ensure_free and not _port_free(port):
            deadline = _now() + 2.5            # своё ядро могло ещё не отпустить порт
            while _now() < deadline and not _port_free(port):
                time.sleep(0.1)
            if not _port_free(port):
                old, port, dirty = port, self._pick_port(), True
                _log(f"port {old} is busy, moved to {port}")
                self._notice_now(T("port_busy_moved", old=old, new=port))
        if dirty:
            self.set_setting("tg_port", int(port), reload_settings=False)
            self.set_setting("tg_port_in", str(port), reload_settings=False)
            self.set_setting("tg_user", user, reload_settings=False)
            self.set_setting("tg_pass", pwd, reload_settings=False)
        return int(port), user, pwd

    # ---------------------------------------------------------------- подключение
    def _rank(self, items):
        def score(item):
            p = self._ping(item[0])
            if p and isinstance(p.get("ms"), int) and p["ms"] > 0:
                return (0, p["ms"])
            if self._ping_failed(item[0]):
                return (2, 0)
            return (1, 0)
        return sorted(items, key=score)

    def _support_note(self, node):
        """'' — сервер работает с выбранным ядром; иначе подпись, с каким работает."""
        core = self._core()
        if node_supported(core, node):
            return ""
        other = _other_core(core)
        if node_supported(other, node):
            return T("server_needs", core=CORE_TITLES[other])
        return T("server_unsupported")

    def _switch_core(self, core):
        if core != self._core():
            self.set_setting("core_type", 1 if core == CORE_XRAY else 0, reload_settings=False)
            _log(f"core type switched to {core} for the selected server")
            self._notice_now(T("core_switched_for_server", core=CORE_TITLES[core]))

    def _connect_plan(self):
        """-> (ядро, узлы, подпись) или (None, [], причина). Ядро подбирается под выбранный сервер."""
        items = self._unique(self._entries())
        if not items:
            return None, [], T("no_servers")
        core, active = self._core(), self._active_key()
        if bool(self.get_setting("auto_best", False)) and len(items) > 1:
            pool = [it for it in items if node_supported(core, it[1])]
            if not pool:
                other = _other_core(core)
                pool = [it for it in items if node_supported(other, it[1])]
                core = other
            if not pool:
                return None, [], T("server_unsupported_all")
            ranked = self._rank(pool)
            good = [it for it in ranked if not self._ping_failed(it[0])] or ranked
            top = good[:AUTO_BEST_MAX]
            act = [it for it in pool if it[0] == active]
            if act and act[0] not in top:
                top = act + top[:AUTO_BEST_MAX - 1]
            self._switch_core(core)
            if len(top) > 1:
                return core, [n for _k, n in top], T("auto_best")
            return core, [top[0][1]], top[0][1]["name"]
        chosen = next((it for it in items if it[0] == active), None)
        if chosen is None:
            pool = [it for it in items if node_supported(core, it[1])] or items
            chosen = self._rank(pool)[0]
            self.store["active"][self._source()] = chosen[0]
            self._store_save()
        node = chosen[1]
        if not node_supported(core, node):
            other = _other_core(core)
            if not node_supported(other, node):
                return None, [], T("core_unsupported_node", core=CORE_TITLES[core])
            core = other
        self._switch_core(core)
        return core, [node], node["name"]

    def _download_progress(self, frac):
        now = _now()
        if frac < 1.0 and now - self._dl_shown < 0.7:
            return
        self._dl_shown = now
        dl = self.cores.downloading
        name = ""
        if dl:
            name = f"{CORE_TITLES.get(dl[0], dl[0])} {T('core_ch_new') if dl[1] == 'modern' else T('core_ch_legacy')}"
        self._set_state("starting", T("core_downloading_pct", name=name, pct=int(max(0.0, min(1.0, frac)) * 100)))

    def connect(self, reason=""):
        with self._lock:
            if not bool(self.get_setting("enabled", False)):
                return False
            allow, why = self._rules_verdict()
            if not allow:
                self._enter_pause(why)
                return False
            if self._paused:
                self._paused = False
                self._notice(T("resumed_notice", reason=network_label(network_snapshot())))
            core, nodes, label = self._connect_plan()
            if core is None:
                self._teardown(restore=True)
                self._fail(label)
                return False
            self._set_state("starting", label)
            info, err = self.cores.prepare(core, progress=self._download_progress)
            if self._stop.is_set():
                return False
            if info is None:
                self._teardown(restore=True)
                if err == T("core_need_restart"):
                    self._need_restart(T("restart_reason_core", core=CORE_TITLES[core]))
                else:
                    self._fail(T("core_prepare_fail", err=_short(err, 120)), err)
                return False
            self.cores.runtime.stop()        # освободить порт перед проверкой: его держит наше же ядро
            port, user, pwd = self._endpoint(ensure_free=True)
            auto = self._ping_url() if len(nodes) > 1 else None
            try:
                cfg = build_main_config(core, nodes, port, user, pwd, auto_url=auto)
            except Exception as e:
                self._teardown(restore=True)
                self._fail(T("core_unsupported_node", core=CORE_TITLES[core]), f"{type(e).__name__}: {e}")
                return False
            err = self.cores.runtime.start(cfg)
            if err and info.get("channel") == "modern":
                # Новая сборка не запустилась. Второе Go-ядро в тот же процесс не грузим (это роняло
                # клиент): отмечаем сборку, при следующем запуске поднимется legacy, и предлагаем перезапуск.
                full = f"{CORE_TITLES[core]} {info.get('tag') or ''}: {err}"
                if core_crashed(err):
                    probe = self._probe_failed_core(core, cfg) if core == CORE_SINGBOX else []
                    self.cores.mark_modern_bad(core, info, err, probe)
                self._teardown(restore=True)
                self._save_error(T("core_start_fail", err=_short(err, 120)), full)
                if self.cores.meta(core, "legacy") or self.cores.channel(core) == "legacy":
                    self._need_restart(T("restart_reason_fallback", core=CORE_TITLES[core]), is_error=True)
                else:
                    self._fail(T("core_start_fail", err=_short(err, 120)), full)
                return False
            if err:
                self._teardown(restore=True)
                full = f"{CORE_TITLES[core]} {info.get('channel')} {info.get('tag') or ''}: {err}"
                self._fail(T("core_start_fail", err=_short(err, 120)), full)
                return False
            deadline = _now() + 6.0
            while _now() < deadline and not _port_open(port, 0.2):
                time.sleep(0.1)
            if not _port_open(port, 0.5):
                self._teardown(restore=True)
                self._fail(T("port_timeout"), f"127.0.0.1:{port} did not open after StartCore")
                return False
            if self._stop.is_set():
                self.cores.runtime.stop()
                return False
            try:
                self.tg.apply(port, user, pwd)
            except Exception as e:
                self.cores.runtime.stop()
                self._fail(T("tg_apply_fail", err=_short(e, 100)), f"{type(e).__name__}: {e}")
                return False
            self._pending_restart = ""
            self._session = {"core": core, "port": port, "user": user, "pwd": pwd, "cfg": cfg, "label": label,
                             "channel": info.get("channel")}
            tail = f" · {CORE_TITLES[core]} legacy" if info.get("channel") == "legacy" else ""
            self._set_state("on", f"{label}{tail}")
            _log(f"connected: {core}/{info.get('channel')} {info.get('tag') or ''} ({reason})")
            return True

    # ---------------------------------------------------------------- перезапуск для смены ядра
    def _need_restart(self, reason, is_error=False):
        """Запустить выбранное ядро можно только после перезапуска клиента — предложить его."""
        self._pending_restart = reason
        if is_error:
            self._save_error(reason, (self._last_error() or {}).get("full") or reason)
        self._set_state("restart", reason)
        _log(f"restart needed: {reason}")
        self._restart_dialog(reason)

    def _restart_dialog(self, reason):
        def show():
            try:
                if AlertDialogBuilder is None:
                    raise RuntimeError("no dialogs")
                frag = get_last_fragment() if get_last_fragment else None
                act = frag.getParentActivity() if frag is not None else None
                b = AlertDialogBuilder(act) if act is not None else AlertDialogBuilder()
                b.set_title(T("restart_title"))
                b.set_message(reason + "\n\n" + T("restart_now_q"))
                b.set_positive_button(T("restart_now"), lambda *a: restart_client())
                b.set_negative_button(T("later"), lambda *a: None)
                b.show()
            except Exception as e:
                _log(f"restart dialog: {e}")
                _notify("info", reason)
        _ui(show)

    def _probe_failed_core(self, core, cfg):
        """Новое ядро упало: несколько коротких запусков, чтобы в отчёте было видно, на чём именно."""
        rt = self.cores.runtime
        direct = {"type": "direct", "tag": "direct"}
        inbound = sb_inbound("probe-in", _free_port(), TG_USER_PREFIX + "probe", _rand_token(16))
        outs = [o for o in cfg.get("outbounds") or [] if o.get("type") not in ("urltest", "selector")][:1]
        no_dns = json.loads(json.dumps(cfg))
        no_dns.pop("dns", None)
        (no_dns.get("route") or {}).pop("default_domain_resolver", None)
        variants = [("empty", {"log": {"level": "panic"}}),
                    ("inbound+direct", sb_config([inbound], [direct], final="direct")),
                    ("server-outbound", sb_config([], outs, final=outs[0]["tag"]) if outs else None),
                    ("without-dns", no_dns)]
        results = []
        for name, variant in variants:
            if variant is None:
                continue
            rt.stop_current()
            err = rt.start(variant, timeout=8.0)
            rt.stop_current()
            results.append(f"{name}: {'ok' if not err else _short(err, 200)}")
            if "timeout" in str(err).lower():
                break
        _log("new core probe: " + "; ".join(results))
        return results

    def _teardown(self, restore=True):
        had = self._session is not None
        self._session = None
        try:
            self.cores.runtime.stop()
        except Exception:
            pass
        if had:
            try:
                self.tg.remove(restore=restore)
            except Exception as e:
                _log(f"remove telegram proxy: {e}")

    def disconnect(self, state="off", detail="", restore=True):
        with self._lock:
            self._teardown(restore=restore)
            self._set_state(state, detail)

    def _cleanup_stale_proxy(self):
        try:
            if self.tg.has_ours():
                self.tg.remove(restore=True)
                _log("stale Tropa proxy removed from Telegram")
        except Exception as e:
            _log(f"stale proxy cleanup: {e}")

    def _watchdog_loop(self):
        fails = 0
        while not self._stop.wait(5.0):
            s = self._session
            if s is None or self._testing or self._state != "on":
                fails = 0
                continue
            if not _port_open(s["port"], 0.5):
                fails += 1
                if fails >= 2:
                    fails = 0
                    self._notice(T("watchdog_restart"))
                    _log("local port stopped answering, reconnecting")
                    _bg(self.connect, "watchdog")
                continue
            fails = 0
            if not self.tg.is_active(s["port"], s["user"]):
                _log("proxy was switched off in Telegram")
                self.set_setting("enabled", False, reload_settings=False)
                self.disconnect("off", restore=False)
                _notify("info", T("ext_off"))

    # ---------------------------------------------------------------- правила сети
    def _rules_verdict(self, snap=None):
        if not bool(self.get_setting("nr_on", False)):
            return True, ""
        snap = snap or network_snapshot()
        if snap.get("vpn") and bool(self.get_setting("nr_vpn", True)):
            return False, T("reason_vpn")
        kind = snap.get("type")
        if kind == "cellular":
            return bool(self.get_setting("nr_mobile", True)), T("net_mobile")
        if kind in ("wifi", "wired", "other"):
            return bool(self.get_setting("nr_wifi", True)), network_label(snap)
        return True, ""

    def _enter_pause(self, why):
        was = self._paused
        self._paused, self._pause_reason = True, why
        self._teardown(restore=True)
        self._set_state("paused", why)
        if not was:
            self._notice(T("paused_notice", reason=why))

    def _apply_rules(self):
        if not bool(self.get_setting("enabled", False)):
            self._paused = False
            return
        allow, why = self._rules_verdict()
        if not allow:
            if self._session is not None or not self._paused:
                with self._lock:
                    self._enter_pause(why)
            elif why != self._pause_reason:
                self._pause_reason = why
                self._set_state("paused", why)
            return
        if self._paused:
            _bg(self.connect, "rules")

    def _monitor_loop(self):
        last, pending = None, None
        while not self._stop.wait(2.5):
            snap = network_snapshot()
            sig = (snap["type"], snap["vpn"], snap["handle"])
            if last is None:
                last = sig
                continue
            if sig != last:
                last, pending = sig, _now()
                continue
            if pending is not None:
                pending = None
                self._apply_rules()
                if bool(self.get_setting("nr_on", False)):
                    self._reload_ui()

    def _on_rules_changed(self, key=None, value=None):
        if key:
            self.set_setting(key, bool(value), reload_settings=False)
        _bg(lambda: (self._apply_rules(), self._reload_ui()))

    # ---------------------------------------------------------------- подписки и ключи
    def refresh_source(self, notify=True):
        if self._refreshing:
            return
        self._refreshing = True
        self._reload_ui()
        hwid = self.get_setting("hwid", "")
        errors, total = [], 0
        try:
            if self._source() == "elix":
                try:
                    links, info, _title = fetch_subscription(ELIX["url"], hwid)
                    self.store["elix"] = {"nodes": [{"uri": l} for l in links], "info": info, "updated": int(time.time())}
                    total = len(links)
                except Exception as e:
                    errors.append(str(e))
            else:
                for sub in self.store["own"]["subs"]:
                    try:
                        links, info, title = fetch_subscription(sub["url"], hwid)
                        sub.update(nodes=[{"uri": l} for l in links], info=info, updated=int(time.time()))
                        if title and not sub.get("name"):
                            sub["name"] = title
                    except Exception as e:
                        errors.append(str(e))
                total = len(self._entries("own"))
            self._store_save()
        finally:
            self._refreshing = False
            self._reload_ui()
        if errors:
            _log(f"subscription refresh failed: {_short(errors[0], 200)}")
        if notify:
            if errors:
                _notify("error", T("refresh_fail", err=_short(_redact(errors[0]), 120)))
            else:
                _notify("ok", T("refreshed", n=total))

    def _known_keys(self):
        return {k for k, _n in self._unique(self._entries("elix") + self._entries("own"))}

    def _add_links(self, links):
        known = self._known_keys()
        added = 0
        for link in links:
            node = parse_link(link)
            if node is None or node_key(node) in known:
                continue
            known.add(node_key(node))
            self.store["own"]["keys"].append({"uri": link})
            added += 1
        if added:
            if not self.store["own"]["subs"] and len(self.store["own"]["keys"]) == added:
                self.set_setting("source", 1, reload_settings=False)
            self._store_save()
        self._reload_ui()
        return added

    def _add_subscription(self, url):
        hwid = self.get_setting("hwid", "")
        try:
            links, info, title = fetch_subscription(url, hwid)
        except Exception as e:
            _notify("error", T("refresh_fail", err=_short(_redact(e), 120)))
            return
        sub = {"id": _rand_token(8), "url": url, "name": title or urllib.parse.urlsplit(url).hostname or "sub",
               "nodes": [{"uri": l} for l in links], "info": info, "updated": int(time.time())}
        self.store["own"]["subs"].append(sub)
        self.set_setting("source", 1, reload_settings=False)
        self._store_save()
        _notify("ok", T("added_sub", n=len(links)))
        self._reload_ui()

    def _on_add_input(self, value):
        text = str(value or "").strip()
        self.set_setting("own_add_input", "", reload_settings=False)
        if not text:
            return
        if re.match(r"^https?://", text, re.I) and not find_links(text):
            _bg(self._add_subscription, text)
            return
        links = find_links(text)
        if not links:
            _notify("error", T("nothing_added"))
            return
        n = self._add_links(links)
        _notify("ok" if n else "info", T("added_keys", n=n))

    def _delete_sub(self, sub_id):
        self.store["own"]["subs"] = [s for s in self.store["own"]["subs"] if s.get("id") != sub_id]
        self._store_save()
        _notify("info", T("deleted"))
        self._reload_ui()

    def _delete_key(self, uri):
        self.store["own"]["keys"] = [k for k in self.store["own"]["keys"] if k.get("uri") != uri]
        self._store_save()
        _notify("info", T("deleted"))
        self._reload_ui()

    def _clear_keys(self):
        self.store["own"]["keys"] = []
        self._store_save()
        self._reload_ui()

    # ---------------------------------------------------------------- буфер обмена
    def _check_clipboard(self):
        if not bool(self.get_setting("clip_import", False)):
            return
        try:
            def read():
                ctx = ApplicationLoader.applicationContext
                cm = ctx.getSystemService("clipboard")
                clip = cm.getPrimaryClip() if cm is not None else None
                if clip is None or clip.getItemCount() == 0:
                    return ""
                txt = clip.getItemAt(0).coerceToText(ctx)
                return str(txt) if txt is not None else ""
            text = _ui_sync(read, 2.0) or ""
        except Exception:
            return
        sig = hashlib.sha1(text.encode("utf-8", "replace")).hexdigest() if text else ""
        if not sig or sig == self.store.get("clip_seen"):
            return
        known = self._known_keys()
        links = [l for l in find_links(text) if node_key(l) not in known]
        self.store["clip_seen"] = sig
        self._store_save()
        if links:
            _ui(lambda: self._clipboard_dialog(links))

    def _clipboard_dialog(self, links):
        try:
            frag = get_last_fragment() if get_last_fragment else None
            act = frag.getParentActivity() if frag is not None else None
            if act is None or AlertDialogBuilder is None:
                return
            b = AlertDialogBuilder(act)
            b.set_title(T("clip_title"))
            b.set_message(T("clip_text", n=len(links)))
            b.set_positive_button(T("add"), lambda *a: _bg(lambda: _notify("ok", T("added_keys", n=self._add_links(links)))))
            b.set_negative_button(T("cancel"), lambda *a: None)
            b.show()
        except Exception as e:
            _log(f"clipboard dialog: {e}")

    # ---------------------------------------------------------------- звонки
    def _install_call_hook(self):
        if self._call_hook is not None or not bool(self.get_setting("calls_proxy", False)):
            return
        cls = find_class("org.telegram.messenger.voip.Instance")
        if cls is None:
            _log("voip Instance class unavailable")
            return
        try:
            self._call_hook = self.hook_all_methods(cls, "makeInstance", CallProxyHook(self))
        except Exception as e:
            _log(f"call hook: {e}")

    def _call_proxy_object(self):
        s = self._session
        if s is None or not bool(self.get_setting("calls_proxy", False)):
            return None
        cls = find_class("org.telegram.messenger.voip.Instance$Proxy")
        return cls(LOCAL_HOST, int(s["port"]), s["user"], s["pwd"]) if cls is not None else None

    # ---------------------------------------------------------------- быстрый тест
    def _progress(self, n=1):
        self._prog[0] += n
        done, total = self._prog[0], self._prog[1]
        self._test_status = T("qt_progress", done=min(done, total), total=total)
        if _now() - self._prog[2] >= 0.8 or done >= total:
            self._prog[2] = _now()
            self._reload_ui()

    def _record(self, key, ms, method):
        if ms is not None:
            self.store["pings"][key] = {"ms": int(ms), "m": method, "ts": int(time.time())}
        self._progress(1)

    def start_quick_test(self):
        if self._testing:
            _notify("info", T("qt_busy"))
            return
        items = self._unique(self._entries())
        if not items:
            _notify("info", T("no_servers"))
            return
        self._testing = True
        self._test_cancel = threading.Event()
        self._test_status = T("qt_start")
        self._prog = [0, len(items), 0.0]
        self._reload_ui()
        _bg(self._quick_test_worker, items)

    def _quick_test_worker(self, items):
        method, timeout, url = self._ping_method(), self._ping_timeout(), self._ping_url()
        results, notes = {}, []
        try:
            if method in ("get", "head"):
                tested, note = self._http_tests(items, method, url, timeout, results)
                if note:
                    notes.append(note)
                rest = [it for it in items if it[0] not in tested]
                if rest:
                    # то, что ядро проверить не смогло (другое ядро, ядро не запустилось), — без ядра
                    self._direct_tests(rest, "tcp", timeout, results)
                    notes.append(T("qt_note_direct", n=len(rest)))
            else:
                note = self._direct_tests(items, method, timeout, results)
                if note:
                    notes.append(note)
                if method == "tcp" and any(n["proto"] in UDP_PROTOCOLS for _k, n in items):
                    notes.append(T("qt_note_udp"))
        except Exception as e:
            _log(f"quick test: {e}")
        finally:
            self._store_save()
            summary = self._summary(items, results, notes)
            self._test_status, self._test_result = "", (method, summary)
            self._testing = False
            if not self._test_cancel.is_set():
                _notify("ok", summary)
            self._reload_ui()

    def _summary(self, items, results, notes):
        names = {k: n["name"] for k, n in items}
        ok = sorted((ms, k) for k, ms in results.items() if ms is not None and ms > 0)
        text = T("qt_summary", ok=len(ok), total=len(items))
        if ok:
            text += " · " + T("qt_best", ms=ok[0][0], unit=T("ms"), name=names.get(ok[0][1], ""))
        skipped = sum(1 for k, _n in items if results.get(k) is None)
        if skipped:
            text += " · " + T("qt_skipped", n=skipped)
        for n in notes:
            text += f". {n}"
        return text

    def _direct_tests(self, items, method, timeout, results):
        note = ""
        if method == "icmp":
            try:
                socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_ICMP).close()
            except Exception:
                method, note = "tcp", T("qt_note_icmp")

        def one(item):
            key, node = item
            if self._test_cancel.is_set():
                return key, None, method
            try:
                ms, used = direct_probe(node, method, timeout)
                return key, ms, used
            except IcmpUnavailable:
                ms, used = direct_probe(node, "tcp", timeout)
                return key, ms, used
            except Exception:
                return key, PING_FAIL, method

        with ThreadPoolExecutor(max_workers=max(1, min(TEST_WORKERS, len(items)))) as ex:
            for fut in as_completed([ex.submit(one, it) for it in items]):
                try:
                    key, ms, used = fut.result()
                except Exception:
                    continue
                results[key] = ms
                self._record(key, ms, used)
        return note

    def _http_tests(self, items, method, url, timeout, results):
        """Реальная задержка через ядро. -> (ключи, которые удалось проверить, пояснение)."""
        core = self._core()
        prepared = [(k, n) for k, n in items if node_supported(core, n)][:TEST_LIMIT]
        if not prepared:
            return set(), ""
        info, err = self.cores.prepare(core)
        if info is None:
            _log(f"test core: {err}")
            return set(), T("qt_note_nocore")
        if not self._lock.acquire(True, 10.0):
            return set(), T("qt_note_busy")
        sess = self._session
        tested = set()
        try:
            base = sess["cfg"] if sess and sess.get("core") == core else None
            tuser, tpwd = "tropat_" + _rand_token(8), _rand_token(20)
            self._test_status = T("qt_core")
            self._reload_ui()
            self._start_fails = 0
            for i in range(0, len(prepared), TEST_BATCH):
                if self._test_cancel.is_set():
                    break
                self._http_batch(core, base, prepared[i:i + TEST_BATCH], tuser, tpwd, method, url, timeout,
                                 results, tested)
        finally:
            self.cores.runtime.stop()
            if sess is not None and self._session is sess and not self._stop.is_set():
                if sess.get("core") == core:
                    err = self.cores.runtime.start(sess["cfg"])
                    sess["channel"] = (self.cores.runtime.current_info() or {}).get("channel", sess.get("channel"))
                    if err:
                        _log(f"restore after test: {err}")
                        _bg(self.connect, "restore")
                else:
                    _bg(self.connect, "restore")
            self._lock.release()
        return tested, ""

    def _http_batch(self, core, base, batch, user, pwd, method, url, timeout, results, tested, depth=0):
        if not batch or self._test_cancel.is_set():
            return
        if self._start_fails >= 24:
            return
        ports = _free_ports(len(batch))
        cfg = add_test_pairs(core, base, [(i, ports[i], n) for i, (_k, n) in enumerate(batch)], user, pwd)
        err = self.cores.runtime.start(cfg)
        if err and core_crashed(err):
            cur = self.cores.runtime.current_info() or {}
            if cur.get("channel") == "modern":
                # отметим сборку как падающую; legacy в этом же процессе не грузим (нужен перезапуск)
                self.cores.mark_modern_bad(core, cur, err)
        if err:
            self._start_fails += 1
            _log(f"test core start: {_short(err, 300)}")
            if len(batch) == 1 or depth >= 9:
                for key, _n in batch:
                    results[key] = PING_FAIL
                    tested.add(key)
                    self._record(key, PING_FAIL, method)
                return
            mid = len(batch) // 2
            self._http_batch(core, base, batch[:mid], user, pwd, method, url, timeout, results, tested, depth + 1)
            self._http_batch(core, base, batch[mid:], user, pwd, method, url, timeout, results, tested, depth + 1)
            return
        deadline = _now() + 2.5
        while _now() < deadline and not (_port_open(ports[0], 0.1) and _port_open(ports[-1], 0.1)):
            time.sleep(0.05)
        with ThreadPoolExecutor(max_workers=max(1, min(TEST_WORKERS, len(batch)))) as ex:
            futs = {ex.submit(http_probe, ports[i], user, pwd, url, method, timeout): k for i, (k, _n) in enumerate(batch)}
            for fut in as_completed(futs):
                key = futs[fut]
                try:
                    ms = fut.result()
                except Exception:
                    ms = PING_FAIL
                results[key] = ms
                tested.add(key)
                self._record(key, ms, method)

    # ---------------------------------------------------------------- действия из интерфейса
    def _on_enable(self, value):
        self.set_setting("enabled", bool(value), reload_settings=False)
        if value:
            _bg(self.connect, "user")
        else:
            self._paused = False
            _bg(self.disconnect, "off")

    def _on_source(self, value):
        self.set_setting("source", int(value), reload_settings=False)
        if not self._source_data()["nodes_count"]:
            _bg(self.refresh_source, False)
        if self._session is not None:
            _bg(self.connect, "source")
        self._reload_ui()

    def _select(self, key):
        self.store["active"][self._source()] = key
        self._store_save()
        node = next((n for k, n in self._unique(self._entries()) if k == key), None)
        if node is not None and not node_supported(self._core(), node) and node_supported(_other_core(self._core()), node):
            self._switch_core(_other_core(self._core()))
        if bool(self.get_setting("enabled", False)):
            _bg(self.connect, "select")
        self._reload_ui()

    def _on_flag(self, key, value, reconnect=False):
        self.set_setting(key, bool(value), reload_settings=False)
        if key == "calls_proxy" and value:
            _bg(self._install_call_hook)
        if reconnect and self._session is not None:
            _bg(self.connect, key)
        self._reload_ui()

    def _set_choice(self, key, idx):
        self.set_setting(key, int(idx), reload_settings=False)
        if key == "ping_method":
            self._test_result = ("", "")
        self._reload_ui()

    def _set_url(self, url):
        self.set_setting("ping_url", normalize_url(url), reload_settings=False)
        self._test_result = ("", "")
        self._reload_ui()

    def _on_url_changed(self, value):
        raw = str(value or "").strip()
        url = normalize_url(raw)
        self.set_setting("ping_url", url, reload_settings=False)
        self._test_result = ("", "")
        if raw and raw != url:
            _notify("info", T("lat_url_fixed", url=url))
        self._reload_ui()

    def _on_timeout_choice(self, idx):
        choices = (1, 2, 3, 5, 7, 10)
        self.set_setting("ping_timeout", choices[max(0, min(len(choices) - 1, int(idx)))], reload_settings=False)
        self._reload_ui()

    def _on_core_type(self, idx):
        self.set_setting("core_type", int(idx), reload_settings=False)
        _bg(self._after_core_choice)

    def _on_core_legacy(self, value):
        self.set_setting("core_legacy", bool(value), reload_settings=False)
        _bg(self._after_core_choice)

    def _after_core_choice(self):
        core = self._core()
        # смена ядра, когда в процесс уже загружено другое: предложить перезапуск, второе не грузим
        if self.cores.needs_restart_for(core):
            self._need_restart(T("restart_reason_core", core=CORE_TITLES[core]))
        elif bool(self.get_setting("enabled", False)):
            self.connect("core")
        self._reload_ui()

    def _retry_modern(self):
        core = self._core()
        self.cores.clear_modern_bad(core)
        if self.cores.needs_restart_for(core):
            self._need_restart(T("restart_reason_core", core=CORE_TITLES[core]))
        else:
            _notify("info", T("core_retry_started"))
            if bool(self.get_setting("enabled", False)):
                self.connect("retry-modern")
        self._reload_ui()

    def _core_action(self):
        core = self._core()
        if self.cores.meta(core, self.cores.channel(core)):
            self._notice_now(self.cores.check_updates(core, force=True))
        else:
            info, err = self.cores.prepare(core, progress=self._download_progress)
            if info:
                _notify("ok", T("core_ready", name=self.cores.label(core, info)))
            else:
                _notify("error", T("core_prepare_fail", err=_short(err, 100)))
            if self._state == "starting":
                self._set_state("off")
        self._reload_ui()

    def _on_port_input(self, value):
        try:
            port = int(str(value or "").strip())
        except Exception:
            port = 0
        if not 1024 <= port <= 65535:
            _notify("error", T("port_bad"))
            self._reload_ui()
            return
        if port == self._int("tg_port", 0, 0, 65535):
            return
        if not _port_free(port) and not (self._session and self._session["port"] == port):
            _notify("error", T("port_taken", port=port))
            self._reload_ui()
            return
        self.set_setting("tg_port", port, reload_settings=False)
        self.set_setting("tg_port_in", str(port), reload_settings=False)
        _notify("ok", T("port_set", port=port))
        if self._session is not None:
            _bg(self.connect, "port")
        self._reload_ui()

    def _open_link(self, url):
        def do():
            browser = find_class("org.telegram.messenger.browser.Browser")
            frag = get_last_fragment() if get_last_fragment else None
            ctx = frag.getParentActivity() if frag is not None else ApplicationLoader.applicationContext
            if browser is not None:
                browser.openUrl(ctx, url)
        _ui(do)

    # ---------------------------------------------------------------- интерфейс
    def _server_label(self, key, node):
        display = self._ping_display()
        badge = ping_badge(self._ping(key), display)
        if not badge:
            return node["name"]
        sep = " " if display in ("dots", "bars") and badge != "✕" else " · "
        return f"{badge}{sep}{node['name']}"

    def _test_row(self):
        method_line = self._latency_summary()
        if self._testing:
            sub = f"{self._test_status or T('qt_start')} · {method_line}"
        else:
            m, res = self._test_result
            sub = f"{method_line} — {res}" if res and m == self._ping_method() else method_line
        return Text(text=T("qt"), subtext=sub, icon="msg_speed", accent=True, on_click=lambda v: self.start_quick_test())

    def _latency_summary(self):
        m = self._ping_method()
        parts = [T({"tcp": "m_tcp", "get": "m_get", "head": "m_head", "icmp": "m_icmp"}[m])]
        if m in ("get", "head"):
            parts.append(urllib.parse.urlsplit(self._ping_url()).hostname or "")
        parts.append(f"{self._ping_timeout()} {T('sec')}")
        return " · ".join(p for p in parts if p)

    def _rules_summary(self):
        if not bool(self.get_setting("nr_on", False)):
            return T("nr_off")
        snap = network_snapshot()
        allow, why = self._rules_verdict(snap)
        return f"{network_label(snap)} · " + (T("nr_allowed") if allow else T("nr_paused", reason=why))

    def _on_state_click(self):
        if self._pending_restart:
            self._restart_dialog(self._pending_restart)
        else:
            self._show_details()

    def _state_row(self):
        # Тап — подробности (или перезапуск, если он нужен); удержание — скопировать отчёт.
        detail = self._state_detail or ""
        sub = (detail + " · " if detail else "") + T("state_hint")
        return Text(text=f"{T('state')}: {T(_STATE_LABELS.get(self._state, 'st_off'))}",
                    subtext=sub, icon=_STATE_ICONS.get(self._state, "msg_info"),
                    red=(self._state == "error"),
                    on_click=lambda v: self._on_state_click(),
                    on_long_click=lambda v: _copy_text(self._report(with_log=True)))

    def create_settings(self):
        items = [
            Header(text="Tropa"),
            Switch(key="enabled", text=T("enable"), subtext=T("enable_sub"), default=False,
                   icon="msg_permissions", on_change=self._on_enable),
            self._state_row(),
        ]
        if self._state == "restart" and self._pending_restart:
            items.append(Text(text=T("restart_now"), subtext=self._pending_restart, icon="msg_retry", accent=True,
                              on_click=lambda v: restart_client()))
        items.append(Selector(key="source", text=T("source"), default=0, items=[T("src_elix"), T("src_own")],
                              icon="msg_list", on_change=self._on_source))
        if self._source() == "elix":
            info = describe_userinfo(self.store["elix"].get("info"))
            items.append(Text(text=T("elix_get"), subtext=info or T("elix_get_sub"), icon="msg_link",
                              on_click=lambda v: self._open_link(ELIX["bot"])))
        else:
            items.append(Text(text=T("own_page"), icon="msg_edit", create_sub_fragment=self._own_page))
        items.append(Header(text=T("servers")))
        items.append(self._test_row())
        items.append(Text(text=T("refreshing") if self._refreshing else T("refresh"), icon="msg_retry",
                          on_click=lambda v: _bg(self.refresh_source, True)))
        servers = self._unique(self._entries())
        active = self._active_key()
        if not servers:
            items.append(Divider(text=T("no_servers")))
        for key, node in servers:
            note = self._support_note(node)
            label = self._server_label(key, node) + (f" · {note}" if note else "")
            items.append(Text(text=label, accent=(key == active), on_click=lambda v, k=key: self._select(k)))
        core = self._core()
        items += [
            Header(text=T("extra")),
            Switch(key="auto_best", text=T("auto_best"), subtext=T("auto_best_d"), default=False, icon="msg_stats",
                   on_change=lambda v: self._on_flag("auto_best", v, reconnect=True)),
            Switch(key="calls_proxy", text=T("calls"), subtext=T("calls_d"), default=False, icon="msg_calls",
                   on_change=lambda v: self._on_flag("calls_proxy", v)),
            Switch(key="clip_import", text=T("clip"), subtext=T("clip_d"), default=False, icon="msg_copy",
                   on_change=lambda v: self._on_flag("clip_import", v)),
            Text(text=T("lat"), subtext=self._latency_summary(), icon="msg_speed", create_sub_fragment=self._latency_page),
            Text(text=T("nr"), subtext=self._rules_summary(), icon="settings_data", create_sub_fragment=self._rules_page),
            Text(text=T("core"), subtext=self.cores.label(core), icon="msg_customize", create_sub_fragment=self._core_page),
            Divider(text=T("about", ver=__version__)),
        ]
        return items

    def _choice(self, title, subtitle, selected, key, idx):
        return Text(text=f"{title}  ✓" if selected else title, subtext=subtitle, accent=bool(selected),
                    on_click=lambda v, k=key, i=idx: self._set_choice(k, i))

    def _latency_page(self):
        m, d, url, t = self._ping_method(), self._ping_display(), self._ping_url(), self._ping_timeout()
        items = [Header(text=T("lat_method"))]
        for i, (code, tk, sk) in enumerate((("tcp", "m_tcp", "m_tcp_d"), ("get", "m_get", "m_get_d"),
                                            ("head", "m_head", "m_head_d"), ("icmp", "m_icmp", "m_icmp_d"))):
            items.append(self._choice(T(tk), T(sk), m == code, "ping_method", i))
        items.append(Header(text=T("lat_display")))
        for i, (code, tk, sk) in enumerate((("digits", "d_digits", "d_digits_d"), ("bars", "d_bars", "d_bars_d"),
                                            ("both", "d_both", "d_both_d"), ("dots", "d_dots", "d_dots_d"))):
            items.append(self._choice(T(tk), T(sk), d == code, "ping_display", i))
        items.append(Header(text=T("lat_url")))
        items.append(Input(key="ping_url", text=T("lat_url_own"), default=url, subtext=T("lat_url_edit"),
                           icon="msg_link", on_change=self._on_url_changed))
        for name, purl in PING_URL_PRESETS:
            sel = url == purl
            items.append(Text(text=f"{name}  ✓" if sel else name, subtext=purl, accent=sel,
                              on_click=lambda v, u=purl: self._set_url(u)))
        items.append(Divider(text=T("lat_url_hint")))
        items.append(Header(text=T("lat_timeout")))
        if Slider is not None:
            items.append(Slider(key="ping_timeout", text=T("lat_timeout"), default=int(t), min=1, max=10, step=1,
                                subtext=T("lat_timeout_d"), icon="msg_recent"))
        else:
            choices = (1, 2, 3, 5, 7, 10)
            cur = min(range(len(choices)), key=lambda i: abs(choices[i] - t))
            items.append(Selector(key="ping_timeout_sel", text=T("lat_timeout"), default=cur,
                                  items=[f"{c} {T('sec')}" for c in choices], icon="msg_recent",
                                  on_change=self._on_timeout_choice))
        return items

    def _rules_page(self):
        snap = network_snapshot()
        allow, why = self._rules_verdict(snap)
        if not bool(self.get_setting("nr_on", False)):
            state = T("nr_rules_off")
        else:
            state = T("nr_allowed") if allow else T("nr_paused", reason=why)
        return [
            Header(text=T("nr")),
            Switch(key="nr_on", text=T("nr_switch"), subtext=T("nr_switch_d"), default=False, icon="settings_power",
                   on_change=lambda v: self._on_rules_changed("nr_on", v)),
            Header(text=T("nr_where")),
            Switch(key="nr_wifi", text=T("nr_wifi"), subtext=T("nr_wifi_d"), default=True, icon="menu_website",
                   on_change=lambda v: self._on_rules_changed("nr_wifi", v)),
            Switch(key="nr_mobile", text=T("nr_mobile"), subtext=T("nr_mobile_d"), default=True, icon="msg_data",
                   on_change=lambda v: self._on_rules_changed("nr_mobile", v)),
            Switch(key="nr_vpn", text=T("nr_vpn"), subtext=T("nr_vpn_d"), default=True, icon="msg_secret",
                   on_change=lambda v: self._on_rules_changed("nr_vpn", v)),
            Header(text=T("nr_now")),
            Text(text=T("nr_line", net=network_label(snap), vpn=T("on") if snap.get("vpn") else T("off")),
                 subtext=state, icon="msg_info", on_click=lambda v: self._on_rules_changed()),
            Divider(text=T("nr_hint")),
        ]

    def _core_status(self, core, channel, info):
        dl = self.cores.downloading
        if dl and dl[0] == core:
            return T("core_downloading")
        if not self.cores.modern_supported():
            return T("core_unsupported")
        if not info:
            return T("core_autodl")
        parts = []
        if self.cores.runtime.is_loaded(info.get("sha256")):
            parts.append(T("core_in_process"))
        if info.get("channel") == "modern":
            parts.append(T("core_verified"))
        nxt = self.cores._nexts().get(f"{core}:{channel}")
        if nxt:
            parts.append(T("core_staged_row", name=self.cores.label(core, nxt)))
        elif self.cores.update_pending:
            parts.append(T("core_available_row"))
        return " · ".join(parts) or None

    def _core_page(self):
        core = self._core()
        channel = self.cores.channel(core)
        info = self.cores.meta(core, channel)
        rows = [
            Header(text=T("core")),
            Selector(key="core_type", text=T("core_type"), default=0, items=["sing-box", "Xray"],
                     icon="msg_customize", on_change=self._on_core_type),
            Text(text=f"{T('core_installed')}: {self.cores.label(core, info, channel)}",
                 subtext=self._core_status(core, channel, info), icon="msg_info"),
            Switch(key="core_legacy", text=T("core_legacy"), subtext=T("core_legacy_d"), default=False,
                   icon="msg_retry", on_change=self._on_core_legacy),
        ]
        bad = self.cores.modern_bad(core)
        if bad and self.cores.user_channel() == "modern":
            rows.append(Text(text=T("core_retry_modern"), subtext=T("core_retry_modern_d", err=_short(bad.get("err"), 90)),
                             icon="msg_retry", accent=True, on_click=lambda v: _bg(self._retry_modern)))
        rows.append(Text(text=T("core_check") if info else T("core_download"), icon="msg_download", accent=True,
                         on_click=lambda v: _bg(self._core_action)))
        port, _user, _pwd = self._endpoint()
        self.set_setting("tg_port_in", str(port), reload_settings=False)
        rows += [
            Header(text=T("port_header")),
            Input(key="tg_port_in", text=T("port"), default=str(port), subtext=T("port_d", port=port),
                  icon="msg_link", on_change=self._on_port_input),
            Divider(text=T("core_note")),
        ]
        return rows

    def _own_page(self):
        items = [
            Header(text=T("own_page")),
            Input(key="own_add_input", text=T("add_key"), default="", subtext=T("add_key_hint"), icon="msg_add",
                  on_change=self._on_add_input),
        ]
        subs = self.store["own"]["subs"]
        if subs:
            items.append(Header(text=T("subs_header")))
            for sub in subs:
                desc = f"{len(sub.get('nodes') or [])} · {describe_userinfo(sub.get('info'))}".strip(" ·")
                items.append(Text(text=sub.get("name") or sub.get("url"), subtext=f"{desc} · {T('sub_hint')}",
                                  icon="msg_link", on_click=lambda v: _bg(self.refresh_source, True),
                                  on_long_click=lambda v, i=sub.get("id"): self._delete_sub(i)))
        keys = self.store["own"]["keys"]
        if keys:
            items.append(Header(text=T("keys_header")))
            for entry in keys:
                node = self._node(entry)
                if node is None:
                    continue
                k = node_key(node)
                note = self._support_note(node)
                items.append(Text(text=self._server_label(k, node) + (f" · {note}" if note else ""),
                                  subtext=T("key_hint"), accent=(k == self._active_key()),
                                  on_click=lambda v, kk=k: self._select(kk),
                                  on_long_click=lambda v, u=entry["uri"]: self._delete_key(u)))
            items.append(Text(text=T("clear_keys"), red=True, icon="msg_delete", on_click=lambda v: self._clear_keys()))
        return items
