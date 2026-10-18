# SPDX-License-Identifier: GPL-3.0-or-later
#
# Tropa — плагин для Telegram-клиентов на SDK плагинов exteraGram (Aprel Gram, exteraGram).
# Пускает Telegram через локальное ядро sing-box или Xray.
#
# Copyright (C) 2026 Tropa contributors
#
# Это свободная программа: её можно распространять и изменять на условиях
# GNU General Public License версии 3 либо (по вашему выбору) любой более поздней версии.
# Полный текст лицензии — в файле LICENSE репозитория. Программа поставляется
# БЕЗ КАКИХ-ЛИБО ГАРАНТИЙ.
#
# Сторонние компоненты в этот файл не входят и скачиваются во время работы:
#   * сборки ядер из релизов github.com/itsv1eds/exitFy (sing-box — GPL-3.0-or-later,
#     обёртка — MIT); каждая проверяется подписью сборщика (ECDSA P-256) и SHA-256;
#   * legacy-сборки libvless — по выбору пользователя или как запасной вариант,
#     если новое ядро падает при запуске.

__id__ = "tropa"
__name__ = "Tropa"
__description__ = ("Telegram через собственное ядро sing-box или Xray: ключи, подписки, "
                   "быстрый тест, правила по типу сети, звонки через прокси.")
__author__ = "@mdlz6"
__version__ = "0.3.0"
__min_version__ = "11.12.0"

import os
import re
import collections
import json
import time
import base64
import struct
import socket
import random
import hashlib
import threading
import ctypes
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import ssl
except Exception:  # pragma: no cover - ssl есть во всех сборках Chaquopy
    ssl = None

import requests

from base_plugin import BasePlugin, MethodHook
try:
    from base_plugin import AppEvent
except Exception:
    AppEvent = None
try:
    from base_plugin import MenuItemData, MenuItemType
except Exception:
    MenuItemData = MenuItemType = None
from android_utils import log as _sdk_log, run_on_ui_thread
from ui.settings import Header, Switch, Selector, Input, Text, Divider
try:
    from ui.settings import Slider
except Exception:
    Slider = None
try:
    from ui.settings import EditText
except Exception:
    EditText = None
from ui.bulletin import BulletinHelper
try:
    from ui.alert import AlertDialogBuilder
except Exception:
    AlertDialogBuilder = None
from hook_utils import find_class
try:
    from client_utils import get_last_fragment
except Exception:
    get_last_fragment = None
from org.telegram.messenger import ApplicationLoader, SharedConfig
from android.os import Build
try:
    from java.util import Locale
except Exception:
    Locale = None
