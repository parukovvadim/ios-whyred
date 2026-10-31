#!/usr/bin/env python3
"""Pure Python implementation of Android mkbootimg (supporting header versions v0, v1, v2).

Compatible with AOSP mkbootimg command line options.
"""
import argparse
import hashlib
import os
import re
import struct
import sys

BOOT_MAGIC = b"ANDROID!"
BOOT_MAGIC_SIZE = 8
BOOT_NAME_SIZE = 16
BOOT_ARGS_SIZE = 512
BOOT_EXTRA_ARGS_SIZE = 1024


def parse_int(x):
    return int(x, 0)


def encode_os_version(os_version_str, os_patch_level_str):
    val = 0
    if os_version_str:
        m = re.match(r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?", os_version_str)
        if m:
            a = int(m.group(1) or 0) & 0x7F
            b = int(m.group(2) or 0) & 0x7F
            c = int(m.group(3) or 0) & 0x7F
            val |= (a << 25) | (b << 18) | (c << 11)
    if os_patch_level_str:
        m = re.match(r"^(\d{4})-(\d{2})", os_patch_level_str)
        if m:
            y = (int(m.group(1)) - 2000) & 0x7F
            month = int(m.group(2)) & 0xF
            val |= (y << 4) | month
    return val


def pad_to(data, page_size):
    pad = (page_size - (len(data) % page_size)) % page_size
    return data + (b"\0" * pad)


def main():
    p = argparse.ArgumentParser(description="Pack Android boot.img (v0, v1, v2)")
    p.add_argument("--kernel", required=True, help="path to kernel")
    p.add_argument("--ramdisk", default=None, help="path to ramdisk")
    p.add_argument("--second", default=None, help="path to second bootloader")
    p.add_argument("--dtb", default=None, help="path to dtb")
    p.add_argument("--recovery_dtbo", default=None, help="path to recovery dtbo")
    p.add_argument("--cmdline", default="", help="extra kernel arguments")
    p.add_argument("--base", type=parse_int, default=0x10000000)
    p.add_argument("--kernel_offset", type=parse_int, default=0x00008000)
    p.add_argument("--ramdisk_offset", type=parse_int, default=0x01000000)
    p.add_argument("--second_offset", type=parse_int, default=0x00F00000)
    p.add_argument("--tags_offset", type=parse_int, default=0x00000100)
    p.add_argument("--dtb_offset", type=parse_int, default=0x01F00000)
    p.add_argument("--os_version", default="9.0.0")
    p.add_argument("--os_patch_level", default="2020-01")
    p.add_argument("--board", default="")
    p.add_argument("--pagesize", type=parse_int, default=4096)
    p.add_argument("--header_version", type=parse_int, default=0)
    p.add_argument("-o", "--output", required=True, help="output boot.img path")

    args = p.parse_args()

    kernel_data = open(args.kernel, "rb").read()
    ramdisk_data = open(args.ramdisk, "rb").read() if args.ramdisk else b""
    second_data = open(args.second, "rb").read() if args.second else b""
    dtb_data = open(args.dtb, "rb").read() if args.dtb else b""
    recovery_dtbo_data = open(args.recovery_dtbo, "rb").read() if args.recovery_dtbo else b""

    k_sz = len(kernel_data)
    r_sz = len(ramdisk_data)
    s_sz = len(second_data)
    dtb_sz = len(dtb_data)
    rec_dtbo_sz = len(recovery_dtbo_data)

    k_addr = args.base + args.kernel_offset
    r_addr = args.base + args.ramdisk_offset
    s_addr = args.base + args.second_offset
    t_addr = args.base + args.tags_offset
    dtb_addr = args.base + args.dtb_offset

    os_ver = encode_os_version(args.os_version, args.os_patch_level)
    cmdline_bytes = args.cmdline.encode("utf-8")[:BOOT_ARGS_SIZE]
    extra_cmdline = b""
    if len(args.cmdline.encode("utf-8")) > BOOT_ARGS_SIZE:
        extra_cmdline = args.cmdline.encode("utf-8")[BOOT_ARGS_SIZE:BOOT_ARGS_SIZE + BOOT_EXTRA_ARGS_SIZE]

    # Calculate SHA1 id
    sha = hashlib.sha1()
    sha.update(kernel_data)
    sha.update(struct.pack("<I", k_sz))
    sha.update(ramdisk_data)
    sha.update(struct.pack("<I", r_sz))
    sha.update(second_data)
    sha.update(struct.pack("<I", s_sz))
    if args.header_version >= 1:
        sha.update(recovery_dtbo_data)
        sha.update(struct.pack("<I", rec_dtbo_sz))
    if args.header_version >= 2:
        sha.update(dtb_data)
        sha.update(struct.pack("<I", dtb_sz))
    sha_id = sha.digest() + (b"\0" * (32 - len(sha.digest())))

    # Format header v0
    hdr = bytearray()
    hdr += BOOT_MAGIC
    hdr += struct.pack("<10I", k_sz, k_addr, r_sz, r_addr, s_sz, s_addr, t_addr, args.pagesize, args.header_version, os_ver)
    hdr += args.board.encode("utf-8")[:BOOT_NAME_SIZE].ljust(BOOT_NAME_SIZE, b"\0")
    hdr += cmdline_bytes.ljust(BOOT_ARGS_SIZE, b"\0")
    hdr += sha_id
    hdr += extra_cmdline.ljust(BOOT_EXTRA_ARGS_SIZE, b"\0")

    if args.header_version == 1:
        header_size = len(hdr) + 16
        hdr += struct.pack("<IQI", rec_dtbo_sz, 0, header_size)
    elif args.header_version >= 2:
        header_size = len(hdr) + 16 + 12
        hdr += struct.pack("<IQI", rec_dtbo_sz, 0, header_size)
        hdr += struct.pack("<IQ", dtb_sz, dtb_addr)

    # Pad header to pagesize
    out_img = bytearray()
    out_img += pad_to(hdr, args.pagesize)
    out_img += pad_to(kernel_data, args.pagesize)
    if r_sz > 0:
        out_img += pad_to(ramdisk_data, args.pagesize)
    if s_sz > 0:
        out_img += pad_to(second_data, args.pagesize)
    if args.header_version >= 1 and rec_dtbo_sz > 0:
        out_img += pad_to(recovery_dtbo_data, args.pagesize)
    if args.header_version >= 2 and dtb_sz > 0:
        out_img += pad_to(dtb_data, args.pagesize)

    with open(args.output, "wb") as f:
        f.write(out_img)

    print(f"[*] Successfully wrote {len(out_img)} bytes to {args.output} (header v{args.header_version})")


if __name__ == "__main__":
    main()
