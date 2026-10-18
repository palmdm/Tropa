

# ===========================================================================
# Строки интерфейса
# ===========================================================================
_STRINGS = {
    # общее
    "enable": ("Включить", "Enable"),
    "enable_sub": ("Telegram пойдёт через выбранный сервер", "Telegram goes through the selected server"),
    "state": ("Состояние", "Status"),
    "st_off": ("Выключено", "Off"),
    "st_starting": ("Подключение…", "Connecting…"),
    "st_on": ("Подключено", "Connected"),
    "st_paused": ("Пауза", "Paused"),
    "st_error": ("Ошибка", "Error"),
    "st_restart": ("Нужен перезапуск", "Restart needed"),
    "state_hint": ("нажмите — подробности, удерживайте — скопировать отчёт",
                   "tap for details, hold to copy the report"),
    "menu_open": ("Настройки Tropa", "Tropa settings"),
    "later": ("Позже", "Later"),
    "ms": ("мс", "ms"),
    "sec": ("сек", "sec"),
    "on": ("вкл", "on"),
    "off": ("выкл", "off"),
    "cancel": ("Отмена", "Cancel"),
    "add": ("Добавить", "Add"),
    "delete": ("Удалить", "Delete"),
    "copy": ("Скопировать", "Copy"),
    "close": ("Закрыть", "Close"),
    "copied": ("Скопировано", "Copied"),
    "copy_failed": ("Не удалось скопировать", "Copy failed"),
    "about": ("Tropa {ver} · GPL-3.0-or-later. Свободная программа без гарантий; исходный код открыт.",
              "Tropa {ver} · GPL-3.0-or-later. Free software without warranty; source code is open."),
    # источники и серверы
    "source": ("Источник серверов", "Server source"),
    "src_elix": ("elix", "elix"),
    "src_own": ("Мои ключи и подписки", "My keys and subscriptions"),
    "elix_get": ("Получить доступ в elix", "Get elix access"),
    "elix_get_sub": ("Бот провайдера в Telegram", "The provider's Telegram bot"),
    "servers": ("Серверы", "Servers"),
    "no_servers": ("Серверов пока нет. Обновите список или добавьте ключ.", "No servers yet. Refresh the list or add a key."),
    "refresh": ("Обновить серверы", "Refresh servers"),
    "refreshing": ("Обновление…", "Refreshing…"),
    "refreshed": ("Серверов: {n}", "Servers: {n}"),
    "refresh_fail": ("Не удалось обновить подписку: {err}", "Failed to refresh the subscription: {err}"),
    "sub_info": ("Трафик: {used} из {total} · до {exp}", "Traffic: {used} of {total} · until {exp}"),
    "sub_unlimited": ("без лимита", "unlimited"),
    "own_page": ("Мои ключи и подписки", "My keys and subscriptions"),
    "add_key": ("Добавить ключ или подписку", "Add a key or subscription"),
    "add_key_hint": ("vless://, vmess://, trojan://, ss://, hy2://, tuic:// или https:// подписки",
                     "vless://, vmess://, trojan://, ss://, hy2://, tuic:// or an https:// subscription"),
    "added_keys": ("Добавлено ключей: {n}", "Keys added: {n}"),
    "added_sub": ("Подписка добавлена, серверов: {n}", "Subscription added, servers: {n}"),
    "nothing_added": ("Не нашёл поддерживаемых ключей", "No supported keys found"),
    "subs_header": ("Подписки", "Subscriptions"),
    "keys_header": ("Отдельные ключи", "Individual keys"),
    "sub_hint": ("Нажмите — обновить, удерживайте — удалить", "Tap to refresh, hold to delete"),
    "key_hint": ("Нажмите — выбрать, удерживайте — удалить", "Tap to select, hold to delete"),
    "extra": ("Дополнительно", "Extras"),
    "deleted": ("Удалено", "Deleted"),
    "clear_keys": ("Удалить все отдельные ключи", "Delete all individual keys"),
    # быстрый тест
    "qt": ("Быстрый тест конфигов", "Quick config test"),
    "qt_busy": ("Тест уже идёт", "A test is already running"),
    "qt_start": ("Запуск теста…", "Starting test…"),
    "qt_core": ("Запуск ядра для теста…", "Starting the core for the test…"),
    "qt_progress": ("Проверка… {done} из {total}", "Testing… {done} of {total}"),
    "qt_summary": ("Ответили {ok} из {total}", "{ok} of {total} responded"),
    "qt_best": ("лучший {ms} {unit} — {name}", "best {ms} {unit} — {name}"),
    "qt_skipped": ("пропущено {n}", "skipped {n}"),
    "qt_note_udp": ("Hysteria2/TUIC по TCP/ICMP проверены только на доступность — точная проверка: HTTP GET",
                    "Hysteria2/TUIC were only checked for reachability over TCP/ICMP — use HTTP GET for a real test"),
    "qt_note_direct": ("ещё {n} проверено без ядра (TCP/ICMP)", "{n} more checked without the core (TCP/ICMP)"),
    "qt_note_icmp": ("ICMP недоступен на этом устройстве — использован TCP", "ICMP is unavailable on this device — TCP was used"),
    "qt_note_nocore": ("ядро для HTTP-теста не запустилось", "the core for the HTTP test did not start"),
    "qt_note_busy": ("Ядро занято — повторите через пару секунд", "The core is busy — retry in a couple of seconds"),
    "lat": ("Проверка задержки", "Latency test"),
    "lat_method": ("Метод проверки", "Test method"),
    "m_tcp": ("TCP Connect", "TCP Connect"),
    "m_tcp_d": ("TCP (рекомендуется)", "TCP (recommended)"),
    "m_get": ("HTTP GET", "HTTP GET"),
    "m_get_d": ("Запрос через сервер — реальная задержка", "A request through the server — the real delay"),
    "m_head": ("HTTP HEAD", "HTTP HEAD"),
    "m_head_d": ("Как GET, но без тела ответа", "Like GET, without the response body"),
    "m_icmp": ("ICMP Ping", "ICMP Ping"),
    "m_icmp_d": ("ICMP", "ICMP"),
    "lat_display": ("Отображение пинга", "Ping display"),
    "d_digits": ("Цифры (мс)", "Numbers (ms)"),
    "d_digits_d": ("Числовое значение пинга", "Numeric ping value"),
    "d_bars": ("Шкала", "Bars"),
    "d_bars_d": ("Индикатор уровня сигнала", "Signal level indicator"),
    "d_both": ("Шкала и цифры", "Bars and numbers"),
    "d_both_d": ("Индикатор и числовое значение", "Indicator and numeric value"),
    "d_dots": ("Точки", "Dots"),
    "d_dots_d": ("Зелёная точка, если сервер ответил", "Green dot if the server responded"),
    "lat_url": ("URL для теста", "Test URL"),
    "lat_url_own": ("Свой адрес", "Custom URL"),
    "lat_url_edit": ("Нажмите, чтобы изменить", "Tap to change"),
    "lat_url_fixed": ("Адрес исправлен: {url}", "URL corrected: {url}"),
    "lat_url_hint": ("Адрес нужен методам HTTP GET и HEAD: запрос идёт через сам сервер, это реальная задержка. "
                     "TCP и ICMP проверяют только, отвечает ли сервер. Telegram отвечает ошибкой 404 — это нормально: "
                     "любой ответ значит, что серверы Telegram доступны.",
                     "HTTP GET and HEAD use this URL: the request goes through the server, so it is the real delay. "
                     "TCP and ICMP only check that the server answers. Telegram replies 404 — that's fine: "
                     "any reply means Telegram servers are reachable."),
    "lat_timeout": ("Таймаут", "Timeout"),
    "lat_timeout_d": ("Сколько ждать ответа от одного сервера, сек", "How long to wait for one server, sec"),
    # правила сети
    "nr": ("Автовключение по сети", "Network rules"),
    "nr_off": ("Выключено", "Off"),
    "nr_switch": ("Учитывать тип сети", "Follow network type"),
    "nr_switch_d": ("Tropa сам встанет на паузу и включится обратно при смене сети",
                    "Tropa pauses and resumes itself when the network changes"),
    "nr_where": ("Где работать", "Where to work"),
    "nr_wifi": ("Wi-Fi", "Wi-Fi"),
    "nr_wifi_d": ("Работать в сетях Wi-Fi и проводных", "Work on Wi-Fi and wired networks"),
    "nr_mobile": ("Мобильная сеть", "Mobile data"),
    "nr_mobile_d": ("Работать на мобильном интернете", "Work on mobile data"),
    "nr_vpn": ("Пауза при VPN", "Pause when VPN is on"),
    "nr_vpn_d": ("Если на телефоне включён VPN, Tropa не нужен", "If a VPN is on, Tropa is not needed"),
    "nr_now": ("Сейчас", "Now"),
    "nr_line": ("Сеть: {net} · VPN: {vpn}", "Network: {net} · VPN: {vpn}"),
    "nr_rules_off": ("Правила выключены — Tropa работает в любой сети", "Rules are off — Tropa works on any network"),
    "nr_allowed": ("Tropa разрешён в этой сети", "Tropa is allowed on this network"),
    "nr_paused": ("Tropa на паузе: {reason}", "Tropa is paused: {reason}"),
    "nr_hint": ("Переключатель «Включить» остаётся за вами: правила только ставят Tropa на паузу и включают обратно, "
                "когда сеть подходит. Сеть проверяется каждые пару секунд и при возврате в приложение.",
                "The Enable switch stays yours: rules only pause Tropa and bring it back when the network fits. "
                "The network is checked every couple of seconds and when you return to the app."),
    "net_wifi": ("Wi-Fi", "Wi-Fi"),
    "net_mobile": ("мобильная сеть", "mobile data"),
    "net_wired": ("проводная сеть", "wired network"),
    "net_other": ("другая сеть", "other network"),
    "net_none": ("нет сети", "no network"),
    "reason_vpn": ("включён VPN", "VPN is on"),
    "paused_notice": ("Tropa на паузе: {reason}", "Tropa paused: {reason}"),
    "resumed_notice": ("Tropa снова работает: {reason}", "Tropa resumed: {reason}"),
    # дополнительные функции
    "auto_best": ("Автовыбор лучшего сервера", "Auto-select the best server"),
    "auto_best_d": ("Ядро само держит соединение через самый быстрый из лучших серверов",
                    "The core keeps traffic on the fastest of the top servers"),
    "calls": ("Звонки через прокси", "Calls through the proxy"),
    "calls_d": ("Звонки Telegram тоже пойдут через сервер (нужно разрешение на хуки)",
                "Telegram calls also go through the server (needs the hooks permission)"),
    "clip": ("Импорт ключей из буфера", "Import keys from clipboard"),
    "clip_d": ("При возврате в Telegram предложить добавить скопированные ключи",
               "Offer to add copied keys when you return to Telegram"),
    "clip_title": ("Ключи в буфере обмена", "Keys in clipboard"),
    "clip_text": ("Найдено ключей: {n}. Добавить в «Мои ключи»?", "Keys found: {n}. Add to “My keys”?"),
    # ядро
    "core": ("Ядро", "Core"),
    "core_type": ("Тип ядра", "Core type"),
    "core_installed": ("Установлено", "Installed"),
    "core_none": ("не установлено", "not installed"),
    "core_ch_new": ("новое", "new"),
    "core_ch_legacy": ("legacy", "legacy"),
    "core_ch_manual": ("из файла", "from file"),
    "core_verified": ("Подпись сборщика и SHA-256 проверены", "Builder signature and SHA-256 verified"),
    "core_legacy": ("Legacy-ядра", "Legacy cores"),
    "core_legacy_d": ("Старые сборки libvless, как в exitFy. Включите, если с новым ядром что-то не работает",
                      "Old libvless builds, as in exitFy. Turn on if something breaks with the new core"),
    "core_download": ("Скачать ядро", "Download the core"),
    "core_downloading": ("Скачивание ядра…", "Downloading the core…"),
    "core_downloading_pct": ("Скачивание ядра {name}… {pct}%", "Downloading the {name} core… {pct}%"),
    "core_autodl": ("Скачается само при подключении (≈30 МБ, один раз)", "Downloads by itself on connect (~30 MB, once)"),
    "core_in_process": ("загружено в Telegram", "loaded in Telegram"),
    "core_check": ("Проверить обновление ядра", "Check for core update"),
    "core_uptodate": ("Установлено самое новое ядро", "The newest core is installed"),
    "core_staged": ("Ядро {name} скачано — применится после перезапуска Telegram",
                    "Core {name} downloaded — it applies after restarting Telegram"),
    "core_staged_row": ("обновление {name} — после перезапуска Telegram", "update {name} — after a Telegram restart"),
    "core_ready": ("Ядро установлено: {name}", "Core installed: {name}"),
    "core_metered": ("Есть обновление ядра (≈30 МБ): скачается на Wi-Fi или по кнопке «Проверить обновление ядра»",
                     "A core update (~30 MB) is available: it downloads on Wi-Fi or via “Check for core update”"),
    "core_available_row": ("доступно обновление", "update available"),
    "core_busy": ("Ядро уже скачивается", "The core is already downloading"),
    "core_dl_fail": ("Не удалось скачать ядро", "Failed to download the core"),
    "core_prepare_fail": ("Ядро не готово: {err}", "The core is not ready: {err}"),
    "core_stuck": ("Ядро зависло при запуске — перезапустите Telegram", "The core hung while starting — restart Telegram"),
    "core_unsupported": ("Новые ядра есть только для arm64 и Android 10+, используется legacy",
                         "New cores exist only for arm64 and Android 10+, legacy is used"),
    "core_start_fail": ("Ядро не запустилось: {err}", "The core failed to start: {err}"),
    "core_need_restart": ("нужен перезапуск клиента", "a client restart is needed"),
    "core_retry_modern": ("Снова пробовать новое ядро", "Try the new core again"),
    "core_retry_modern_d": ("Отключено после ошибки: {err}", "Disabled after an error: {err}"),
    "core_retry_started": ("Пробую новое ядро", "Trying the new core"),
    "core_unsupported_node": ("Этот сервер не поддерживается ядром {core}", "This server is not supported by the {core} core"),
    "core_switched_for_server": ("Ядро переключено на {core}: выбранный сервер работает только с ним",
                                 "Switched the core to {core}: the selected server only works with it"),
    "core_note": ("Ядра хранятся на устройстве и не скачиваются повторно. Чтобы сменить тип ядра или включить "
                  "legacy, нужен перезапуск клиента (одно Go-ядро на процесс — так клиент не падает). "
                  "Если новое ядро падает, Tropa сам предложит перезапуск на legacy.",
                  "Cores are stored on the device and never re-downloaded. Changing the core type or enabling "
                  "legacy needs a client restart (one Go core per process keeps the client from crashing). "
                  "If the new core crashes, Tropa offers a restart onto legacy."),
    # перезапуск при смене ядра
    "restart_title": ("Перезапуск Tropa", "Restart Tropa"),
    "restart_now": ("Перезапустить", "Restart"),
    "restart_now_q": ("Перезапустить клиент сейчас?", "Restart the client now?"),
    "restart_reason_core": ("Чтобы запустить ядро {core}, нужно перезапустить клиент.",
                            "A client restart is needed to start the {core} core."),
    "restart_reason_fallback": ("Новое ядро {core} не запустилось. Нужно перезапустить клиент, чтобы подключиться "
                                "через legacy-ядро.",
                                "The new {core} core failed to start. Restart the client to connect through the legacy core."),
    "server_needs": ("только {core}", "{core} only"),
    "server_unsupported": ("не поддерживается", "not supported"),
    "server_unsupported_all": ("Ни один сервер не поддерживается ядрами Tropa", "No server is supported by Tropa cores"),
    "port_header": ("Подключение Telegram", "Telegram connection"),
    "port": ("Порт локального прокси", "Local proxy port"),
    "port_d": ("Telegram подключается к 127.0.0.1:{port}. В списке прокси Telegram всегда одна запись Tropa",
               "Telegram connects to 127.0.0.1:{port}. The Telegram proxy list always has one Tropa entry"),
    "port_bad": ("Порт — число от 1024 до 65535", "The port must be a number from 1024 to 65535"),
    "port_taken": ("Порт {port} занят другим приложением", "Port {port} is used by another app"),
    "port_set": ("Порт {port} сохранён", "Port {port} saved"),
    "port_busy_moved": ("Порт {old} занят другим приложением — Tropa перешёл на {new}",
                        "Port {old} is used by another app — Tropa moved to {new}"),
    # диагностика
    "err_title": ("Состояние Tropa", "Tropa status"),
    "diag_copy_hint": ("«Скопировать» — полный отчёт с журналом (без ключей и паролей) для разработчика.",
                       "“Copy” gives the full report with the log (no keys or passwords) for the developer."),
    "diag_clear": ("Очистить журнал", "Clear the log"),
    "diag_cleared": ("Журнал очищен", "Log cleared"),
    "diag_last_error": ("Последняя ошибка", "Last error"),
    # подключение
    "pick_server": ("Сначала выберите сервер", "Pick a server first"),
    "connected_to": ("Подключено: {name}", "Connected: {name}"),
    "port_timeout": ("Ядро запустилось, но порт не открылся", "The core started but its port did not open"),
    "tg_apply_fail": ("Не удалось включить прокси в Telegram: {err}", "Failed to enable the proxy in Telegram: {err}"),
    "ext_off": ("Прокси выключен в настройках Telegram — Tropa остановлен", "The proxy was turned off in Telegram — Tropa stopped"),
    "watchdog_restart": ("Ядро перестало отвечать — перезапускаю", "The core stopped responding — restarting"),
}


def _lang_is_ru():
    try:
        if Locale is not None:
            lang = str(Locale.getDefault().getLanguage() or "").lower()
            return lang in ("ru", "uk", "be", "kk")
    except Exception:
        pass
    return True


_RU = _lang_is_ru()


def T(key, **kw):
    pair = _STRINGS.get(key)
    s = (pair[0] if _RU else pair[1]) if pair else key
    if kw:
        try:
            return s.format(**kw)
        except Exception:
            return s
    return s
