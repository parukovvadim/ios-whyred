#!/bin/sh
# Read the WHYRED console log (kernel patch 0047) from a phone booted into
# OrangeFox / TWRP recovery (fastboot boot recovery.img; adb root shell).
#   tools/whyred-log-pull.sh OUT.txt
# eMMC build: the driver's block is 512 bytes, so the log area is the last
# 1 + 4 MiB/512 = 8193 sectors of userdata (header sector, then the ring).
# Only reads.
set -eu
out=${1:?usage: whyred-log-pull.sh OUT.txt}
dev=$(adb shell 'for d in /dev/block/by-name/userdata /dev/block/bootdevice/by-name/userdata; do [ -e $d ] && readlink -f $d && break; done' | tr -d '\r')
[ -n "$dev" ] || { echo "userdata block device not found" >&2; exit 1; }
bytes=$(adb shell blockdev --getsize64 "$dev" | tr -d '\r')
sectors=$((bytes / 512))
skip=$((sectors - 8193))
adb exec-out "dd if=$dev bs=512 skip=$skip count=8193 2>/dev/null" > "$out.bin"
echo "$dev: $bytes bytes, read sectors $skip.. ($(stat -c %s "$out.bin") bytes)" >&2
python3 "$(dirname "$0")/whyred-log.py" "$out.bin" "$out"
