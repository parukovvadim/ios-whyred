# Credits & Acknowledgements

`ios-whyred` builds upon research, open-source code, and reverse engineering from the following projects:

1. **[dipa-studio/ios-sweet](https://github.com/dipa-studio/ios-sweet)**
   - Apple's XNU kernel bringup on Qualcomm hardware
   - Bare-metal boot shim and page-table initialization
   - IOSurface, AppleCLCD, and persistent logging architecture
   - Apple Device Tree synthesis (`tools/mkadt.py`)

2. **[MakrSas/ios-topaz](https://github.com/MakrSas/ios-topaz)**
   - Kryo 260 / ARMv8.0 compatibility architecture
   - Handoff from Cortex-A53 Silver to Cortex-A73 Gold cores for 16K translation granule
   - Commpage CASA LDAXR/STXR loop
   - Userland atomic LSE emulation in `sleh.c`

3. **[HackiOS](https://github.com/oosexgang/hackios-xnu-kernel)**
   - Pioneering iOS 16 bringup on bare-metal Android devices
   - GPU presentation and audio subsystem research

4. **Apple Open Source**
   - XNU kernel (`xnu-8796`, macOS 13.5 / iOS 16 generation)
   - IOHIDFamily (`IOHIDFamily-1915.140.3`)
   - libpthread and HFS filesystem implementations

5. **Tooling & Cryptography**
   - [blacktop/darwin-xnu-build](https://github.com/blacktop/darwin-xnu-build) and [blacktop/ipsw](https://github.com/blacktop/ipsw)
   - [BearSSL](https://bearssl.org) by Thomas Pornin

*Note: iOS, iPhone, and Apple are registered trademarks of Apple Inc. This project is independent and not affiliated with Apple.*
