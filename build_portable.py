r"""Baut den portablen Hörbuch-Generator (Windows x64, läuft ohne installiertes Python).

    python -I build_portable.py                 # Zip nach dist\Hoerbuch-Generator_portable_<YYMMDD>.zip
    python -I build_portable.py --dir D:\HB     # zusätzlich entpackt in einen festen Ordner
    python -I build_portable.py --refresh-lock  # Paketliste neu auflösen statt requirements.lock zu nehmen

Ablauf:
 1. Embedded-Python von python.org in derselben Version wie das laufende Python laden (Cache unter
    %LOCALAPPDATA%\\Hoerbuch-Generator\\cache) und nach <build>\\python entpacken.
 2. python3XX._pth um Lib\\site-packages, den Programmordner und "import site" ergänzen.
 3. Pakete mit dem pip des laufenden Pythons nach python\\Lib\\site-packages (nur Wheels). Quelle ist
    requirements.lock, beim ersten Lauf oder mit --refresh-lock requirements.txt; danach wird requirements.lock
    aus dem tatsächlich Installierten geschrieben.
 4. Programmdateien kopieren (ohne out\\, __pycache__ und gemini_key.txt), Fixture für die Tests dazulegen.
 5. Starter hoerbuch.cmd und test.cmd, Kurzanleitung PORTABEL.txt, BUILD_INFO.txt mit Versionen und SHA-256.
 6. Gebaut wird in einem lokalen Temp-Ordner (Drive synchronisiert tausende Einzeldateien langsam), ins Drive
    kommt nur das Zip.
"""
import argparse
import datetime
import hashlib
import importlib.metadata as md
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = 'Hoerbuch-Generator'
APP_FILES = ['hoerbuch.py', 'web.py', 'config.json', 'README.md', 'LICENSE', '.env.example',
             'requirements.txt', 'requirements.lock', 'Starte_Web_UI.bat']
APP_DIRS = ['hb', 'tests']
NEVER = {'gemini_key.txt', 'config.local.json', '.env', '__pycache__', 'out', 'dist', 'published'}

HOERBUCH_CMD = r'''@echo off
rem Hoerbuch-Generator, portabel. Aufruf: hoerbuch.cmd <YouTube-URL oder Textdatei> [Optionen]
rem Hilfe: hoerbuch.cmd --help    Ausgabe: Unterordner out\ neben dieser Datei
setlocal
"%~dp0python\python.exe" -I "%~dp0hoerbuch.py" %*
exit /b %ERRORLEVEL%
'''

TEST_CMD = r'''@echo off
rem Offline-Tests des portablen Hoerbuch-Generators (ohne Netz, ohne Sprachmodell)
setlocal
"%~dp0python\python.exe" -I "%~dp0tests\test_offline.py" %*
exit /b %ERRORLEVEL%
'''

PORTABEL_TXT = '''Hörbuch-Generator, portabel (Windows 10/11, x64)
==================================================

Läuft ohne installiertes Python: Python {pyver} (Embedded, python.org) und alle Pakete liegen in python\\.
ffmpeg kommt aus dem Paket imageio-ffmpeg. Gebaut am {date} mit build_portable.py.

Start:
  Web-Studio (empfohlen):  Doppelklick auf Starte_Web_UI.bat  (öffnet http://127.0.0.1:7865)
  CLI (Eingabeaufforderung/PowerShell in diesem Ordner):

    hoerbuch.cmd https://www.youtube.com/watch?v=... --target tr --helper en --extra de --level A1 --minutes 10
    hoerbuch.cmd --help
    test.cmd                       (Offline-Tests, sollten alle "ok" zeigen)

Gemini-Schlüssel: Umgebungsvariable GEMINI_API_KEY, Datei .env oder gemini_key.txt mit dem Schlüssel neben
hoerbuch.cmd. Schlüsseldateien nicht weitergeben und nicht in ein Zip packen.

Netz braucht es für: YouTube-Transkript, Gemini, edge-tts (Microsoft-Sprachdienst, inoffiziell). Nur privat nutzen.
Ergebnisse landen in out\\<Titel>\\ (MP3, .apkg, README mit Transkript).

Der Ordner lässt sich verschieben oder auf einen USB-Stick kopieren; Pfade sind relativ.
Neu bauen: im Quellordner  python -I build_portable.py
'''


def log(msg):
    print(msg, flush=True)


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def fetch_embed(version, cache):
    os.makedirs(cache, exist_ok=True)
    fname = f'python-{version}-embed-amd64.zip'
    path = os.path.join(cache, fname)
    if not os.path.exists(path):
        url = f'https://www.python.org/ftp/python/{version}/{fname}'
        log(f'Lade {url}')
        tmp = path + '.part'
        with urllib.request.urlopen(url, timeout=120) as r, open(tmp, 'wb') as f:
            shutil.copyfileobj(r, f)
        os.replace(tmp, path)
    with zipfile.ZipFile(path) as z:
        bad = z.testzip()
        if bad:
            raise SystemExit(f'Embedded-Zip beschädigt ({bad}), Cache-Datei löschen: {path}')
    return path


def patch_pth(pydir):
    pths = [f for f in os.listdir(pydir) if f.endswith('._pth')]
    if len(pths) != 1:
        raise SystemExit(f'Erwartet genau eine ._pth-Datei in {pydir}, gefunden: {pths}')
    p = os.path.join(pydir, pths[0])
    lines = [ln.strip() for ln in open(p, encoding='utf-8').read().splitlines()]
    keep = [ln for ln in lines if ln and not ln.startswith('#') and ln != 'import site']
    for extra in ('Lib\\site-packages', '..'):
        if extra not in keep:
            keep.append(extra)
    keep.append('import site')
    with open(p, 'w', encoding='utf-8', newline='\r\n') as f:
        f.write('\n'.join(keep) + '\n')
    return pths[0], keep


def pip_install(site, reqfile):
    cmd = [sys.executable, '-I', '-m', 'pip', 'install', '--target', site, '--only-binary=:all:',
           '--no-warn-script-location', '--disable-pip-version-check', '--no-compile', '-r', reqfile]
    log('pip: ' + ' '.join(os.path.basename(c) if c == sys.executable else c for c in cmd[1:]))
    r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if r.returncode != 0:
        print(r.stdout[-4000:])
        print(r.stderr[-4000:])
        raise SystemExit('pip install fehlgeschlagen')
    for line in r.stdout.splitlines():
        if line.startswith('Successfully installed'):
            log(line)


def installed(site):
    out = {}
    for d in md.distributions(path=[site]):
        n = d.metadata['Name']
        if n:
            out[n.lower()] = d.version
    return dict(sorted(out.items()))


def clean(site):
    shutil.rmtree(os.path.join(site, 'bin'), ignore_errors=True)
    for root, dirs, _ in os.walk(site):
        for d in list(dirs):
            if d == '__pycache__':
                shutil.rmtree(os.path.join(root, d), ignore_errors=True)
                dirs.remove(d)


def copy_app(dst):
    for f in APP_FILES:
        src = os.path.join(HERE, f)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(dst, f))
    ignore = shutil.ignore_patterns(*NEVER, '*.pyc')
    for d in APP_DIRS:
        shutil.copytree(os.path.join(HERE, d), os.path.join(dst, d), ignore=ignore)
    for root, dirs, files in os.walk(dst):
        for f in files:
            if f in NEVER:
                raise SystemExit(f'{f} darf nicht in den portablen Ordner: {root}')


def make_zip(src, zpath, top):
    os.makedirs(os.path.dirname(zpath), exist_ok=True)
    tmp = zpath + '.part'
    n = 0
    with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for root, dirs, files in os.walk(src):
            dirs.sort()
            for f in sorted(files):
                full = os.path.join(root, f)
                arc = os.path.join(top, os.path.relpath(full, src))
                z.write(full, arc)
                n += 1
    os.replace(tmp, zpath)
    return n


def folder_size(path):
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            total += os.path.getsize(os.path.join(root, f))
    return total


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--dir', help='zusätzlich entpackt hierhin (Ordner wird neu angelegt, darf nicht existieren)')
    ap.add_argument('--zip', default=None, help='Zielpfad des Zips (Standard: dist\\Hoerbuch-Generator_portable_<YYMMDD>.zip)')
    ap.add_argument('--no-zip', action='store_true')
    ap.add_argument('--refresh-lock', action='store_true', help='requirements.txt neu auflösen und Lock neu schreiben')
    ap.add_argument('--python', default='.'.join(map(str, sys.version_info[:3])),
                    help='Version des Embedded-Pythons (Standard: die des laufenden Pythons)')
    a = ap.parse_args()

    if sys.platform != 'win32' or sys.maxsize < 2 ** 32:
        raise SystemExit('Nur mit einem 64-Bit-Python unter Windows bauen (Wheels müssen zu win_amd64 passen).')
    if a.python.rsplit('.', 1)[0] != '.'.join(map(str, sys.version_info[:2])):
        raise SystemExit('Embedded-Python muss dieselbe Hauptversion haben wie das bauende Python (Wheel-ABI).')

    stamp = datetime.date.today().strftime('%y%m%d')
    local = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~')
    cache = os.path.join(local, NAME, 'cache')
    build_root = os.path.join(local, NAME, 'build')
    shutil.rmtree(build_root, ignore_errors=True)
    build = os.path.join(build_root, NAME)
    pydir = os.path.join(build, 'python')
    site = os.path.join(pydir, 'Lib', 'site-packages')
    os.makedirs(site)

    embed = fetch_embed(a.python, cache)
    with zipfile.ZipFile(embed) as z:
        z.extractall(pydir)
    pth, pth_lines = patch_pth(pydir)
    log(f'Embedded-Python {a.python} entpackt, {pth}: {" | ".join(pth_lines)}')

    lock = os.path.join(HERE, 'requirements.lock')
    use_lock = os.path.exists(lock) and not a.refresh_lock
    pip_install(site, lock if use_lock else os.path.join(HERE, 'requirements.txt'))
    pkgs = installed(site)
    clean(site)
    if not use_lock:
        with open(lock, 'w', encoding='utf-8', newline='\n') as f:
            f.write(f'# Von build_portable.py am {datetime.date.today():%d.%m.%Y} aus requirements.txt aufgelöst '
                    f'(Python {a.python}, win_amd64). Neu: --refresh-lock\n')
            f.writelines(f'{n}=={v}\n' for n, v in pkgs.items())
        log(f'requirements.lock geschrieben ({len(pkgs)} Pakete)')

    copy_app(build)
    with open(os.path.join(build, 'hoerbuch.cmd'), 'w', encoding='ascii', newline='\r\n') as f:
        f.write(HOERBUCH_CMD)
    with open(os.path.join(build, 'test.cmd'), 'w', encoding='ascii', newline='\r\n') as f:
        f.write(TEST_CMD)
    with open(os.path.join(build, 'PORTABEL.txt'), 'w', encoding='utf-8-sig', newline='\r\n') as f:
        f.write(PORTABEL_TXT.format(pyver=a.python, date=datetime.date.today().strftime('%d.%m.%Y')))
    with open(os.path.join(build, 'BUILD_INFO.txt'), 'w', encoding='utf-8', newline='\r\n') as f:
        f.write(f'Gebaut {datetime.datetime.now():%d.%m.%Y %H:%M} mit build_portable.py\n')
        f.write(f'Embedded-Python {a.python}: {os.path.basename(embed)}  SHA-256 {sha256(embed)}\n')
        f.write(f'Paketquelle: {"requirements.lock" if use_lock else "requirements.txt"}\n\n')
        f.writelines(f'{n}=={v}\n' for n, v in pkgs.items())

    size = folder_size(build)
    log(f'Ordner fertig: {build} ({size / 1e6:.1f} MB)')

    if a.dir:
        if os.path.exists(a.dir):
            raise SystemExit(f'--dir existiert schon, bitte einen neuen Ordner angeben: {a.dir}')
        shutil.copytree(build, a.dir)
        log(f'Entpackt nach {a.dir}')
    if not a.no_zip:
        zpath = a.zip or os.path.join(HERE, 'dist', f'{NAME}_portable_{stamp}.zip')
        n = make_zip(build, zpath, NAME)
        log(f'Zip: {zpath} ({n} Dateien, {os.path.getsize(zpath) / 1e6:.1f} MB)')


if __name__ == '__main__':
    main()
