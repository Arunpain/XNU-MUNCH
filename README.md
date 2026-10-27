# ios-munch

**Apple's iOS 16 running on the Xiaomi POCO F4 / Redmi K40S.**

This project ports Apple's open-source XNU kernel (`xnu-8796`, corresponding to the iOS 16 generation) to the **Xiaomi POCO F4 / Redmi K40S** (`munch`, Qualcomm SM8250 / Snapdragon 870), ported from the original [`ios-sweet`](https://github.com/dipa-studio/ios-sweet) project. On top of it runs the **unmodified iOS 16.7.16 (20H392) userland of the iPhone X**: launchd, the system daemons, backboardd, SpringBoard, and the stock apps.

> **Warning:** Experimental bring-up, proof-of-concept project. Many subsystems (cellular, camera, Wi-Fi, SEP) are stubbed or non-functional, and Apple's security model is mostly relaxed. It installs into the `userdata` partition and **erases Android user data**.

---

## Architectural Mapping: Sweet (SM7150) vs Munch (SM8250)

| Subsystem | sweet (Redmi Note 10 Pro) | munch (POCO F4 / Redmi K40S) | Status on Munch |
|---|---|---|---|
| **SoC** | Qualcomm SM7150 (Snapdragon 732G) | Qualcomm SM8250 (Snapdragon 870) | Supported |
| **CPU Cores** | 6x A55 + 2x A76 (Kryo 470) | 4x A55 (1.8GHz) + 3x A77 (2.42GHz) + 1x A77 Prime (3.2GHz) | Supported via PSCI SMP |
| **Arch / Granule** | ARMv8.2-A, no PAC, 16K pages | ARMv8.2-A, no PAC, 16K pages | Identical (`-march=armv8.2-a+crypto`) |
| **GIC** | GICv3 (`0x17a00000`, `0x17a60000`) | GICv3 (`0x17a00000`, `0x17a60000`) | Identical MMIO addresses |
| **Timer / PPI** | Virtual timer INTID 19 | Virtual timer INTID 19 | Identical |
| **Storage** | UFS 2.2 host at `0x01d84000` | UFS 3.1 host at `0x01d84000` | Identical MMIO base & registers |
| **Display** | 1080×2400 AMOLED @ `0x9c000000` | 1080×2400 E4 AMOLED @ `0x9c000000` | Identical splash framebuffer |
| **Touchscreen** | Goodix GT9896 (I²C QUP SE7) | FocalTech FT3658U (`focaltech,fts` on QUP SE4 SPI `0x990000`) | SPI driver / HID hook |
| **Power / Keys** | PM6150 PON + PM6150L GPIO | PM8150 PON + PM8150L GPIO | SPMI / PON consumer keys |
| **Identity** | iPhone X (`iPhone10,3` / `D22AP`) | iPhone X (`iPhone10,3` / `D22AP`) | Identical |

---

## How It Boots

```
Stock Xiaomi Bootloader (ABL, Unlocked)
  -> fastboot boot shim/out/shim-boot.img          (Temporary; never touches boot partition)
     -> Shim loader: 16K MMU setup, reads live FDT, loads Mach-O from ramdisk
        -> XNU Mach-O + generated Apple Device Tree (munch.adt) + boot-args
           -> XNU -> Qualcomm UFS Driver -> HFS+ root in userdata
              -> dyld + shared cache -> launchd -> daemons -> backboardd + SpringBoard
```

---

## Step-by-Step Bring-up Guide

### Prerequisites
1. **Xiaomi POCO F4 / Redmi K40S (`munch`)** with an **unlocked bootloader**.
2. Linux environment (Ubuntu 22.04+ or WSL2) with `hfsprogs`, `apfs-fuse`, `android-tools` (`fastboot`, `adb`), `aarch64-linux-gnu-gcc`, `mkbootimg`, and `python3`.
3. GitHub account to build the XNU kernel via GitHub Actions.

---

### Step 0: Backup Device Partitions
Boot OrangeFox or TWRP recovery via fastboot (`fastboot boot recovery.img`) and backup all critical calibration partitions:
```sh
adb root
adb shell "dd if=/dev/block/by-name/persist of=/tmp/persist.img"
adb shell "dd if=/dev/block/by-name/modemst1 of=/tmp/modemst1.img"
adb shell "dd if=/dev/block/by-name/modemst2 of=/tmp/modemst2.img"
adb shell "dd if=/dev/block/by-name/boot of=/tmp/boot.img"
adb pull /tmp/persist.img backup/
adb pull /tmp/boot.img backup/
```
Unpack your stock kernel `boot.img` to extract the live DTB:
```sh
python3 tools/unpack_bootv2.py backup/boot.img dtb/boot_unpacked
# Output: dtb/boot_unpacked/dtb
```

---

### Step 1: Build the XNU Kernel
Fork this repository and build the XNU kernel via GitHub Actions (macOS runner):
```sh
gh workflow run xnu.yml -R YOUR_USER/ios-munch
gh run download RUN_ID -R YOUR_USER/ios-munch -n xnu-kernel -D xnu/out
```

---

### Step 2: Build the iOS 16 Root Image
Download the official iPhone X (`iPhone10,3`) iOS 16.7.16 (`20H392`) IPSW from Apple.

```sh
# 1. Unpack OS and cryptex DMGs from the IPSW into an HFS+ disk image
tools/mkiosroot.sh OS.dmg SystemOS.dmg AppOS.dmg ios16-root.img 16G

# 2. Check and mount the HFS+ volume
sudo fsck.hfsplus -fy ios16-root.img
sudo mkdir -p /mnt/iosroot
sudo mount -t hfsplus -o loop,force ios16-root.img /mnt/iosroot

# 3. Apply the Munch bring-up tweaks (Setup bypass, mobileactivationd seed, launchd patches)
sudo python3 tools/munch-root-tweaks.py /mnt/iosroot

# 4. Unmount and convert to sparse image for fastboot flashing
sudo umount /mnt/iosroot
img2simg ios16-root.img ios16-root.simg
```

Extract the official iPhone X device tree for identity metadata:
```sh
python3 tools/remotezip.py IPSW_URL DeviceTree.d22ap.im4p research/ipsw-x/dt
ipsw img4 im4p extract research/ipsw-x/dt/Firmware/all_flash/DeviceTree.d22ap.im4p -o research/ipsw-x/d22ap.adt
```

---

### Step 3: Build the Boot Shim
```sh
# 1. Build the Apple Device Tree (ADT) for Munch
python3 tools/mkadt.py shim/out/munch.adt --highmem

# 2. Pack the Mach-O kernel + ADT + boot arguments into the payload
python3 tools/mkpayload.py xnu/out/kernel.development.sweet shim/out/munch.adt shim/out/payload.bin \
    --cmdline 'debug=0xc serial=3 cpus=8 keepsyms=1 -enable_kprintf_spam -noprogress rd=ufsroot0 unentitled_ios_sim_launch=1 ignition_level=1 wdt_test=no_user_checkin ufsrw=1 rootrw=1 launchd_unsecure_cache=1 wdt=-1 sweetfb_noconsole=1 sweetfb_hz=30'

# 3. Compile the bare-metal shim and assemble shim-boot.img
shim/build.sh ../shim/out/payload.bin
# Output: shim/out/shim-boot.img
```

---

### Step 4: Flash Root & Boot
1. Reboot phone to Fastboot mode:
   ```sh
   fastboot -S 512M flash userdata ios16-root.simg
   ```
2. Boot the shim (does not modify `/boot` or permanent partitions):
   ```sh
   fastboot boot shim/out/shim-boot.img
   ```
3. The phone will display the early text console followed by the Apple logo, then progress into the iOS lock screen and SpringBoard home screen.

---

### Step 5: Read Persistent Kernel Console
The kernel writes a 4MB circular log ring into the end of the `userdata` partition. After a run:
1. Hold `Power + Vol Down` into fastboot.
2. Boot temporary recovery: `fastboot boot recovery/recovery.img`
3. Pull and decode the kernel log:
   ```sh
   tools/munch-log-pull.sh logs/munch-boot.txt
   ```

---

## Credits & Acknowledgments
- Based on the pioneering [dipa-studio/ios-sweet](https://github.com/dipa-studio/ios-sweet) project for Redmi Note 10 Pro.
- Uses [blacktop/darwin-xnu-build](https://github.com/blacktop/darwin-xnu-build) for XNU cross-compilation.
