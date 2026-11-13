"""Grafische Web-Oberfläche (Stufe 2) für den Hörbuch-Generator.

Läuft lokal ohne zusätzliche Web-Frameworks (nutzt Pythons eingebautes http.server + das Paket hb),
funktioniert daher sowohl mit dem globalen Python 3.12 als auch direkt im portablen Embedded-Python-Ordner.

Aufruf:
  python -I web.py                    # startet lokalen Server auf http://127.0.0.1:7865 und öffnet den Browser
  python -I web.py --port 8080        # anderer Port
  python -I web.py --no-browser       # nur Server starten (z. B. für Tests)
"""
import argparse
import functools
import http.server
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse
import webbrowser

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import hoerbuch  # noqa: E402
from hb import anki, audio, check, known as known_mod, languages as L, llm, load_config, readme, resolve_path, script as S  # noqa: E402

OUT_DIR = os.path.join(ROOT, 'out')


def load_cfg():
    llm.load_dotenv()
    return load_config(os.path.join(ROOT, 'config.json'))


def get_publish_dir(cfg=None):
    cfg = cfg if cfg is not None else load_cfg()
    raw = os.environ.get('HOERBUCH_PUBLISH') or cfg.get('publish_dir') or 'published'
    return resolve_path(raw, base=ROOT)


def get_known_path(cfg=None):
    cfg = cfg if cfg is not None else load_cfg()
    raw = os.environ.get('HOERBUCH_KNOWN') or cfg.get('known_path') or ''
    return resolve_path(raw, base=ROOT) if raw else ''


class JobState:
    def __init__(self):
        self.lock = threading.Lock()
        self.running = False
        self.step = ''
        self.step_index = 0
        self.total_steps = 6
        self.logs = []
        self.error = None
        self.slug = None
        self.started_at = None
        self.finished_at = None
        self.params = {}

    def reset(self, params, total_steps):
        with self.lock:
            self.running = True
            self.step = 'Start'
            self.step_index = 0
            self.total_steps = total_steps
            self.logs = []
            self.error = None
            self.slug = params.get('name') or None
            self.started_at = time.time()
            self.finished_at = None
            self.params = params

    def log(self, msg):
        text = str(msg)
        with self.lock:
            self.logs.append({'t': round(time.time() - (self.started_at or time.time()), 1), 'msg': text})
            if text.startswith('Ordner: '):
                self.slug = os.path.basename(text.split('Ordner: ', 1)[1].strip())
            elif text.startswith('YouTube ') or text.startswith('Webseite:') or text.startswith('Datei ') or text.startswith('Direkter Text'):
                self.step = '1/6 Quelle'
                self.step_index = 1
            elif text.startswith('Fassung:'):
                self.step = '2/6 Skript (Gemini)'
                self.step_index = 2
            elif text.startswith('Korrektor-Durchlauf') or text.startswith('Prüfung:'):
                self.step = '3/6 Qualitätsprüfung'
                self.step_index = 3
            elif text.startswith('Sprachclips:') or text.startswith('MP3:'):
                self.step = '4/6 Audio-Synthese (edge-tts)'
                self.step_index = 4
            elif text.startswith('Anki:'):
                self.step = '5/6 Anki-Deck (.apkg)'
                self.step_index = 5
            elif text.startswith('README:'):
                self.step = '6/6 Dokumentation'
                self.step_index = 6
            elif text.startswith('Fertig.'):
                self.step = 'Abgeschlossen'
                self.step_index = self.total_steps

    def snapshot(self):
        with self.lock:
            now = self.finished_at or time.time()
            elapsed = round(now - self.started_at, 1) if self.started_at else 0.0
            return {
                'running': self.running,
                'step': self.step,
                'step_index': self.step_index,
                'total_steps': self.total_steps,
                'logs': list(self.logs),
                'error': self.error,
                'slug': self.slug,
                'elapsed_sec': elapsed,
                'params': self.params,
            }


JOB = JobState()


def has_api_key():
    try:
        return bool(llm._key())
    except Exception:
        return False


def api_meta():
    cfg = load_cfg()
    known_path = get_known_path(cfg)
    publish_dir = get_publish_dir(cfg)
    known_info = {'path': known_path, 'exists': False, 'total': 0, 'known': 0, 'sample': []}
    if known_path and os.path.exists(known_path):
        try:
            entries = known_mod.load(known_path)
            words = known_mod.known_words(entries)
            known_info = {
                'path': known_path,
                'exists': True,
                'total': len(entries),
                'known': len(words),
                'sample': words[:25],
            }
        except Exception:
            pass
    pub_count = 0
    if publish_dir and os.path.isdir(publish_dir):
        pub_count = sum(1 for f in os.listdir(publish_dir) if f.lower().endswith('.mp3'))
    langs = {}
    for code, info in L.LANGS.items():
        langs[code] = {
            'code': code,
            'name_en': info['name_en'],
            'name_de': info['name_de'],
            'name_native': info['name_native'],
            'voices': info['voices'],
            'chapter': info['chapter'],
            'rules': info['rules'],
        }
    return {
        'languages': langs,
        'levels': list(L.LEVELS),
        'config': cfg,
        'known_info': known_info,
        'default_publish': publish_dir,
        'publish_label': os.path.basename(publish_dir.rstrip('\\/')) or publish_dir,
        'published_mp3_count': pub_count,
        'has_api_key': has_api_key(),
    }


def api_plan(minutes=10.0, level='A1', vocab=None, sentences=None):
    cfg = load_cfg()
    v = int(vocab) if vocab not in (None, '', 0, '0') else None
    s = int(sentences) if sentences not in (None, '', 0, '0') else None
    return S.plan(float(minutes), str(level), cfg.get('chapter_size', 15), vocab=v, sentences=s)


def _book_summary(slug):
    folder = os.path.join(OUT_DIR, slug)
    if not os.path.isdir(folder):
        return None
    script_path = os.path.join(folder, 'script.json')
    seg_path = os.path.join(folder, 'segments.json')
    check_path = os.path.join(folder, 'check.json')
    sc = {}
    if os.path.exists(script_path):
        try:
            with open(script_path, encoding='utf-8') as f:
                sc = json.load(f)
        except Exception:
            sc = {}
    dur = None
    if os.path.exists(seg_path):
        try:
            with open(seg_path, encoding='utf-8') as f:
                dur = json.load(f).get('total')
        except Exception:
            pass
    chk_counts = {'error': 0, 'warn': 0, 'hint': 0, 'applied': 0}
    if os.path.exists(check_path):
        try:
            with open(check_path, encoding='utf-8') as f:
                cj = json.load(f)
            for lvl, _, _ in cj.get('findings', []):
                if lvl in chk_counts:
                    chk_counts[lvl] += 1
            chk_counts['applied'] = len(cj.get('applied', []))
        except Exception:
            pass
    files = os.listdir(folder)
    mp3s = [f for f in files if f.lower().endswith('.mp3')]
    apkgs = [f for f in files if f.lower().endswith('.apkg')]
    readmes = [f for f in files if f.startswith('README_AND_TRANSCRIPT_') and f.endswith('.md')]
    mp3_file = mp3s[0] if mp3s else None
    apkg_file = apkgs[0] if apkgs else None
    readme_file = readmes[0] if readmes else None
    publish_dir = get_publish_dir()
    published = bool(mp3_file and publish_dir and os.path.isdir(publish_dir)
                     and os.path.exists(os.path.join(publish_dir, mp3_file)))
    sents = S.all_sentences(sc) if sc.get('chapters') else []
    mtime = os.path.getmtime(script_path) if os.path.exists(script_path) else os.path.getmtime(folder)
    return {
        'slug': slug,
        'short_title': sc.get('short_title') or slug.replace('_', ' '),
        'title_helper': sc.get('title_helper') or slug.replace('_', ' '),
        'title_target': sc.get('title_target') or '',
        'target': sc.get('target', 'tr'),
        'helper': sc.get('helper', 'en'),
        'extra': sc.get('extra'),
        'level': sc.get('level', 'A1'),
        'intro': sc.get('intro', ''),
        'source': sc.get('source', {}),
        'sentences_count': len(sents),
        'vocab_count': len(sc.get('vocab', [])),
        'chapters_count': len(sc.get('chapters', [])),
        'duration_sec': round(dur, 1) if dur else None,
        'duration_fmt': audio.fmt(dur) if dur else None,
        'mp3_file': mp3_file,
        'apkg_file': apkg_file,
        'readme_file': readme_file,
        'has_cover': os.path.exists(os.path.join(folder, 'cover.jpg')),
        'has_script': bool(sc),
        'check_counts': chk_counts,
        'published': published,
        'mtime': mtime,
    }


def api_list_books():
    if not os.path.isdir(OUT_DIR):
        return []
    items = []
    for name in os.listdir(OUT_DIR):
        info = _book_summary(name)
        if info:
            items.append(info)
    items.sort(key=lambda x: x['mtime'], reverse=True)
    return items


def api_get_book(slug):
    slug = S.safe_filename(slug)
    summary = _book_summary(slug)
    if not summary:
        return None
    folder = os.path.join(OUT_DIR, slug)
    script_path = os.path.join(folder, 'script.json')
    check_md_path = os.path.join(folder, 'check.md')
    check_json_path = os.path.join(folder, 'check.json')
    seg_path = os.path.join(folder, 'segments.json')
    sc = json.load(open(script_path, encoding='utf-8')) if os.path.exists(script_path) else None
    check_md = open(check_md_path, encoding='utf-8').read() if os.path.exists(check_md_path) else ''
    check_json = json.load(open(check_json_path, encoding='utf-8')) if os.path.exists(check_json_path) else {}
    segments = []
    tl = []
    if os.path.exists(seg_path):
        seg_data = json.load(open(seg_path, encoding='utf-8'))
        segments = seg_data.get('segments', [])
        total = seg_data.get('total', 0)
        if segments:
            tl = audio.timeline(segments, total)
    readme_md = ''
    if summary['readme_file']:
        rp = os.path.join(folder, summary['readme_file'])
        if os.path.exists(rp):
            readme_md = open(rp, encoding='utf-8').read()
    return {
        'summary': summary,
        'script': sc,
        'check_md': check_md,
        'check_json': check_json,
        'segments': segments,
        'timeline': tl,
        'readme_md': readme_md,
    }


def api_save_script(slug, new_script):
    slug = S.safe_filename(slug)
    folder = os.path.join(OUT_DIR, slug)
    script_path = os.path.join(folder, 'script.json')
    if not os.path.isdir(folder):
        raise ValueError(f'Ordner {slug} existiert nicht.')
    # Nummerierung konsistent halten
    n = 0
    for ch in new_script.get('chapters', []):
        for s in ch.get('sentences', []):
            n += 1
            s['n'] = n
            s['target'] = str(s.get('target', '')).strip()
            s['helper'] = str(s.get('helper', '')).strip()
    for i, v in enumerate(new_script.get('vocab', []), 1):
        v['n'] = i
        v['target'] = str(v.get('target', '')).strip()
        v['helper'] = str(v.get('helper', '')).strip()
        v['note'] = str(v.get('note', '')).strip()
    known_words = None
    known_path = get_known_path()
    if known_path and os.path.exists(known_path):
        try:
            known_words = known_mod.known_words(known_mod.load(known_path))
        except Exception:
            pass
    findings = check.deterministic(new_script, known=known_words)
    with open(script_path, 'w', encoding='utf-8') as f:
        json.dump(new_script, f, ensure_ascii=False, indent=1)
    md = check.report_md(new_script, findings, None, [], [])
    with open(os.path.join(folder, 'check.md'), 'w', encoding='utf-8') as f:
        f.write(md)
    with open(os.path.join(folder, 'check.json'), 'w', encoding='utf-8') as f:
        json.dump({'findings': findings, 'review': None, 'applied': []}, f, ensure_ascii=False, indent=1)
    return {'ok': True, 'findings': findings, 'check_md': md}


def api_publish_book(slug, target_dir=None):
    slug = S.safe_filename(slug)
    summary = _book_summary(slug)
    if not summary:
        raise ValueError(f'Hörbuch {slug} nicht gefunden.')
    folder = os.path.join(OUT_DIR, slug)
    dest = resolve_path(target_dir) if target_dir else get_publish_dir()
    os.makedirs(dest, exist_ok=True)
    copied = []
    for key in ('mp3_file', 'apkg_file', 'readme_file'):
        fname = summary.get(key)
        if fname:
            src = os.path.join(folder, fname)
            if os.path.exists(src):
                shutil.copy2(src, dest)
                copied.append(fname)
    return {'ok': True, 'dest': dest, 'copied': copied}


def start_job(params):
    if JOB.running:
        raise RuntimeError('Es läuft bereits ein Auftrag.')
    inp = str(params.get('input', '')).strip()
    steps = str(params.get('steps', 'all')).strip() or 'all'
    slug = params.get('slug')
    if not inp and slug:
        # Bestehendes Hörbuch weiterverarbeiten (z. B. audio,anki,readme)
        src_json = os.path.join(OUT_DIR, S.safe_filename(slug), 'source.json')
        if os.path.exists(src_json):
            with open(src_json, encoding='utf-8') as f:
                sd = json.load(f)
            inp = sd.get('url') or sd.get('text') or slug
        else:
            inp = slug
    if not inp:
        raise ValueError('Bitte eine YouTube-URL, Webseite, Datei oder einen Text eingeben.')

    api_key = str(params.get('api_key', '')).strip()
    if api_key:
        os.environ['GEMINI_API_KEY'] = api_key

    argv = [inp]
    argv += ['--target', str(params.get('target', 'tr'))]
    argv += ['--helper', str(params.get('helper', 'en'))]
    extra = str(params.get('extra', '')).strip()
    if extra and extra != 'none':
        argv += ['--extra', extra]
    argv += ['--level', str(params.get('level', 'A1'))]
    argv += ['--minutes', str(params.get('minutes', 10))]
    if params.get('sentences'):
        argv += ['--sentences', str(int(params['sentences']))]
    if params.get('vocab'):
        argv += ['--vocab', str(int(params['vocab']))]
    cfg = load_cfg()
    known_path = get_known_path(cfg)
    publish_dir = get_publish_dir(cfg)
    if params.get('voice_target') in ('m', 'f'):
        argv += ['--voice-target', params['voice_target']]
    if params.get('voice_helper') in ('m', 'f'):
        argv += ['--voice-helper', params['voice_helper']]
    if params.get('use_known', True) and known_path and os.path.exists(known_path):
        argv += ['--known', known_path]
    if params.get('name') or slug:
        argv += ['--name', S.safe_filename(params.get('name') or slug)]
    if params.get('publish') and publish_dir:
        argv += ['--publish', publish_dir]
    if params.get('no_fix'):
        argv.append('--no-fix')
    if params.get('no_review'):
        argv.append('--no-review')
    argv += ['--steps', steps]

    step_list = hoerbuch.STEPS if steps == 'all' else tuple(s.strip() for s in steps.split(','))
    JOB.reset(params, len(step_list))

    def worker():
        orig_log = hoerbuch.log
        hoerbuch.log = JOB.log
        try:
            JOB.log(f'Starte: python hoerbuch.py {" ".join(argv[:6])} …')
            hoerbuch.main(argv)
        except SystemExit as e:
            if e.code not in (0, None):
                JOB.error = str(e)
                JOB.log(f'Abbruch: {e}')
        except Exception as e:  # noqa: BLE001
            JOB.error = str(e)
            JOB.log(f'Fehler: {e}')
            traceback.print_exc()
        finally:
            hoerbuch.log = orig_log
            with JOB.lock:
                JOB.running = False
                JOB.finished_at = time.time()

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    return JOB.snapshot()


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # Konsole sauber halten

    def _send_json(self, obj, status=200):
        data = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def _send_file(self, path, download_name=None):
        if not os.path.isfile(path):
            self.send_error(404, 'Datei nicht gefunden')
            return
        ctype, _ = mimetypes.guess_type(path)
        if path.endswith('.apkg'):
            ctype = 'application/octet-stream'
        elif path.endswith('.mp3'):
            ctype = 'audio/mpeg'
        elif path.endswith('.html'):
            ctype = 'text/html; charset=utf-8'
        size = os.path.getsize(path)
        range_header = self.headers.get('Range')
        if range_header and path.endswith('.mp3'):
            m = re.match(r'bytes=(\d+)-(\d*)', range_header)
            if m:
                start = int(m.group(1))
                end = int(m.group(2)) if m.group(2) else size - 1
                end = min(end, size - 1)
                if start <= end:
                    length = end - start + 1
                    self.send_response(206)
                    self.send_header('Content-Type', ctype or 'application/octet-stream')
                    self.send_header('Accept-Ranges', 'bytes')
                    self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
                    self.send_header('Content-Length', str(length))
                    self.end_headers()
                    with open(path, 'rb') as f:
                        f.seek(start)
                        self.wfile.write(f.read(length))
                    return
        self.send_response(200)
        self.send_header('Content-Type', ctype or 'application/octet-stream')
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Content-Length', str(size))
        if download_name:
            safe_dl = download_name.encode('ascii', 'ignore').decode() or 'download'
            self.send_header('Content-Disposition', f'attachment; filename="{safe_dl}"')
        self.end_headers()
        with open(path, 'rb') as f:
            shutil.copyfileobj(f, self.wfile)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)
        qs = urllib.parse.parse_qs(parsed.query)

        if path in ('/', '/index.html'):
            return self._send_file(os.path.join(ROOT, 'hb', 'web_ui.html'))
        if path == '/api/health':
            ff_ok = False
            try:
                ff_ok = bool(audio.ffmpeg_path())
            except SystemExit:
                ff_ok = False
            return self._send_json({
                'status': 'ok',
                'running': JOB.running,
                'has_api_key': has_api_key(),
                'ffmpeg': ff_ok,
            })
        if path == '/api/meta':
            return self._send_json(api_meta())
        if path == '/api/plan':
            return self._send_json(api_plan(
                minutes=qs.get('minutes', ['10'])[0],
                level=qs.get('level', ['A1'])[0],
                vocab=qs.get('vocab', [None])[0],
                sentences=qs.get('sentences', [None])[0],
            ))
        if path == '/api/books':
            return self._send_json(api_list_books())
        if path.startswith('/api/book/'):
            slug = path.split('/api/book/', 1)[1].strip('/')
            data = api_get_book(slug)
            if not data:
                return self._send_json({'error': 'Nicht gefunden'}, 404)
            return self._send_json(data)
        if path == '/api/job/status':
            return self._send_json(JOB.snapshot())
        if path.startswith('/out/'):
            rel = os.path.normpath(path[len('/out/'):])
            if rel.startswith('..') or ':' in rel:
                self.send_error(403)
                return
            full = os.path.join(OUT_DIR, rel)
            dl = os.path.basename(full) if full.endswith('.apkg') or 'download' in qs else None
            return self._send_file(full, download_name=dl)
        self.send_error(404)

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = urllib.parse.unquote(parsed.path)
        length = int(self.headers.get('Content-Length', '0'))
        body = json.loads(self.rfile.read(length).decode('utf-8')) if length > 0 else {}

        try:
            if path == '/api/job/start':
                return self._send_json(start_job(body))
            if path.startswith('/api/book/') and path.endswith('/script'):
                slug = path[len('/api/book/'):-len('/script')].strip('/')
                return self._send_json(api_save_script(slug, body.get('script', body)))
            if path.startswith('/api/book/') and path.endswith('/publish'):
                slug = path[len('/api/book/'):-len('/publish')].strip('/')
                return self._send_json(api_publish_book(slug, body.get('dest')))
            if path.startswith('/api/book/') and path.endswith('/open_folder'):
                slug = S.safe_filename(path[len('/api/book/'):-len('/open_folder')].strip('/'))
                folder = os.path.join(OUT_DIR, slug)
                opened = False
                if os.path.isdir(folder):
                    if os.name == 'nt':
                        subprocess.Popen(['explorer.exe', folder])
                        opened = True
                    elif sys.platform == 'darwin':
                        subprocess.Popen(['open', folder])
                        opened = True
                    elif os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY'):
                        subprocess.Popen(['xdg-open', folder])
                        opened = True
                return self._send_json({'ok': opened, 'folder': os.path.abspath(folder)})
        except Exception as e:  # noqa: BLE001
            return self._send_json({'error': str(e)}, 400)
        self.send_error(404)


def main(argv=None):
    llm.load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--host', default=os.environ.get('HOERBUCH_HOST', '127.0.0.1'))
    ap.add_argument('--port', type=int, default=int(os.environ.get('HOERBUCH_PORT', '7865')))
    ap.add_argument('--no-browser', action='store_true')
    a = ap.parse_args(argv)

    os.makedirs(OUT_DIR, exist_ok=True)
    srv = http.server.ThreadingHTTPServer((a.host, a.port), Handler)
    browser_host = '127.0.0.1' if a.host in ('0.0.0.0', '::') else a.host
    url = f'http://{browser_host}:{a.port}'
    print(f'Hörbuch-Generator Studio (Stufe 2) läuft auf http://{a.host}:{a.port} ({url})', flush=True)
    print('Beenden mit Strg+C.', flush=True)
    if not a.no_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print('\nServer beendet.')
        srv.server_close()


if __name__ == '__main__':
    main()
