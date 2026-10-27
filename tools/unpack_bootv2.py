#!/usr/bin/env python3
"""Unpack an Android boot image (header v0-v4) or vendor_boot image into kernel/ramdisk/dtb + header.txt."""
import os, struct, sys

if len(sys.argv) < 3:
    sys.exit(f"usage: {sys.argv[0]} BOOT_OR_VENDOR_BOOT_IMG OUT_DIR")

src, out = sys.argv[1], sys.argv[2]
os.makedirs(out, exist_ok=True)
b = open(src, 'rb').read()

magic = b[:8]

if magic == b'ANDROID!':
    header_version = struct.unpack_from('<I', b, 40)[0]
    if header_version >= 3:
        # Boot image header v3 / v4
        ks, rs, osv, hs = struct.unpack_from('<4I', b, 8)
        ps = 4096  # Android header v3/v4 page size is fixed at 4096
        cmd = b[44:44+1536].split(b'\0')[0]
        info = {
            'format': f'boot_header_v{header_version}',
            'kernel_size': ks,
            'ramdisk_size': rs,
            'os_version': hex(osv),
            'header_size': hs,
            'page_size': ps,
            'header_version': header_version,
            'cmdline': cmd.decode(errors='replace')
        }
        rnd = lambda n: (n + ps - 1) // ps * ps
        off = ps
        # Kernel
        if ks:
            open(os.path.join(out, 'kernel'), 'wb').write(b[off:off+ks])
        info['kernel_offset'] = off
        off += rnd(ks)
        # Ramdisk
        if rs:
            open(os.path.join(out, 'ramdisk'), 'wb').write(b[off:off+rs])
        info['ramdisk_offset'] = off
        off += rnd(rs)

        print(f"Unpacked boot image header v{header_version} to {out}")
        print("Note: On Android Header v3/v4, the device DTB is stored in 'vendor_boot.img'.")
    else:
        # Header v0 - v2
        ks, ka, rs, ra, ss, sa, ta, ps, ver, osv = struct.unpack_from('<10I', b, 8)
        cmd = b[64:64+512].split(b'\0')[0] + b[608:608+1024].split(b'\0')[0]
        info = dict(kernel_size=ks, kernel_addr=hex(ka), ramdisk_size=rs, ramdisk_addr=hex(ra),
                    second_size=ss, tags_addr=hex(ta), page_size=ps, header_version=ver,
                    os_version=hex(osv), name=b[48:64].split(b'\0')[0].decode(errors='replace'),
                    cmdline=cmd.decode(errors='replace'))
        rnd = lambda n: (n + ps - 1) // ps * ps
        off = ps
        parts = [('kernel', ks), ('ramdisk', rs), ('second', ss)]
        if ver >= 1:
            rds, rdo, hs = struct.unpack_from('<IQI', b, 1632)
            parts.append(('recovery_dtbo', rds)); info['header_size'] = hs
        if ver >= 2:
            ds, da = struct.unpack_from('<IQ', b, 1648)
            parts.append(('dtb', ds)); info['dtb_addr'] = hex(da)
        for name, sz in parts:
            if sz:
                open(os.path.join(out, name), 'wb').write(b[off:off+sz])
            info[name + '_offset'] = off
            off += rnd(sz)

elif magic == b'VNDRBOOT':
    # Vendor boot header v3 / v4
    ver = struct.unpack_from('<I', b, 8)[0]
    ps, ka, ra, vrs = struct.unpack_from('<4I', b, 12)
    cmd = b[28:28+2048].split(b'\0')[0]
    ta = struct.unpack_from('<I', b, 2076)[0]
    name = b[2080:2080+16].split(b'\0')[0].decode(errors='replace')
    hs, ds = struct.unpack_from('<2I', b, 2096)
    da = struct.unpack_from('<Q', b, 2104)[0]
    info = dict(format=f'vendor_boot_v{ver}', header_version=ver, page_size=ps,
                kernel_addr=hex(ka), ramdisk_addr=hex(ra), vendor_ramdisk_size=vrs,
                cmdline=cmd.decode(errors='replace'), tags_addr=hex(ta), name=name,
                header_size=hs, dtb_size=ds, dtb_addr=hex(da))
    rnd = lambda n: (n + ps - 1) // ps * ps
    off = ps
    if vrs:
        open(os.path.join(out, 'vendor_ramdisk'), 'wb').write(b[off:off+vrs])
        info['vendor_ramdisk_offset'] = off
        off += rnd(vrs)
    if ds:
        open(os.path.join(out, 'dtb'), 'wb').write(b[off:off+ds])
        info['dtb_offset'] = off
        off += rnd(ds)
    print(f"Unpacked vendor_boot header v{ver} to {out} (extracted DTB: {ds} bytes)")

else:
    sys.exit(f"Unrecognized image magic: {magic}")

with open(os.path.join(out, 'header.txt'), 'w') as f:
    for k, v in info.items():
        f.write(f'{k}: {v}\n')
print(open(os.path.join(out, 'header.txt')).read())
