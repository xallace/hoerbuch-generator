"""Quelle holen: YouTube-Link (Transkript + Titel), andere URL (Seitentext), Textdatei oder Text direkt.

YouTube: youtube-transcript-api 1.2.x (Instanz, .list()/.fetch(); get_transcript gibt es nicht mehr). Fällt das
aus, holt yt-dlp (als Modul, nicht als .exe) die automatischen Untertitel. Es wird der ganze Text übergeben,
nichts abgeschnitten. Titel und Kanal über YouTubes oEmbed-Dienst.
"""
import html
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request

YT_ID = re.compile(r"(?:v=|/shorts/|/live/|youtu\.be/|/embed/)([A-Za-z0-9_-]{11})")


def youtube_id(url):
    m = YT_ID.search(url)
    return m.group(1) if m else None


def _get(url, timeout=30):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode('utf-8', 'replace')


def youtube_meta(vid):
    try:
        d = json.loads(_get('https://www.youtube.com/oembed?format=json&url=' +
                            urllib.parse.quote(f'https://www.youtube.com/watch?v={vid}', safe='')))
        return {'title': html.unescape(d.get('title', '')), 'author': html.unescape(d.get('author_name', ''))}
    except Exception:
        return {'title': '', 'author': ''}


def _transcript_api(vid, prefer):
    from youtube_transcript_api import YouTubeTranscriptApi
    api = YouTubeTranscriptApi()
    listing = api.list(vid)
    manual = [t for t in listing if not t.is_generated]
    auto = [t for t in listing if t.is_generated]

    def pick(cands):
        for code in prefer:
            for t in cands:
                if t.language_code.split('-')[0] == code:
                    return t
        return cands[0] if cands else None

    chosen = pick(manual) or pick(auto)
    if chosen is None:
        raise RuntimeError('kein Transkript vorhanden')
    fetched = chosen.fetch()
    text = ' '.join(s.text.replace('\n', ' ') for s in fetched)
    return text, {'lang': chosen.language_code, 'generated': chosen.is_generated,
                  'seconds': round(fetched[-1].start + fetched[-1].duration) if len(fetched) else None,
                  'segments': len(fetched), 'via': 'youtube-transcript-api'}


def _transcript_ytdlp(vid, prefer):
    with tempfile.TemporaryDirectory() as d:
        langs = ','.join(dict.fromkeys(prefer + ['en']))
        cmd = [sys.executable, '-I', '-m', 'yt_dlp', '--skip-download', '--write-auto-subs', '--write-subs',
               '--sub-langs', langs, '--sub-format', 'json3', '-o', os.path.join(d, 'v'),
               f'https://www.youtube.com/watch?v={vid}']
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=300)
        files = sorted(f for f in os.listdir(d) if f.endswith('.json3'))
        if not files:
            raise RuntimeError('yt-dlp lieferte keine Untertitel')
        for code in prefer:
            hit = [f for f in files if f'.{code}.' in f or f'.{code}-' in f]
            if hit:
                files = hit
                break
        with open(os.path.join(d, files[0]), encoding='utf-8') as f:
            j = json.load(f)
        parts = []
        last_end = 0
        for ev in j.get('events', []):
            segs = ev.get('segs') or []
            t = ''.join(s.get('utf8', '') for s in segs).replace('\n', ' ').strip()
            if t:
                parts.append(t)
            last_end = max(last_end, ev.get('tStartMs', 0) + ev.get('dDurationMs', 0))
        return ' '.join(parts), {'lang': files[0].split('.')[-2], 'generated': True,
                                 'seconds': round(last_end / 1000), 'segments': len(parts), 'via': 'yt-dlp'}


def _html_text(url):
    page = _get(url)
    title = re.search(r'<title[^>]*>(.*?)</title>', page, re.I | re.S)
    page = re.sub(r'<(script|style|nav|footer|header|noscript)[^>]*>.*?</\1>', ' ', page, flags=re.I | re.S)
    page = re.sub(r'<br\s*/?>|</p>|</div>|</h\d>|</li>', '\n', page, flags=re.I)
    text = html.unescape(re.sub(r'<[^>]+>', ' ', page))
    text = re.sub(r'[ \t\xa0]+', ' ', text)
    text = re.sub(r'\n\s*\n+', '\n\n', text).strip()
    return text, html.unescape(title.group(1).strip()) if title else ''


def fetch(inp, prefer_langs=('en',), log=print):
    """Gibt {'text', 'title', 'author', 'url', 'kind', 'meta'} zurück."""
    inp = inp.strip()
    if re.match(r'^https?://', inp):
        vid = youtube_id(inp)
        if vid:
            meta = youtube_meta(vid)
            log(f'YouTube {vid}: {meta["title"]!r} ({meta["author"]})')
            try:
                text, info = _transcript_api(vid, list(prefer_langs))
            except Exception as e:
                log(f'  youtube-transcript-api: {e} – Ausweg yt-dlp')
                text, info = _transcript_ytdlp(vid, list(prefer_langs))
            log(f'  Transkript {info["lang"]}{" (automatisch)" if info["generated"] else ""}, '
                f'{info["seconds"]} s Video, {len(text)} Zeichen über {info["via"]}')
            return {'text': text, 'title': meta['title'] or vid, 'author': meta['author'],
                    'url': f'https://youtu.be/{vid}', 'kind': 'youtube', 'meta': info}
        text, title = _html_text(inp)
        log(f'Webseite: {title!r}, {len(text)} Zeichen (einfache Textextraktion)')
        return {'text': text, 'title': title or inp, 'author': urllib.parse.urlparse(inp).netloc,
                'url': inp, 'kind': 'web', 'meta': {}}
    if os.path.isfile(inp):
        with open(inp, encoding='utf-8-sig') as f:
            text = f.read()
        title = os.path.splitext(os.path.basename(inp))[0]
        m = re.match(r'^#\s+(.+)', text)
        if m:
            title = m.group(1).strip()
        log(f'Datei {inp}: {len(text)} Zeichen')
        return {'text': text, 'title': title, 'author': '', 'url': '', 'kind': 'file', 'meta': {}}
    log(f'Direkter Text, {len(inp)} Zeichen')
    return {'text': inp, 'title': inp[:60].splitlines()[0], 'author': '', 'url': '', 'kind': 'text', 'meta': {}}
