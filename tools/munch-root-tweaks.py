#!/usr/bin/env python3
"""Apply the MUNCH bring-up changes to an iOS root made by tools/mkiosroot.sh.

  sudo munch-root-tweaks.py MOUNTED_ROOT

MOUNTED_ROOT is the HFS+ image mounted read-write (Linux: run
`fsck.hfsplus -fy` on the image, then `mount -t hfsplus -o loop,force`).
Run as root (it writes root/mobile owned files). Idempotent.
"""
import glob, os, plistlib, shutil, sys

BUILD, VERSION = '20H392', '16.7.16'
MOBILE = 501


def load(path):
    with open(path, 'rb') as f:
        return plistlib.load(f)


def save(path, data, uid, gid, mode, fmt=plistlib.FMT_BINARY):
    with open(path, 'wb') as f:
        plistlib.dump(data, f, fmt=fmt)
    os.chown(path, uid, gid)
    os.chmod(path, mode)


def merge_pref(root, name, values):
    """Merge keys into /var/mobile/Library/Preferences/NAME.plist (mobile, 0600)."""
    path = os.path.join(root, 'private/var/mobile/Library/Preferences', name + '.plist')
    data = load(path) if os.path.exists(path) else {}
    data.update(values)
    save(path, data, MOBILE, MOBILE, 0o600)
    print('pref', name, sorted(values))


def launchd(root):
    path = os.path.join(root, 'System/Library/xpc/launchd.plist')
    st = os.stat(path)
    plist = load(path)
    jobs = plist['LaunchDaemons']
    renamed = 0
    for job in jobs.values():
        if '_PanicOnCrash' in job:
            job['_PanicOnCrasX'] = job.pop('_PanicOnCrash')
            renamed += 1
    removed = [k for k, j in jobs.items() if j.get('Label') == 'com.apple.CommCenter']
    for k in removed:
        del jobs[k]
    save(path, plist, st.st_uid, st.st_gid, st.st_mode & 0o7777)
    print(f'launchd.plist: {renamed} _PanicOnCrash renamed, {len(removed)} CommCenter jobs removed')


def containers(root):
    base = os.path.join(root, 'private/var/containers')
    for sub, uid in (('Bundle', 33), ('Data/System', 0), ('Shared/SystemGroup', 0), ('Temp', 0)):
        d = os.path.join(base, sub)
        if not os.path.isdir(d):
            os.makedirs(d)
            os.chown(d, uid, uid)
            os.chmod(d, 0o755)
            print('mkdir', d)


def find_container(root, kind, identifier):
    for meta in glob.glob(os.path.join(root, 'private/var/containers', kind, '*',
                                       '.com.apple.mobile_container_manager.metadata.plist')):
        if load(meta).get('MCMMetadataIdentifier') == identifier:
            return os.path.dirname(meta)
    return None


def activation(root):
    c = find_container(root, 'Data/System', 'com.apple.mobileactivationd')
    if c is None:
        print('warning: no mobileactivationd system container in the image; skipped data ark')
        return
    d = os.path.join(c, 'Library/internal')
    os.makedirs(d, exist_ok=True)
    os.chown(d, MOBILE, MOBILE)
    os.chmod(d, 0o700)
    ark = os.path.join(d, 'data_ark.plist')
    save(ark, {
        '-ActivationState': 'Activated',
        '-BrickState': False,
        '-CloudActivationBypassRecord': b'',
        '-SystemActivationState': 'Activated',
    }, MOBILE, MOBILE, 0o600)
    print('seeded', ark)


def migration(root):
    merge_pref(root, 'com.apple.migration', {
        'LastSystemVersion': BUILD,
        'DMUserDataDisposition': {'DidUpgrade': True, 'BuildVersion': BUILD},
    })


def springboard(root):
    merge_pref(root, 'com.apple.springboard', {
        'BKNoWatchdogs': True,
        'MCForceShowCloudConfigurationUI': False,
    })


def setup(root):
    merge_pref(root, 'com.apple.purplebuddy', {
        'SetupDone': True,
        'SetupFinishedAllSteps': True,
        'SetupVersion': 11,
        'daemonizeNeedsToRun': False,
        'mini-buddy-done': True,
    })
    merge_pref(root, 'com.apple.purplebuddy.notbackedup', {
        'PBAppStoreDone': True,
        'PBAppearanceDone': True,
        'PBBiometricsDone': True,
        'PBBuddyDisplayDone': True,
        'PBCloudConfigDone': True,
        'PBExpressLanguageDone': True,
        'PBHomeButtonDone': True,
        'PBLearnMoreDone': True,
        'PBOnBoardingDone': True,
        'PBPasscodeDone': True,
        'PBSOSDone': True,
        'PBSiriDone': True,
        'PBTermsDone': True,
    })
    merge_pref(root, 'com.apple.managedconfiguration.notbackedup', {
        'LockdownActivationIndicatesCloudConfigurationAvailable': False,
    })


def media(root):
    src = os.path.join(root, 'Library/Audio/Plug-Ins/HAL/VirtualAudio.plugin')
    dst = os.path.join(root, 'Library/Audio/Plug-Ins/HAL.disabled/VirtualAudio.plugin')
    if os.path.exists(src):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(src, dst)
        print('disabled', src)
    mtb = os.path.join(root, 'System/Library/Frameworks/MediaToolbox.framework/MediaToolbox.plist')
    if os.path.exists(mtb):
        p = load(mtb)
        for target in ('D22', 'D221', 'Default'):
            sub = p.get('DeviceSpecific', {}).get(target, {}).get('SubServerConfiguration', {})
            if 'StartRecorderServer' in sub:
                sub['StartRecorderServer'] = False
        save(mtb, p, 0, 0, 0o644)
        print('disabled MediaToolbox StartRecorderServer')


def main(root):
    assert os.path.isdir(os.path.join(root, 'System/Library')), f'{root}: not an iOS root'
    launchd(root)
    containers(root)
    activation(root)
    migration(root)
    springboard(root)
    setup(root)
    media(root)
    print('Done applying MUNCH bring-up tweaks.')


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit(f'usage: sudo {sys.argv[0]} MOUNTED_ROOT')
    main(sys.argv[1])
