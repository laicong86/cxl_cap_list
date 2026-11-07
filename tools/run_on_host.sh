#!/bin/sh
# 在目标 CXL 主机上手工执行的部署脚本（无需 python/paramiko）。
#
# 用法（在能登录该主机后，把 <your-host> 换成目标机器地址）：
#   scp tools/run_on_host.sh root@<your-host>:/tmp/
#   ssh root@<your-host> 'sh /tmp/run_on_host.sh 0000:a8:00.0'
#
# 或直接把本文件内容粘贴进远端 shell 也行（需要 cxl_dump.py 已在 /root/cxl/）。
set -e

BDF="${1:-0000:a8:00.0}"
DIR="${CXL_DIR:-/root/cxl}"
PY="${PYTHON:-python3}"

if [ ! -f "$DIR/cxl_dump.py" ]; then
    echo "ERROR: $DIR/cxl_dump.py 不存在。请先上传 src/cxl_dump.py" >&2
    exit 1
fi

echo "=== 环境 ==="
uname -sr
"$PY" --version
id -u

echo
echo "=== PCI 侧确认 $BDF ==="
DEV="/sys/bus/pci/devices/$BDF"
if [ ! -d "$DEV" ]; then
    echo "ERROR: $DEV 不存在。现有设备：" >&2
    ls /sys/bus/pci/devices/ >&2
    exit 1
fi
echo "vendor/device : $(cat "$DEV/vendor" 2>/dev/null) / $(cat "$DEV/device" 2>/dev/null)"
echo "class         : $(cat "$DEV/class" 2>/dev/null)"
echo "driver        : $(basename "$(readlink -f "$DEV/driver" 2>/dev/null)" 2>/dev/null || echo none)"

echo
echo "=== 运行 cxl_dump ==="
cd "$DIR"
exec "$PY" cxl_dump.py -d "$BDF"
