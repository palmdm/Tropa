"""Shared setup for plugin-level tests: fake cores installed on the 'device', servers, store."""
import hashlib
import json
import os
import time

import harness as H


def install_fake_cores(m, which=(("singbox", "modern", "libsb-modern.so", "sb-v1.13.20-w4079", 2),
                                 ("singbox", "legacy", "libsb-legacy.so", "", 1),
                                 ("xray", "modern", "libxr-modern.so", "xray-v26.7.28-w10110", 2))):
    cdir = H.core_env()
    os.environ["FAKECORE_BIN_xrmodern"] = os.path.join(H.FAKECORE_DIR, "fakexray.py")
    os.environ["FAKECORE_BIN_xrlegacy"] = os.path.join(H.FAKECORE_DIR, "fakexray.py")
    cores_dir = os.path.join(H.FILES, "app_tropa", "cores")
    os.makedirs(cores_dir, exist_ok=True)
    meta = {}
    for core, ch, src, tag, api in which:
        p = H.padded_core(src, os.path.join(cores_dir, f"{core}-{ch}.so"))
        meta[f"{core}:{ch}"] = {"core": core, "channel": ch, "tag": tag, "version": "", "api": api,
                                "sha256": hashlib.sha256(open(p, "rb").read()).hexdigest(), "size": os.path.getsize(p)}
    H.SETTINGS["core_meta2"] = json.dumps(json.dumps(meta))
    H.SETTINGS["core_check_ts"] = json.dumps(int(time.time()))
    return cdir


def set_store(links, source="elix", subs=None, keys=None):
    store = {"elix": {"nodes": [{"uri": u} for u in links], "info": {}, "updated": int(time.time())},
             "own": {"subs": subs or [], "keys": [{"uri": u} for u in (keys or [])]},
             "active": {"elix": "", "own": ""}, "pings": {}, "clip_seen": ""}
    H.SETTINGS["store"] = json.dumps(json.dumps(store))
    H.SETTINGS["source"] = json.dumps(1 if source == "own" else 0)


def block_network(m):
    calls = []

    def fake_get(url, *a, **k):
        calls.append(url)
        raise RuntimeError("network disabled in test")
    m.requests.get = fake_get
    return calls
