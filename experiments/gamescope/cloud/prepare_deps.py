#!/usr/bin/env python3
"""Fetch verified Debian build dependencies into this workspace, without apt install.

Trust chain: distro-provided archive keyring -> signed InRelease -> Packages.xz
SHA256 -> each .deb SHA256. No maintainer scripts or system modifications.
"""
import concurrent.futures
import argparse
import hashlib
import json
import lzma
import os
from pathlib import Path
import platform
import re
import subprocess
import urllib.request

ROOT = Path('/workspace/DockSR-gamescope-lab')
CACHE = ROOT / 'deps-cache'
PREFIX = ROOT / 'prefix'
BASE = 'https://deb.debian.org/debian/'
SEEDS = '''libwayland-dev libwayland-bin wayland-protocols libx11-dev
libxdamage-dev libxcomposite-dev libxcursor-dev libxrender-dev libxext-dev
libxfixes-dev libxxf86vm-dev libxtst-dev libxres-dev libxmu-dev libxi-dev
libxkbcommon-dev libsdl2-dev libpixman-1-dev libudev-dev libdecor-0-dev
libluajit-5.1-dev libinput-dev libxcb-composite0-dev libxcb-render-util0-dev
libxcb-res0-dev libxcb-xinput-dev libxcb-errors-dev libxcb-ewmh-dev
libxcb-icccm4-dev libxcb-util-dev libxcb-dri3-dev libxcb-present-dev
libxcb-sync-dev libxcb-xfixes0-dev libdrm-dev libseat-dev libdisplay-info-dev
hwdata xwayland libgles-dev libegl-dev libgbm-dev libvulkan-dev libvulkan1 catch2
libsdl2-2.0-0 libdecor-0-0 libinput10 libpixman-1-0 libudev1 libxmu6 libxres1
libice6 libsm6 libxcomposite1 libxcursor1 libxdamage1 libxext6 libxfixes3
libxi6 libxrandr2 libxrender1 libxss1 libxt6t64 libxtst6 libxv1 libxxf86vm1
libxinerama1 libxau6 libxdmcp6
libasound2t64 libblkid1 libcap2 libdbus-1-3 libegl1 libevdev2 libffi8 libgbm1 libgl1 libglib2.0-0t64 libglx0 libgudev-1.0-0 libmount1 libmtdev1t64 libpciaccess0 libpulse-mainloop-glib0 libpulse0 libsamplerate0 libselinux1 libsepol2 libsystemd0 libuuid1 libwacom9 libxcb-dri3-0 libxcb-icccm4 libxcb-present0 libxcb-randr0 libxcb-render-util0 libxcb-render0 libxcb-res0 libxcb-shape0 libxcb-sync1 libxcb-util1 libxcb-xfixes0 libxcb-xinput0 libxcb1'''.split()

def run(*args):
    return subprocess.run(args, check=True, text=True, capture_output=True).stdout

def fetch(url, path, sha=None, size=None):
    if not path.exists():
        with urllib.request.urlopen(url, timeout=120) as response:
            data = response.read()
        path.write_bytes(data)
    data = path.read_bytes()
    if sha and hashlib.sha256(data).hexdigest() != sha:
        raise RuntimeError(f'SHA256 mismatch: {path}')
    if size is not None and len(data) != int(size):
        raise RuntimeError(f'Size mismatch: {path}')
    return data

def fields(raw):
    result = {}
    last = None
    for line in raw.splitlines():
        if line.startswith(' ') and last:
            result[last] += '\n' + line
        elif ': ' in line:
            last, value = line.split(': ', 1)
            result[last] = value
    return result

def relocate_metadata(prefix):
    """Relocate only extracted package metadata, including multiarch SDL."""
    for pc in (prefix/'usr').rglob('*.pc'):
        raw = pc.read_text()
        raw = re.sub(r'(?m)^(\w+=)/usr(?=/|$)',
                     lambda match: match[1]+str(prefix/'usr'), raw)
        raw = raw.replace('-I/usr/', '-I'+str(prefix/'usr')+'/')
        raw = raw.replace('-L/usr/', '-L'+str(prefix/'usr')+'/')
        if pc.name.lower() == 'sdl2.pc':
            include_flag = '-I'+str(prefix/'usr/include/x86_64-linux-gnu')
            if include_flag not in raw:
                raw = re.sub(r'(?m)^Cflags:', 'Cflags: '+include_flag, raw)
        pc.write_text(raw)

def restore_locks(paths, verify_only):
    # A reviewed checked-in lock records artifacts authenticated when created.
    # Replay preserves exact versions/bytes instead of resolving a newer suite.
    # No package scripts are executed and no system path is modified.
    total = 0
    for path in paths:
        manifest = json.loads(Path(path).read_text())
        if manifest.get('repository') != BASE:
            raise RuntimeError('Only the recorded official Debian repository is allowed')
        packages = manifest['packages']
        def acquire(package):
            url = package['url']
            if not url.startswith(BASE+'pool/'):
                raise RuntimeError('Unexpected locked package URL')
            sha = package['sha256']
            if not re.fullmatch('[0-9a-f]{64}', sha):
                raise RuntimeError('Invalid locked SHA256')
            destination = CACHE / Path(url).name
            fetch(url, destination, sha, package['size'])
            return destination
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            acquired = list(executor.map(acquire, packages))
        if not verify_only:
            for artifact in acquired:
                run('dpkg-deb', '--extract', str(artifact), str(PREFIX))
        total += len(acquired)
    if not verify_only:
        relocate_metadata(PREFIX)
    print(f'Verified {total} locked Debian packages'+(' only' if verify_only else f' and extracted into {PREFIX}'))

def main():
    global ROOT, CACHE, PREFIX
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=ROOT, help='Workspace-only dependency/build root')
    parser.add_argument('--restore-lock', type=Path, action='append', default=[], help='Replay reviewed artifact lock, in argument order')
    parser.add_argument('--verify-only', action='store_true', help='Check locked artifacts without extracting; requires --restore-lock')
    parser.add_argument('--suite', choices=['trixie','sid'], default='trixie')
    parser.add_argument('--seeds', nargs='+')
    args = parser.parse_args()
    host = platform.freedesktop_os_release()
    if host.get('ID') != 'debian' or host.get('VERSION_ID') != '13' or platform.machine() != 'x86_64':
        raise RuntimeError('This isolated dependency setup is tested only on Debian 13 x86_64')
    ROOT = args.root.resolve()
    if ROOT == Path('/') or not str(ROOT).startswith(('/workspace/', '/tmp/')):
        raise RuntimeError('Dependency root must be a workspace-owned path under /workspace or /tmp')
    for ancestor in (ROOT, *ROOT.parents):
        marker = ancestor/'.git'
        # Empty /workspace/.git and /tmp/.git are platform guards, not repos.
        if marker.is_file() or (marker.is_dir() and any(marker.iterdir())):
            raise RuntimeError('Keep extracted dependencies outside every Git checkout')
    ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    CACHE, PREFIX = ROOT/'deps-cache', ROOT/'prefix'
    CACHE.mkdir(exist_ok=True)
    PREFIX.mkdir(exist_ok=True)
    if args.restore_lock:
        restore_locks(args.restore_lock, args.verify_only)
        return
    if args.verify_only:
        parser.error('--verify-only requires --restore-lock')
    suite = args.suite
    seeds = args.seeds or SEEDS
    CACHE.mkdir(exist_ok=True)
    PREFIX.mkdir(exist_ok=True)
    gh = ROOT / 'gnupg'
    gh.mkdir(mode=0o700, exist_ok=True)
    release = CACHE / ('InRelease' if suite == 'trixie' else suite+'-InRelease')
    fetch(BASE + 'dists/'+suite+'/InRelease', release)
    verification = run('gpg', '--status-fd', '1', '--homedir', str(gh), '--no-default-keyring',
        '--keyring', '/usr/share/keyrings/debian-archive-keyring.gpg',
        '--verify', str(release))
    (CACHE/(suite+'-signature-verification.txt')).write_text(verification)
    lines = release.read_text().splitlines()
    marker = lines.index('SHA256:')
    expected = None
    for line in lines[marker+1:]:
        if not line.startswith(' '): break
        sha, size, name = line.split()
        if name == 'main/binary-amd64/Packages.xz': expected = sha, size, name
    if not expected: raise RuntimeError('Signed index missing Packages.xz')
    sha, size, name = expected
    data = fetch(BASE + 'dists/'+suite+'/' + name, CACHE/('Packages.xz' if suite == 'trixie' else suite+'-Packages.xz'), sha, size)
    records = [fields(part) for part in lzma.decompress(data).decode().split('\n\n') if part.strip()]
    packages = {r['Package']: r for r in records if r.get('Architecture') in ('all','amd64')}
    providers = {}
    for rec in records:
        for provision in rec.get('Provides', '').split(','):
            match = re.match(r'\s*([\w+.-]+)', provision)
            if match: providers.setdefault(match[1], rec['Package'])
    installed = {}
    for row in run('dpkg-query','-W','-f=${Package}\t${Version}\t${db:Status-Status}\n').splitlines():
        parts = row.split('\t')
        if len(parts) == 3 and parts[2] == 'installed': installed[parts[0].split(':')[0]] = parts[1]
    for lock in ROOT.glob('*dependencies.lock.json'):
        for package in json.loads(lock.read_text())['packages']:
            installed[package['name']] = package['version']
    def satisfied(name, relation, version):
        if name not in installed: return False
        if not relation: return True
        return subprocess.run(['dpkg','--compare-versions',installed[name],relation,version]).returncode == 0
    selected = {}
    todo = [(name, True) for name in seeds]
    while todo:
        name, seed = todo.pop()
        if name in selected: continue
        if name not in packages:
            raise RuntimeError(f'Package unavailable: {name}')
        rec = packages[name]
        selected[name] = rec
        for expression in (rec.get('Pre-Depends','') + ',' + rec.get('Depends','')).split(','):
            alternatives = []
            for alt in expression.split('|'):
                m = re.match(r'\s*([\w+.-]+)(?::\w+)?(?:\s*\(([^ ]+)\s+([^\)]+)\))?', alt)
                if m: alternatives.append(m.groups())
            if not alternatives: continue
            if any(satisfied(*alt) for alt in alternatives): continue
            candidate = next((a[0] if a[0] in packages else providers.get(a[0]) for a in alternatives if a[0] in packages or a[0] in providers), None)
            if candidate is None: raise RuntimeError(f'Unresolved dependency: {name}: {expression}')
            todo.append((candidate, False))
    def acquire(item):
        name, rec = item
        filename = rec['Filename']
        dest = CACHE / Path(filename).name
        fetch(BASE + filename, dest, rec['SHA256'], rec['Size'])
        return name, rec, dest
    acquired = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        for name, rec, dest in executor.map(acquire, sorted(selected.items())):
            acquired.append((name,rec,dest))
    for name,rec,dest in acquired:
        run('dpkg-deb','--extract',str(dest),str(PREFIX))
    relocate_metadata(PREFIX)
    manifest = {'distribution':'Debian '+suite+' amd64','repository':BASE,
      'inrelease_sha256':hashlib.sha256(release.read_bytes()).hexdigest(),
      'packages_index_sha256':sha,'seeds':seeds,
      'packages':[{'name':n,'version':r['Version'],'url':BASE+r['Filename'],
       'sha256':r['SHA256'],'size':int(r['Size'])} for n,r,_ in acquired]}
    lock = ROOT/('dependencies.lock.json' if suite == 'trixie' else suite+'-dependencies.lock.json')
    if lock.exists():
        previous = json.loads(lock.read_text())
        combined = {p['name']: p for p in previous['packages']}
        combined.update({p['name']: p for p in manifest['packages']})
        manifest['packages'] = [combined[n] for n in sorted(combined)]
        manifest['seeds'] = sorted(set(previous['seeds'] + seeds))
    lock.write_text(json.dumps(manifest,indent=2)+'\n')
    print(f'Verified and extracted {len(acquired)} Debian packages into {PREFIX}')

if __name__ == '__main__': main()
