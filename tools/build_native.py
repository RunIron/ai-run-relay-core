"""Run on the target OS. Never publish build directories or owner source archives."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import sysconfig
import tarfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from relay import __version__ as VERSION


def run(*args):
    subprocess.run([str(x) for x in args], cwd=ROOT, check=True)


def audit(folder):
    forbidden = {'.py', '.pyc', '.pyo', '.sqlite3', '.db', '.pem', '.key', '.pdb', '.c', '.cpp'}
    for path in folder.rglob('*'):
        if path.is_symlink() or path.suffix.lower() in forbidden or path.name in {'.git', 'auth.json', 'config.toml'}:
            raise RuntimeError(f'Unexpected private/source file in runtime: {path}')


def licenses(destination):
    """Keep interpreter and GUI license notices with the embedded runtime."""
    target = destination / 'licenses'
    target.mkdir(exist_ok=True)
    python_license = Path(sysconfig.get_path('stdlib')) / 'LICENSE.txt'
    if not python_license.exists():
        python_license = Path(sys.base_prefix) / 'LICENSE.txt'
    if not python_license.exists():
        raise RuntimeError('Cannot locate Python LICENSE.txt; do not distribute without it')
    shutil.copy2(python_license, target / 'PYTHON-LICENSE.txt')
    import tkinter
    tcl_lib = Path(tkinter.Tcl().eval('info library'))
    found = list(tcl_lib.glob('license*')) + list(tcl_lib.parent.glob('tk*/license*'))
    # Linux distro builds may store notices under /usr/share/doc.
    if sys.platform == 'linux':
        found += list(Path('/usr/share/doc').glob('libtcl*/copyright'))
        found += list(Path('/usr/share/doc').glob('libtk*/copyright'))
    if not found:
        found = list((ROOT / 'packaging/licenses').glob('*-LICENSE.txt'))
    if not found:
        raise RuntimeError('Cannot locate Tcl/Tk license notices')
    for i, file in enumerate(found):
        shutil.copy2(file, target / f'TCL-TK-{i}.txt')
    compiler = importlib.metadata.distribution('Nuitka')
    for file in compiler.files:
        if file.name in ('LICENSE.txt', 'LICENSE-RUNTIME.txt', 'NOTICE.txt') and 'licenses' in file.parts:
            shutil.copy2(compiler.locate_file(file), target / ('NUITKA-' + file.name))


def repair_tcl_runtime(dist):
    # Tcl 9 from standalone Python builds is not recognized by all Nuitka DLL rules.
    if sys.platform != 'linux':
        return
    for name in ('libtcl9.0.so', 'libtcl9tk9.0.so'):
        source = Path(sys.base_prefix) / 'lib' / name
        if source.exists() and not (dist / name).exists():
            shutil.copy2(source, dist / name)
            run('patchelf', '--set-rpath', '$ORIGIN', dist / name)
    for path in dist.glob('*.so*'):
        result = subprocess.run(['ldd', str(path)], capture_output=True, text=True, check=True)
        if 'not found' in result.stdout:
            raise RuntimeError(f'Missing runtime libraries for {path.name}: {result.stdout}')


def linux_packages(dist, out):
    name = f'AI-Run-Relay-{VERSION}-linux-x86_64'
    with tarfile.open(out / (name + '.tar.gz'), 'w:gz') as archive:
        archive.add(dist, arcname=name)
    stage = ROOT / 'build' / 'deb-root'
    shutil.rmtree(stage, ignore_errors=True)
    shutil.copytree(dist, stage / 'opt' / 'ai-run-relay')
    control = stage / 'DEBIAN'
    control.mkdir()
    # Use the build host's glibc floor. Do not label a 24.04 build as 22.04 compatible.
    libc_version = platform.libc_ver()[1]
    if not libc_version:
        raise RuntimeError('Cannot determine glibc version')
    (control / 'control').write_text(
        f'Package: ai-run-relay\nVersion: {VERSION}\nArchitecture: amd64\n'
        'Maintainer: AI Run Relay <runiron.wu@gmail.com>\nSection: utils\nPriority: optional\n'
        f'Depends: libc6 (>= {libc_version}), libx11-6, libxext6, libxrender1, libxft2, libfontconfig1, libfreetype6\n'
        'Description: Local AI work queue and quota-aware relay\n'
        ' Personal noncommercial use; commercial use requires written authorization.\n', encoding='utf-8')
    bins = stage / 'usr/bin'
    bins.mkdir(parents=True)
    launcher = bins / 'ai-run-relay'
    launcher.write_text('#!/bin/sh\nexec /opt/ai-run-relay/ai-run-relay "$@"\n')
    launcher.chmod(0o755)
    apps = stage / 'usr/share/applications'
    apps.mkdir(parents=True)
    shutil.copy2(ROOT / 'packaging/ai-run-relay.desktop', apps)
    run('dpkg-deb', '--root-owner-group', '--build', stage,
        out / f'AI-Run-Relay-{VERSION}-linux-amd64.deb')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--iscc', help='Path to Inno Setup ISCC.exe on Windows')
    args = parser.parse_args()
    if platform.machine().lower() not in ('amd64', 'x86_64') or sys.platform not in ('linux', 'win32'):
        raise SystemExit('This build currently targets Windows/Linux x86_64 only')
    out = ROOT / 'release-native'
    out.mkdir(exist_ok=True)
    if list(out.iterdir()):
        raise SystemExit('release-native must be empty: move previous release files before building')
    binary = 'AI-Run-Relay.exe' if os.name == 'nt' else 'ai-run-relay'
    command = [sys.executable, '-m', 'nuitka', '--mode=standalone', '--enable-plugin=tk-inter',
        '--include-package=relay', '--include-data-files=relay/static/index.html=relay/static/index.html',
        '--output-dir=build/native', f'--output-filename={binary}', '--assume-yes-for-downloads',
        '--jobs=2']
    if os.name == 'nt':
        command += ['--msvc=latest', '--windows-console-mode=attach',
                    '--product-name=AI Run Relay', f'--product-version={VERSION}.0']
    command.append('launcher.py')
    run(*command)
    dist = ROOT / 'build/native/launcher.dist'
    finish(dist, out, binary, args.iscc)


def finish(dist, out, binary, iscc=None):
    repair_tcl_runtime(dist)
    # Tcl/Tk distributions contain public C embedding examples, unused at runtime.
    for example in ('tcl/tclAppInit.c', 'tk/tkAppInit.c'):
        (dist / example).unlink(missing_ok=True)
    shutil.copy2(ROOT / 'LICENSE', dist / 'LICENSE.txt')
    shutil.copy2(ROOT / 'public/INSTALL.md', dist / 'START-HERE.txt')
    licenses(dist)
    audit(dist)
    report = ROOT / 'build/native-smoke.json'
    report.unlink(missing_ok=True)
    run(dist / binary, '--self-test', report)
    if json.loads(report.read_text())['ok'] is not True:
        raise RuntimeError('Compiled application smoke test failed')
    if os.name == 'nt':
        iscc = iscc or shutil.which('ISCC') or r'C:\Program Files (x86)\Inno Setup 6\ISCC.exe'
        run(iscc, f'/DAppVersion={VERSION}', ROOT / 'packaging/windows.iss')
    else:
        linux_packages(dist, out)
    files = list(out.iterdir())
    manifest = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files if p.is_file()}
    (out / 'SHA256SUMS.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(f'Built and mock-tested runtime packages in {out}. Real Codex still requires separate testing.')


if __name__ == '__main__':
    main()
