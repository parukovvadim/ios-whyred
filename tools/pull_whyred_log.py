#!/usr/bin/env python3
import subprocess
import sys
import os
import struct

ADB = r"C:\platform-tools\adb.exe" if os.path.exists(r"C:\platform-tools\adb.exe") else "adb"

def run_adb(args, capture_output=True):
    cmd = [ADB] + args
    res = subprocess.run(cmd, stdout=subprocess.PIPE if capture_output else None, stderr=subprocess.PIPE, check=True)
    return res.stdout

def main():
    out_txt = sys.argv[1] if len(sys.argv) > 1 else "tools/log_latest.txt"
    out_bin = out_txt + ".bin"

    print(f"[*] Querying userdata block device via {ADB}...")
    dev = None
    for cand in ["/dev/block/bootdevice/by-name/userdata", "/dev/block/by-name/userdata", "/dev/block/mmcblk0p64"]:
        try:
            out = run_adb(["shell", f"readlink -f {cand}"]).decode().strip()
            dev_cand = out.splitlines()[-1].strip()
            if dev_cand.startswith("/dev/block/"):
                dev = dev_cand
                break
        except Exception:
            pass
    if not dev:
        dev = "/dev/block/mmcblk0p64"
    print(f"[+] Found userdata device: {dev}")

    size_out = run_adb(["shell", f"blockdev --getsize64 {dev}"]).decode().strip()
    total_bytes = int(size_out.splitlines()[-1].strip())
    sectors = total_bytes // 512
    skip = sectors - 8193
    print(f"[+] Total bytes: {total_bytes} ({sectors} sectors of 512B). Reading last 8193 sectors (skip={skip})...")

    # Read binary
    res = subprocess.run([ADB, "exec-out", f"dd if={dev} bs=512 skip={skip} count=8193 2>/dev/null"],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    raw = res.stdout
    with open(out_bin, "wb") as f:
        f.write(raw)
    print(f"[+] Dumped {len(raw)} bytes to {out_bin}")

    # Decode
    magic, version, size, total, seq = struct.unpack_from("<8sIIQQ", raw, 0)
    if magic != b"SWEETLOG":
        print(f"[-] Error: magic is {magic!r}, expected b'SWEETLOG'", file=sys.stderr)
        sys.exit(1)

    BLOCK = 512
    ring = raw[BLOCK:BLOCK + size]
    if total <= size:
        text = ring[:total]
    else:
        start = total % size
        text = ring[start:] + ring[:start]

    log_str = text.decode("utf-8", "replace").replace("\r", "")
    with open(out_txt, "w", encoding="utf-8") as f:
        f.write(log_str)

    print(f"[+] Decoded {len(log_str)} chars into {out_txt} (flush #{seq}, total bytes {total})")
    print("--- Last 40 lines of log: ---")
    lines = log_str.strip().splitlines()
    for l in lines[-40:]:
        print(l)

if __name__ == "__main__":
    main()
