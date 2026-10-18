# Tropa

## Description

A plugin for accessing Telegram from locations where Telegram may not work properly. Designed for clients that support plugins (Aprel Gram, exteraGram, AyuGram). Borrows some ideas from the exitFy plugin (an outdated version) with improvements, fixes, and new features. Tested and recommended for use with Aprel Gram.
Runs Telegram through the local **sing-box** or **Xray** kernel: the client connects to SOCKS5 at `127.0.0.1`, and the kernel routes traffic through the selected server.

## Features

- **Keys and subscriptions:** vless (tcp, ws, grpc, httpupgrade, xhttp; tls, reality), vmess, trojan, shadowsocks (including 2022), hysteria2, tuic. Subscriptions in base64 or as a list of links; traffic, expiration date, and profile name are displayed. If a subscription update fails, the server list remains unchanged.
- **Built-in elix provider.**
- **Single entry in the Telegram proxy list:** fixed port and login; the port can be set manually. Old Tropa entries are automatically deleted; the user’s previous proxy is restored when the app is turned off.
- **Quick config test:** TCP Connect, ICMP, HTTP GET / HEAD (actual latency through the server itself). Hysteria2 and TUIC are also tested using the TCP method: TCP to the same port, followed by ICMP. Ping can be displayed as numbers, a gauge, or a gauge with numbers or dots; there are presets for the test address and timeout.
- **Automatic selection of the best server:** `urltest` in Sing-Box, `balancer` + `observatory` in Xray.
- **Auto-activation based on network:** Wi-Fi and mobile network behavior are configured separately; when the VPN is enabled, the plugin pauses. The “Enable” toggle remains the user’s choice.
- **Calls via proxy:** A local SOCKS5 proxy is passed to `Instance.makeInstance`.
- **Import keys from the clipboard** when returning to Telegram. Only new keys are offered.
- **Telegram menu item:** “Tropa Settings” appears in the left menu (and in the chat menu)—a quick way to access settings.
- **Diagnostics in the “Status” section:** tap to view details and copy the full report with the log (without keys or passwords); press and hold to copy the report immediately.

## Installation

Upload the `tropa.plugin` file to your Telegram client (Aprel Gram, exteraGram, AyuGram) and tap it to begin installation. Grant all permissions and install.

## Kernels

Kernels are not included in the plugin. The required kernel is downloaded automatically upon the first connection (≈30 MB) and is then stored on the device: each build is stored in its own file (`<type>-<channel>.so`), so switching between kernel types or legacy mode does not require any additional downloads.

- **New (default).** Releases from [itsv1eds/exitFy](https://github.com/itsv1eds/exitFy/releases): as of this release, sing-box 1.13.20 and Xray 26.7.28. The release’s `manifest.json` is verified using the builder’s signature (ECDSA P-256, verified using pure Python), and the file itself is verified using the SHA-256 hash from the manifest. GitHub mirrors are used only for these verified files. Available for arm64 and Android 10+.
- **Legacy.** Older libvless builds from [itsv1eds/itsv1eds](https://github.com/itsv1eds/itsv1eds/releases), as in exitFy. These are enabled via the “Legacy kernel” toggle or automatically if the new kernel crashes on startup: in that case, Tropa connects via the legacy kernel, saves the error message for the report, and does not run the crashed build until a new one is released or the user clicks “Try the new kernel again.”

**One Go kernel per process.** You cannot unload a native library from a process, and two Go runtimes in a single process conflict over signal handlers and can crash the client (this is exactly what caused the client to crash when switching kernels in earlier versions). Therefore, the first selected kernel is loaded and remains the only one, and changing the kernel type or enabling legacy mode requires restarting the client—Tropa offers this with a single button (the restart works the same way as Aprel Gram does: it restarts the client and terminates the old process). As long as the desired kernel matches the one already loaded, reconnection occurs without a restart. Libraries are loaded locally (`RTLD_NOW` without `RTLD_GLOBAL`). Updates for an already loaded kernel are downloaded in advance and applied at the next startup; background updates are downloaded only on an unlimited data plan.

If the new kernel fails to start, Tropa flags the build, saves the error message and several short test runs (visible in the report to determine exactly where it crashes), and offers to restart using the legacy kernel. If the selected server only works with a different kernel (hysteria2 and tuic—sing-box only), Tropa switches the kernel itself; such servers are always marked as “sing-box only” in the list.

## Limitations

- TG WS mode (without servers) has not yet been implemented: this is a separate MTProto-over-WebSocket bridge that needs to be refined and tested on the device.
- sing-box does not support xhttp. Xray in this plugin does not support hysteria2 and tuic. Shadowsocks with plugins (obfs, v2ray-plugin) is not supported.

## Build

```bash
python3 build.py
```

The script concatenates `src/NN_*.py` files in order into `dist/tropa.plugin` and checks for syntax errors.

## Tests

The tests run the plugin on a computer using mock versions of the Aprel Gram SDK and Telegram classes. The mocks replicate the issues that occurred on the device: you cannot iterate over a `java.util.ArrayList` in Chaquopy Aprel Gram using a `for` loop; `SharedConfig` is implemented as in Aprel Gram; and settings persist across restarts. Instead of cores, there are small libraries with the same C interface (`StartCore`/`StopCore`) that launch a desktop sing-box with the same configuration.

You’ll need Python 3.11, `requests`, `gcc`, `openssl`, and sing-box 1.13 with `with_utls` and `with_quic`:

```
SING_BOX=/path/to/sing-box tests/run_all.sh
```

| Test | What it checks |
|---|---|
| `t_configs` | configurations for all protocols pass `sing-box check` (1.13.14, 1.13.19, 1.13.20) |
| `t_runtime` | a single proxy entry, traffic over each protocol, quick test, core switching, rollback to legacy, restart, error replication |
| `t_cores` | signed boot once, switches without boot, updates, fake releases, migration from old layout |
| `t_proxy` | forks without getters, entries after restart, user actions in proxy settings, busy port |
| `t_ui` | all settings pages in various states, subscriptions, clipboard |

## Third-Party Licenses

Third-party components are downloaded during runtime and are not included in the repository:
- sing-box builds — GPL-3.0-or-later;
- itsv1eds build wrapper — MIT;
- Xray-core — under the XTLS project license.

