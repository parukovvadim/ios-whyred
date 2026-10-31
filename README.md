# ios-whyred

**Apple's iOS 16 running on the Xiaomi Redmi Note 5 / Pro (`whyred`).**

[English](#english) | [Русский](#русский)

---

<a name="русский"></a>
## Русский

Проект портирует ядро Apple XNU (`xnu-8796`, поколение iOS 16) на смартфон **Xiaomi Redmi Note 5 / 5 Pro** (`whyred`, процессор Qualcomm **Snapdragon 636 / SDM636**, архитектура Kryo 260). Поверх ядра работает оригинальный пользовательский раздел **iOS 16.7.16 (20H392) от iPhone X**: `launchd`, системные демоны, `backboardd`, `SpringBoard` и интерфейс iOS.

> **Экспериментальный проект.** Это исследовательский порт для энтузиастов. iOS устанавливается в раздел `userdata` и форматирует пользовательские данные Android. Разделы загрузчика, модема и восстановления не перезаписываются; запуск ядра осуществляется из оперативной памяти командой `fastboot boot`.

---

### Ключевые особенности порта whyred

| Компонент | Значение на whyred | Особенности реализации |
|---|---|---|
| **SoC** | Qualcomm SDM636 | 8 ядер Kryo 260 (4x Cortex-A73 Gold + 4x Cortex-A53 Silver). |
| **Страницы 16K** | Только на Gold (A73) | Ядра Silver (A53) не имеют аппаратной поддержки 16K страниц (`TGran16 = 0`). Шим стартует на Silver CPU0, передает управление ядру Gold `0x100` через PSCI `CPU_ON`, а ядра Silver усыпляет (`wfi`). |
| **Набор команд** | ARMv8.0-A | В процессоре отсутствуют инструкции LSE атомиков (`cas`, `ldadd`, `swp`) и RCpc (`ldapr`). Компиляция ядра выполняется с флагом `-mcpu=cortex-a53`, а атомики iOS эмулируются на уровне ядра в `handle_uncategorized` (`sleh.c`). |
| **Прерывания** | GICv3 | Distributor: `0x17a00000` (64 КБ), Redistributors: `0x17b00000` (1 МБ, 8 ядер). Таймер: PPI 19 (19.2 МГц). |
| **Дисплей** | 1080 × 2160 (18:9) | Буфер continuous splash ABL находится по адресу `0x9d400000` (36 МБ, stride 4320). AppleCLCD транслирует кадры на экран без мерцания. |
| **Хранилище** | eMMC 5.1 | Контроллер `sdhc_1` по адресу `0x0c0c4000`. Раздел `userdata` форматируется в файловую систему HFS+. |
| **Идентичность** | iPhone X (`iPhone10,3`) | Экран без кнопки Home, жестовая навигация, автономная Hactivation через статус дерева устройств. |

---

### Пошаговая инструкция по сборке и установке

#### 0. Резервное копирование телефона
Обязательно сделайте бэкап уникальных разделов через TWRP или OrangeFox:
`persist`, `modemst1`, `modemst2`, `fsg`, `fsc`, а также `boot` и `dtbo`.

#### 1. Сборка ядра XNU на GitHub Actions
Ядро компилируется на бесплатных раннерах GitHub (macOS 14 + Xcode 15):
1. Сделайте Fork этого репозитория на свой аккаунт GitHub.
2. Откройте вкладку **Actions** -> выберите workflow **xnu** -> нажмите **Run workflow**.
3. Дождитесь окончания сборки (~8 минут) и скачайте артефакт `xnu-kernel` в папку `xnu/out/`:
```sh
# Имя собранного ядра:
xnu/out/kernel.development.sweet
```

#### 2. Создание системного образа iOS
Скачайте IPSW-прошивку iPhone X (iPhone10,3) iOS 16.7.16 (20H392) с официального сервера Apple.
На Linux (требуются `apfs-fuse`, `hfsprogs` и `img2simg`):
```sh
# Распаковка и объединение OS, SystemOS и AppOS dmg в единый образ HFS+
sudo bash tools/mkiosroot.sh OS.dmg SystemOS.dmg AppOS.dmg ios16-root.img 16G
sudo fsck.hfsplus -fy ios16-root.img
sudo mount -t hfsplus -o loop,force ios16-root.img /mnt/iosroot

# Применение правок автозапуска (пропуск Setup, активация, отключение вотчдогов)
sudo python3 tools/whyred-root-tweaks.py /mnt/iosroot
sudo umount /mnt/iosroot

# Конвертация в разреженный образ для fastboot
img2simg ios16-root.img ios16-root.simg
```

#### 3. Сборка загрузочного образа (Boot Image)
Требуются кросс-компилятор `aarch64-linux-gnu-gcc` и утилита `mkbootimg`:
```sh
# Генерация дерева устройств Apple (ADT) для whyred:
python3 tools/mkadt.py shim/out/whyred.adt --highmem

# Создание полезной нагрузки (Payload):
python3 tools/mkpayload.py xnu/out/kernel.development.sweet shim/out/whyred.adt shim/out/payload.bin \
    --cmdline 'debug=0xc serial=3 cpus=4 keepsyms=1 -noprogress rd=ufsroot0 unentitled_ios_sim_launch=1 ignition_level=1 wdt_test=no_user_checkin ufsrw=1 rootrw=1 launchd_unsecure_cache=1 wdt=-1 sweetfb_noconsole=1 sweetfb_hz=30 sweetfb_stayon=1'

# Сборка загрузочного шима:
shim/build.sh shim/out/payload.bin
# Результат -> shim/out/shim-boot.img
```

#### 4. Прошивка и запуск
1. Переведите телефон в режим Fastboot (зажмите **Громкость вниз + Питание**).
2. Прошейте системный раздел `userdata`:
```sh
fastboot -S 512M flash userdata ios16-root.simg
```
3. Запустите ядро без прошивки постоянных разделов:
```sh
fastboot boot shim/out/shim-boot.img
```
4. Первый запуск займет около 3-4 минут (пока `launchd` инициализирует базы данных системных служб), после чего появится экран блокировки iOS!

#### 5. Чтение логов отладки
Если что-то пошло не так, лог ядра сохраняется в кольцевой буфер размером 4 МБ в конце раздела `userdata`:
```sh
fastboot boot recovery.img
tools/whyred-log-pull.sh logs/boot.txt
```

---

<a name="english"></a>
## English

`ios-whyred` ports Apple's open-source XNU kernel (`xnu-8796`, iOS 16 generation) to the **Xiaomi Redmi Note 5 / 5 Pro** (`whyred`, Qualcomm **Snapdragon 636 / SDM636** with Kryo 260 CPU).
On top of the kernel runs the unmodified **iOS 16.7.16 (20H392)** userland from the iPhone X (`iPhone10,3` / `D22AP`): `launchd`, system daemons, `backboardd`, and `SpringBoard`.

---

### Hardware Architecture Highlights

- **Kryo 260 Heterogeneous Clusters**:
  - Silver cluster (Cortex-A53) does not support 16K memory translation granules (`TGran16 = 0`).
  - Bootloader enters on Silver CPU0; our bare-metal shim wakes Gold CPU `0x100` via PSCI `CPU_ON` and parks the Silver cluster. XNU runs on the four Gold Cortex-A73 cores.
- **ARMv8.0 Instructions & LSE Emulation**:
  - Cortex-A73 and A53 cores are ARMv8.0.
  - The kernel is compiled with `-mcpu=cortex-a53`.
  - Missing LSE atomic instructions (`cas`, `ldadd`, `swp`, `ldapr`) present in the iPhone X binaries are dynamically emulated in the kernel's synchronous exception handler (`sleh.c`).
- **Display Framebuffer**:
  - Continuous splash buffer at `0x9d400000` (1080 × 2160, stride 4320).
- **Storage Subsystem**:
  - eMMC 5.1 host controller at `0x0c0c4000` (`sdhc_1`).
  - Case-sensitive, journaled HFS+ root volume inside `userdata`.

---

### Repository Layout

```
├── .github/workflows/xnu.yml   # CI automated build of XNU on macOS runners
├── shim/                       # Bare-metal bootloader shim (C & ARM64 ASM)
│   ├── console.c / console.h   # Framebuffer text renderer (0x9d400000, 1080x2160)
│   ├── loader.c                # XNU segment loader & boot_args generator
│   ├── mmu.c / mmu.h           # Early 16K translation table initialization
│   ├── shim.c                  # Core PSCI CPU_ON handoff and GICv3 configuration
│   └── build.sh                # Boot image packaging script
├── tools/                      # Bringup and provisioning utilities
│   ├── mkadt.py                # Apple Device Tree synthesizer for whyred
│   ├── mkpayload.py            # Mach-O chained fixup resolution & packaging
│   ├── mkiosroot.sh            # Root filesystem builder from official IPSW
│   ├── whyred-root-tweaks.py   # Root modifications (Setup bypass, fake activation)
│   ├── whyred-log-pull.sh      # 4MB persistent log extractor via recovery ADB
│   └── qemu-whyred.py          # QEMU aarch64 virtual machine runner
├── xnu/patches/                # Ordered XNU-8796 patch series
├── dts/                        # Hardware DTS/DTSI source definitions for SDM636
├── NOTES.md                    # In-depth technical log & hardware registers
└── CREDITS.md                  # Acknowledgements & open-source licenses
```

---

### Credits

- **[dipa-studio/ios-sweet](https://github.com/dipa-studio/ios-sweet)**: Core XNU Qualcomm bringup, IOSurface/AppleCLCD, and boot shim architecture.
- **[MakrSas/ios-topaz](https://github.com/MakrSas/ios-topaz)**: Kryo 260 / ARMv8.0 compatibility and Gold CPU PSCI handoff implementation.
- **[HackiOS](https://github.com/oosexgang/hackios-xnu-kernel)**: Pioneering iOS bringup on bare-metal Android devices.
- **Apple Inc.**: XNU kernel and open-source system libraries.
