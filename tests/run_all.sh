#!/bin/sh
# Сборка плагина, тестовых библиотек ядер и запуск всех тестов.
#   SING_BOX      — sing-box 1.13 с with_utls и with_quic (обязательно)
#   SING_BOX_120  — sing-box 1.13.20 (по умолчанию = SING_BOX)
#   SING_BOX_114  — sing-box 1.13.14 (по умолчанию = SING_BOX)
#   PYTHON        — Python 3.11 с requests (по умолчанию python3.11)
set -e
cd "$(dirname "$0")/.."
: "${SING_BOX:?set SING_BOX to a sing-box 1.13 binary built with with_utls,with_quic}"
export SING_BOX
export SING_BOX_120="${SING_BOX_120:-$SING_BOX}"
export SING_BOX_114="${SING_BOX_114:-$SING_BOX}"
PYTHON="${PYTHON:-python3.11}"

# разрешить непривилегированный ICMP (на устройстве Android это есть; для тестов — best-effort)
echo "0 2147483647" > /proc/sys/net/ipv4/ping_group_range 2>/dev/null || true

"$PYTHON" build.py
cd tests/fakecore
for spec in "sbmodern:libsb-modern.so:" "sblegacy:libsb-legacy.so:-DAPI1" "xrmodern:libxr-modern.so:" \
            "xrlegacy:libxr-legacy.so:-DAPI1" "sbmodern2:libsb-modern2.so:"; do
    name=${spec%%:*}; rest=${spec#*:}; out=${rest%%:*}; flag=${rest#*:}
    gcc -Wall -shared -fPIC -O2 $flag -DCORE_NAME="\"$name\"" -o "$out" fakecore.c
done
chmod +x fakexray.py
cd ../..

status=0
for t in t_configs t_runtime t_cores t_proxy t_ui; do
    printf '%-10s ' "$t"
    if "$PYTHON" "tests/$t.py" > "tests/$t.log" 2>&1; then echo ok; else echo "FAILED (tests/$t.log)"; status=1; fi
done
exit $status
