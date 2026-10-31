# iOS 16 on whyred (Xiaomi Redmi Note 5 / Pro, SDM636) - Engineering Notes

## Overview

This repository ports Apple's open-source XNU kernel (`xnu-8796`, iOS 16 generation) to the **Xiaomi Redmi Note 5 / Pro** (`whyred`, Qualcomm SDM636 Snapdragon 636).
On top of it runs the unmodified **iOS 16.7.16 (20H392)** userland from the iPhone X (`iPhone10,3` / `D22AP`).

---

## Hardware Reference (SDM636 / whyred)

### 1. CPU Architecture & 16K Page Granule
- **Cores**: 8x Kryo 260
  - **Cluster 0 (Silver)**: 4x Cortex-A53 class, MPIDR `0x000`–`0x003`.
    - **No 16K translation granule** (`ID_AA64MMFR0_EL1.TGran16 == 0`).
  - **Cluster 1 (Gold)**: 4x Cortex-A73 class, MPIDR `0x100`–`0x103`.
    - **16K translation granule supported** (`ID_AA64MMFR0_EL1.TGran16 != 0`).
- **Instruction Set**: ARMv8.0-A.
  - No LSE atomics (`cas`, `ldadd`, `swp`).
  - No RCpc (`ldapr`).
  - No PAN (`__ARM_PAN_AVAILABLE__ = 0`).
  - The compiler target is forced to `-mcpu=cortex-a53`.
  - The kernel emulates userland LSE atomics and LDAPR in `handle_uncategorized` (`sleh.c`).
- **Boot Handoff**:
  1. ABL starts execution on Silver CPU0.
  2. The shim checks `ID_AA64MMFR0_EL1`.
  3. Since Silver lacks 16K pages, Silver CPU0 invokes `smc(PSCI_CPU_ON, 0x100, secondary_entry, 4)`.
  4. Silver CPU0 enters an infinite low-power wait loop (`wfi`).
  5. Gold CPU `0x100` wakes up, prepares the GICv3 redistributor, sets up memory, and boots XNU.

---

### 2. MMIO & Peripheral Map

| Subsystem | Physical Address | Size | Description |
|---|---|---|---|
| **GICD** | `0x17a00000` | `0x10000` (64 KiB) | GICv3 Distributor |
| **GICR** | `0x17b00000` | `0x100000` (1 MiB) | GICv3 Redistributors (8 cores, 0x20000 stride) |
| **Splash FB** | `0x9d400000` | `0x23ff000` (~36 MiB) | Continuous splash framebuffer (`cont_splash_mem`) |
| **PS_HOLD** | `0x010ac000` | `0x4` | Power-off / hardware reset register |
| **MSM IMEM** | `0x146bf000` | `0x1000` | Shared internal memory |
| **Restart Reason** | `0x146bf65c` | `0x4` | Bootloader restart reason code (`0x77665500`) |
| **eMMC (SDHC 1)** | `0x0c0c4000` | `0x1000` | Qualcomm SDHCI MSM v5 host controller |
| **SD Card (SDHC 2)**| `0x0c084000` | `0x1000` | External MicroSD slot |
| **I2C 1 (BLSP QUP)**| `0x0c175000` | `0x600` | Touchscreen bus (Novatek / Synaptics) |
| **Timer PPI** | INTID 19 | PPI | Virtual timer interrupt (frequency: 19.2 MHz) |

---

### 3. Display Subsystem
- **Panel**: 5.99" IPS LCD, 1080 × 2160 pixels (18:9 aspect ratio, ~403 ppi).
- **Mode**: MIPI DSI Video Mode (`dsi_nt36672_tianma_fhd_video`, `dsi_td4310_shenchao_fhd_video`, etc.).
- **Continuous Splash**: Memory mapped at `0x9d400000`. Stride is `1080 * 4 = 4320` bytes (BGRA32).
- **Presentation**: Exposed to iOS via AppleCLCD as an iPhone X canvas (`1125 × 2436`) or native (`1080 × 2160`).

---

### 4. Storage Architecture
- Unlike newer devices (e.g. `sweet` with UFS 2.2), `whyred` utilizes an **eMMC 5.1** controller at `0x0c0c4000` (`sdhc_1`).
- The iOS root filesystem is formatted as a case-sensitive, journaled HFS+ image and installed into the `userdata` partition.
- The kernel uses a polled block driver to read and write GPT partitions without requiring complex interrupts during early boot.

---

### 5. Memory Map & Carve-Outs
- **Lower DDR Bank**: `0x80000000` – `0x100000000` (2 GiB).
  - Modem, TrustZone, PIL, ADSP, CDSP, and continuous splash carve-outs reside between `0x85600000` and `0x9f800000`.
  - Clean space above carveouts: `0xb0000000` – `0xfd000000` (~1.25 GiB).
- **Upper DDR Bank (Highmem)**: `0x100000000` (4 GiB boundary).
  - 4 GB RAM model: `0x100000000` to `0x180000000` (2 GiB completely unencumbered memory).
  - 6 GB RAM model: `0x100000000` to `0x200000000` (4 GiB unencumbered memory).

---

## Boot Sequence

```
[Xiaomi LK / ABL Bootloader]
      │
      ▼  fastboot boot shim-boot.img (Android boot image v1/v2)
[Bare-Metal Boot Shim on Silver CPU0]
      │
      ├─► Checks ID_AA64MMFR0_EL1 (TGran16 == 0)
      ├─► Wakes Gold CPU 0x100 via PSCI CPU_ON
      └─► Silver CPU0 enters WFI sleep loop
            │
            ▼
[Boot Shim on Gold CPU 0x100]
      │
      ├─► Sets up GICv3 Distributor & Redistributor Group 1
      ├─► Prepares secondary Gold redistributors (0x101 - 0x103)
      ├─► Relocates XNU Mach-O segments to physBase
      ├─► Synthesizes Apple Device Tree (ADT)
      ├─► Populates boot_args structure (Video, cmdline, memory)
      └─► Jumps to XNU entry point (MMU off)
            │
            ▼
[Apple XNU Kernel (xnu-8796)]
      │
      ├─► Initializes MMU (16K pages, identity mapping)
      ├─► Boots SweetPlatformExpert & SweetCPU (Gold 0x100)
      ├─► Attaches AppleCLCD framebuffer console (0x9d400000)
      ├─► Mounts HFS+ root from userdata partition
      ├─► Dyld maps shared cache from /System/Cryptexes/OS
      └─► Launches launchd (PID 1)
            │
            ▼
[iOS 16.7.16 Userland]
      ├─► launchd starts essential daemons
      ├─► backboardd initializes WindowServer & IOSurface
      └─► SpringBoard presents the iOS UI
```
