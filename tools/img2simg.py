#!/usr/bin/env python3
"""Convert raw partition image to Android sparse image format.
Compatible with standard img2simg: img2simg IN.img OUT.simg [BLOCK_SIZE]
"""
import sys, os, struct

MAGIC = 0xed26ff3a
RAW, DONT_CARE = 0xcac1, 0xcac3

def main():
    if len(sys.argv) < 3:
        sys.exit(f"Usage: {sys.argv[0]} <raw_image_file> <sparse_image_file> [block_size]")
    src = sys.argv[1]
    dst = sys.argv[2]
    bs = int(sys.argv[3]) if len(sys.argv) > 3 else 4096

    size = os.path.getsize(src)
    if size % bs:
        # Pad file to block size if needed
        pad = bs - (size % bs)
        with open(src, 'ab') as f:
            f.write(b'\0' * pad)
        size += pad
    nblocks = size // bs

    zero_block = b'\0' * bs
    runs = []
    step = (8 << 20) // bs

    with open(src, 'rb') as fn:
        for base in range(0, nblocks, step):
            n = min(step, nblocks - base)
            bn = fn.read(n * bs)
            for i in range(n):
                is_data = (bn[i * bs:(i + 1) * bs] != zero_block)
                if runs and runs[-1][0] == is_data:
                    runs[-1][1] += 1
                else:
                    runs.append([is_data, 1])

    changed = sum(c for d, c in runs if d)
    with open(src, 'rb') as fn, open(dst, 'wb') as out:
        out.write(struct.pack('<IHHHHIIII', MAGIC, 1, 0, 28, 12, bs, nblocks, len(runs), 0))
        pos = 0
        for is_data, count in runs:
            if is_data:
                out.write(struct.pack('<HHII', RAW, 0, count, 12 + count * bs))
                fn.seek(pos * bs)
                left = count * bs
                while left:
                    chunk = fn.read(min(left, 8 << 20))
                    out.write(chunk)
                    left -= len(chunk)
            else:
                out.write(struct.pack('<HHII', DONT_CARE, 0, count, 12))
            pos += count
    print(f"[*] Wrote {dst}: {changed} of {nblocks} non-zero blocks ({changed * bs >> 20} MiB of {size >> 20} MiB)")

if __name__ == '__main__':
    main()
