#!/usr/bin/env python3
"""Build the minimal Apple Device Tree that the WHYRED xnu needs to boot.

Only what the early boot path actually reads (see NOTES.md); every MMIO
address comes from the whyred (Xiaomi Redmi Note 5 / Pro, SDM636) live FDT.
Usage:  mkadt.py OUT.adt [--dump] [--qemu] [--highmem] [--native] [--midmem]
"""
import hashlib, os, struct, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import adt  # noqa: E402

# Kernel-managed RAM: above every Qualcomm XPU carve-out (see NOTES.md)
# On whyred, lower DDR bank is 0x80000000..0x100000000 (2 GiB) with carveouts
# up to ~0x9f800000. 0xb0000000 gives ~1.25 GiB clean memory below 4G.
PHYS_BASE = 0xb0000000
MEM_SIZE = 0x4d000000

# --highmem (phone only): the upper DDR bank above 4 GiB (0x100000000).
# On a 4 GiB whyred: 0x100000000 + 2 GiB (0x80000000).
# On a 6 GiB whyred: 0x100000000 + 4 GiB (0x100000000).
# On a 3 GiB whyred: 0x100000000 + 1 GiB (0x40000000).
HIGH_PHYS_BASE = 0x100000000
HIGH_MEM_SIZE = int(os.environ.get("HIGHMEM_SIZE", "0x80000000"), 16)

# --midmem: 0x80000000 + memory size
MID_PHYS_BASE = int(os.environ.get("MIDBASE", "0x80000000"), 16)
MID_MEM_SIZE = int(os.environ.get("MIDSIZE", "0x80000000"), 16)

# /arm-io children are relative to this; it must not be 0 (serial_init bails)
SOC_BASE = 0x01000000

# whyred GICv3: interrupt-controller@17a00000 (GICD 0x17a00000, GICR 0x17b00000, 8 cores)
GICD, GICD_SIZE = 0x17a00000, 0x10000
GICR, GICR_SIZE = 0x17b00000, 0x100000

# cont_splash_mem left lit by ABL at 0x9d400000, size 0x23ff000
FB, FB_SIZE = 0x9d400000, 0x23ff000
WHYRED_ECID = 0x5748595245440001  # 'WHYRED' + 1, synthetic
FB_W, FB_H, FB_STRIDE = 1080, 2160, 1080 * 4

# eMMC 5.1 host controller (sdhc_1 at 0x0c0c4000)
EMMC, EMMC_SIZE = 0x0c0c4000, 0x1000
TIMEBASE = 19200000
VTIMER_INTID = 19

# QEMU virt (-M virt,gic-version=3 -cpu cortex-a76): GICD/GICR and the generic timer's CNTFRQ
QEMU_GICD, QEMU_GICR, QEMU_TIMEBASE = 0x08000000, 0x080a0000, 62500000
QEMU_VTIMER_INTID = 27

BOOT_MANIFEST_HASH = hashlib.sha384(b'whyred boot manifest').digest()

# The iOS userland is the iPhone X (iPhone10,3 / D22AP) IPSW. MobileGestalt
# derives product type, device class, home-button-less UI, artwork etc. from
# the root identity and /product of the real D22AP device tree.
D22AP_ADT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../research/ipsw-x/d22ap.adt')


def d22ap_product(path=D22AP_ADT):
    """/product properties of the real D22AP tree, without the syscfg
    placeholders iBoot would fill in (flag bit set) and the node bookkeeping."""
    if not os.path.exists(path):
        print(f'warning: {path} missing, no /product node', file=sys.stderr)
        return None
    root, _ = adt.parse(open(path, 'rb').read())
    for c in root.children:
        if dict((k, v) for k, f, v in c.props).get('name') == b'product\0':
            return [(k, v) for k, f, v in c.props if not f and k not in ('name', 'AAPL,phandle')]
    raise SystemExit(f'{path}: no /product node')

u32 = lambda *v: struct.pack('<%dI' % len(v), *v)
u64 = lambda *v: struct.pack('<%dQ' % len(v), *v)
cstr = lambda s: s.encode() + b'\0'


def node(name, props=(), children=()):
    n = adt.Node()
    n.props = [('name', 0, cstr(name))] + [(k, 0, v) for k, v in props]
    n.children = list(children)
    return n


def build(seed=None, qemu=False, highmem=False, native=False, midmem=False):
    """qemu=True: same tree, but with QEMU virt's GIC addresses and CNTFRQ (tools/qemu-whyred.py)."""
    phys_base, mem_size = ((MID_PHYS_BASE, MID_MEM_SIZE) if midmem else
                           (HIGH_PHYS_BASE, HIGH_MEM_SIZE) if highmem else (PHYS_BASE, MEM_SIZE))
    gicd, gicr, timebase = (QEMU_GICD, QEMU_GICR, QEMU_TIMEBASE) if qemu else (GICD, GICR, TIMEBASE)
    seed = seed if seed is not None else os.urandom(64)
    phandle = iter(range(1, 1000))
    ph = lambda: ('AAPL,phandle', u32(next(phandle)))

    chosen = node('chosen', [
        ph(),
        ('dram-base', u64(phys_base)),
        ('dram-size', u64(mem_size)),
        ('random-seed', seed),
        ('debug-enabled', u32(1)),
        ('firmware-version', cstr('whyred-shim')),
        ('system-firmware-version', cstr('whyred-shim')),
        # iBoot's SHA-384 of the boot manifest
        ('boot-manifest-hash', BOOT_MANIFEST_HASH),
        # libimg4 (cryptexd) crypto algorithm requirement
        ('crypto-hash-method', cstr('sha2-384')),
        # MobileGestalt's screen scale: 1080x2160 @3x = 360x720 pt
        ('display-scale', u32(3)),
        # IOPlatformUUID generation
        ('unique-chip-id', struct.pack('<Q', WHYRED_ECID)),
        ('chip-id', u32(0x8015)),
        # Security status for mobileactivationd Hactivation branch
        ('certificate-production-status', u32(0)),
        ('effective-production-status-ap', u32(0)),
        ('certificate-security-mode', u32(1)),
        ('effective-security-mode-sep', u32(1)),
    ], [node('memory-map', [ph()]),
        # Relaxed SIP
        node('asmb', [ph(), ('lp-sip0', u64(0x6f)), ('lp-sip1', u32(1))])])

    # WHYRED SMP: 4 Cortex-A73 (Gold) cores, MPIDR 0x100-0x103:
    # the Kryo 260 Silver cores have no 16K granule, so the shim boots XNU
    # on Gold CPU 0x100 and parks the Silver cluster.
    cpu_nodes = []
    for core in range(1 if qemu else 4):
        cpu_nodes.append(node(f'cpu{core}', [
            ph(),
            ('device_type', cstr('cpu')),
            ('compatible', cstr('qcom,kryo260') + cstr('qcom,kryo470') + cstr('ARM,v8')),
            ('reg', u32(core if qemu else 0x100 | core)),  # MPIDR Aff1:Aff0
            ('cpu-id', u32(core)),
            ('cluster-id', u32(0)),
            ('cluster-type', u32(0)),
            ('die-cluster-id', u32(0)),
            ('cluster-core-id', u32(core)),
            ('l2-cache-id', u32(0)),
            ('l3-cache-id', u32(0)),
            ('state', cstr('running' if core == 0 else 'stopped')),
            ('timebase-frequency', u32(timebase)),
            ('clock-frequency', u32(1804800000)),  # 1.8 GHz Gold
            ('bus-frequency', u32(100000000)),
            ('memory-frequency', u32(1866000000)),
            ('peripheral-frequency', u32(timebase)),
            ('fixed-frequency', u32(timebase)),
        ]))
    cpus = node('cpus', [ph(), ('#address-cells', u32(1)),
                         ('#size-cells', u32(0))], cpu_nodes)

    gic = node('gic', [
        ph(),
        ('compatible', cstr('arm,gic-v3')),
        ('interrupt-controller', b''),
        ('virtual-timer-intid', u32(QEMU_VTIMER_INTID if qemu else VTIMER_INTID)),
        ('reg', u64(gicd - SOC_BASE, GICD_SIZE, gicr - SOC_BASE, GICR_SIZE)),
    ])
    arm_io = node('arm-io', [
        ph(),
        ('device_type', cstr('sweet-io')),
        ('compatible', cstr('sweet-io') + cstr('arm-io')),
        ('#address-cells', u32(2)),
        ('#size-cells', u32(2)),
        ('ranges', u64(0, SOC_BASE, 0x100000000 - SOC_BASE)),
    ], [gic,
        node('wdt', [ph(), ('no-pmu', u32(1))]),
        node('disp0', [
            ph(),
            ('device_type', cstr('display-subsystem')),
            ('compatible', cstr('sweet,display')),
            ('canvas-width', u32(1080 if native else 1125)),
            ('canvas-height', u32(2160 if native else 2436)),
        ])])

    fbcon = node('sweet-fbcon', [
        ph(),
        ('reg', u64(FB, FB_SIZE)),
        ('width', u32(FB_W)),
        ('height', u32(FB_H)),
        ('stride', u32(FB_STRIDE)),
    ])

    # Storage controller nub:
    # sweet_ufs driver checks /sweet-ufs node in SecureDT
    ufs = node('sweet-ufs', [
        ph(),
        ('compatible', cstr('qcom,ufshc') + cstr('qcom,sdhci-msm-v5')),
        ('reg', u64(EMMC, EMMC_SIZE)),
    ])

    defaults = node('defaults', [ph(), ('no-effaceable-storage', u32(1))])

    # Buttons: power and volume
    buttons = node('buttons', [
        ph(),
        ('button-names', cstr('volup') + cstr('voldown') + cstr('hold')),
        ('home-button-type', u32(2)),
        ('opposed-power-vol-buttons', u32(1)),
    ])

    product_props = d22ap_product()
    if product_props:
        product_props = [(k, cstr('sRGB') if k == 'artwork-display-gamut' else v) for k, v in product_props]
    product = [node('product', [ph()] + product_props)] if product_props else []

    return node('device-tree', [
        ph(),
        ('compatible', cstr('D22AP') + cstr('iPhone10,3') + cstr('xiaomi,whyred') + cstr('xiaomi,sweet') + cstr('qcom,sdm636') + cstr('AppleARM')),
        ('model', cstr('iPhone10,3')),
        ('target-type', cstr('D22')),
        ('target-sub-type', cstr('D22AP')),
        ('manufacturer', cstr('Apple Inc.')),
    ], [chosen, cpus, arm_io, fbcon, ufs, defaults, buttons] + product)


def main():
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('out', help='output ADT file')
    p.add_argument('--dump', action='store_true', help='print the tree')
    p.add_argument('--qemu', action='store_true', help='use QEMU virt addresses')
    p.add_argument('--highmem', action='store_true', help='use upper DDR bank above 4G')
    p.add_argument('--midmem', action='store_true', help='use middle DDR bank')
    p.add_argument('--native', action='store_true', help='present native 1080x2160 panel size')
    args = p.parse_args()

    tree = build(qemu=args.qemu, highmem=args.highmem, native=args.native, midmem=args.midmem)
    data = adt.serialize(tree)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, 'wb') as f:
        f.write(data)
    print(f'wrote {len(data)} bytes to {args.out}')
    if args.dump:
        adt.dump(tree)

if __name__ == '__main__':
    main()
