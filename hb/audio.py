"""Audio: Segmentplan (4 Phasen mit Pausen), Sprachclips mit edge-tts, Zusammenbau über WAV, MP3 mit ffmpeg,
ID3-Tags und Cover.

Phasen wie in den handgebauten Hörbüchern: 1 Titel (Hilfssprache) · 2 Vokabel-Sandwich Ziel → Hilfe → Ziel ·
3 Geschichte Satz für Satz: Ziel → Denkpause → Hilfe → Festigungspause · 4 Immersion: alles in der Zielsprache
mit Atempausen. Zielsprache mit 80 % Tempo (config target_rate), Hilfssprache normal.

Clips werden nach (Text, Stimme, Tempo) benannt und wiederverwendet; jeder Clip wird einmal nach WAV dekodiert
(ffmpeg aus imageio-ffmpeg oder aus dem PATH), die Pausen entstehen als Stille in Python, die Summe wird einmal
als MP3 kodiert. So stimmen die Zeiten exakt und es gibt keine Nahtstellen-Glitches.
"""
import asyncio
import hashlib
import io
import json
import os
import shutil
import struct
import subprocess
import wave

from . import languages as L

PHASES = ('title', 'vocab', 'story', 'immersion')


def ffmpeg_path():
    p = shutil.which('ffmpeg')
    if p:
        return p
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        raise SystemExit('ffmpeg fehlt: pip install imageio-ffmpeg (oder ffmpeg in den PATH)')


def clip_key(text, voice, rate):
    return hashlib.sha1(f'{voice}|{rate}|{text}'.encode('utf-8')).hexdigest()[:14]


def _say(text, voice, rate, role, ref=None):
    return {'kind': 'clip', 'text': text, 'voice': voice, 'rate': rate, 'role': role, 'ref': ref,
            'key': clip_key(text, voice, rate)}


def _pause(sec):
    return {'kind': 'pause', 'sec': float(sec)}


def plan_segments(script, cfg):
    """Liste von Segmenten; jedes trägt 'phase' für die Zeitleiste in der README."""
    T, H = L.lang(script['target']), L.lang(script['helper'])
    vt = L.voice(script['target'], cfg['voice_gender']['target'])
    vh = L.voice(script['helper'], cfg['voice_gender']['helper'])
    rt, rh = cfg['target_rate'], cfg['helper_rate']
    P = cfg['pauses']
    segs = []

    def add(seg, phase):
        seg['phase'] = phase
        segs.append(seg)

    level_word = {'A1': 'A1', 'A2': 'A2', 'B1': 'B1', 'B2': 'B2'}[script['level']]
    add(_say(f"{script['title_helper']}. {T['name_en']} {level_word}.", vh, rh, 'meta'), 'title')
    if script.get('title_target'):
        add(_pause(0.8), 'title')
        add(_say(script['title_target'], vt, rt, 'meta'), 'title')
    add(_pause(P['after_title']), 'title')

    for v in script['vocab']:
        add(_say(v['target'], vt, rt, 'word', v['n']), 'vocab')
        add(_pause(P['vocab_inner']), 'vocab')
        add(_say(v['helper'], vh, rh, 'helper_word', v['n']), 'vocab')
        add(_pause(P['vocab_inner']), 'vocab')
        add(_say(v['target'], vt, rt, 'word', v['n']), 'vocab')
        add(_pause(P['vocab_between']), 'vocab')
    add(_pause(P['phase']), 'vocab')

    many = len(script['chapters']) > 1
    for i, ch in enumerate(script['chapters'], 1):
        if many:
            add(_say(f"{T['chapter']} {i}. {ch['title_target']}", vt, rt, 'chapter', i), 'story')
            add(_pause(0.6), 'story')
            add(_say(f"{H['chapter']} {i}. {ch['title_helper']}", vh, rh, 'chapter_helper', i), 'story')
            add(_pause(P['chapter'] * 0.6), 'story')
        for s in ch['sentences']:
            add(_say(s['target'], vt, rt, 'sentence', s['n']), 'story')
            add(_pause(P['think']), 'story')
            add(_say(s['helper'], vh, rh, 'helper_sentence', s['n']), 'story')
            add(_pause(P['consolidate']), 'story')
        if many:
            add(_pause(P['chapter']), 'story')
    add(_pause(P['phase']), 'story')

    add(_say(f"Now the whole story in {T['name_en']}.", vh, rh, 'meta'), 'immersion')
    add(_pause(P['chapter']), 'immersion')
    for i, ch in enumerate(script['chapters'], 1):
        if many:
            add(_say(f"{T['chapter']} {i}. {ch['title_target']}", vt, rt, 'chapter', i), 'immersion')
            add(_pause(P['breath']), 'immersion')
        for s in ch['sentences']:
            add(_say(s['target'], vt, rt, 'sentence', s['n']), 'immersion')
            add(_pause(P['breath']), 'immersion')
        if many:
            add(_pause(P['chapter']), 'immersion')
    return segs


def _mp3_seconds(path):
    try:
        from mutagen.mp3 import MP3
        return MP3(path).info.length
    except Exception:
        return 0.0


async def _record(seg, clipdir, sem, log):
    import edge_tts
    out = os.path.join(clipdir, seg['key'] + '.mp3')
    # Stummel-Erkennung (der Dienst liefert manchmal einen Bruchteil einer Sekunde): über die Dauer, nicht die
    # Dateigröße – Englisch in Normaltempo braucht nur etwa 0,06 s je Zeichen, Türkisch mit -20 % etwa 0,1 s
    least = max(0.3, 0.03 * len(seg['text']))
    if os.path.exists(out) and _mp3_seconds(out) >= least:
        return True
    for attempt in range(1, 6):
        async with sem:
            try:
                await edge_tts.Communicate(seg['text'], voice=seg['voice'], rate=seg['rate']).save(out + '.tmp')
                got = _mp3_seconds(out + '.tmp')
                if got >= least:
                    os.replace(out + '.tmp', out)
                    return True
                log(f'  Stummel ({got:.2f} s) für {seg["text"][:40]!r}, Versuch {attempt}')
            except Exception as e:
                log(f'  Versuch {attempt} fehlgeschlagen für {seg["text"][:40]!r}: {e}')
        await asyncio.sleep(attempt * 2)
    if os.path.exists(out + '.tmp'):
        os.remove(out + '.tmp')
    return False


async def _record_all(clips, clipdir, concurrency, log):
    sem = asyncio.Semaphore(concurrency)
    done = 0
    results = []
    tasks = [asyncio.ensure_future(_record(c, clipdir, sem, log)) for c in clips]
    for t in asyncio.as_completed(tasks):
        results.append(await t)
        done += 1
        if done % 25 == 0 or done == len(tasks):
            log(f'  {done}/{len(tasks)} Clips')
    return all(results)


def synthesize(segments, clipdir, cfg, log=print):
    os.makedirs(clipdir, exist_ok=True)
    uniq = {s['key']: s for s in segments if s['kind'] == 'clip'}
    todo = [s for s in uniq.values()]
    log(f'Sprachclips: {len(uniq)} verschiedene ({sum(1 for s in segments if s["kind"] == "clip")} Vorkommen)')
    ok = asyncio.run(_record_all(todo, clipdir, cfg.get('tts_concurrency', 4), log))
    if not ok:
        raise SystemExit('Nicht alle Clips konnten aufgenommen werden (Netz? edge-tts?).')


def _to_wav(ff, mp3, wav, rate):
    if os.path.exists(wav) and os.path.getsize(wav) > 44:
        return
    subprocess.run([ff, '-v', 'error', '-y', '-i', mp3, '-ar', str(rate), '-ac', '1', '-sample_fmt', 's16', wav],
                   check=True, capture_output=True)


def _wav_frames(path):
    with wave.open(path, 'rb') as w:
        return w.readframes(w.getnframes()), w.getframerate()


def assemble(segments, clipdir, out_mp3, cfg, log=print):
    """Baut die MP3 und gibt die Zeitleiste zurück: je Segment Startzeit und Dauer, dazu Phasen-Startzeiten."""
    ff = ffmpeg_path()
    rate = 24000  # edge-tts liefert 24 kHz mono
    cache = {}
    for s in segments:
        if s['kind'] == 'clip' and s['key'] not in cache:
            mp3 = os.path.join(clipdir, s['key'] + '.mp3')
            wav = os.path.join(clipdir, s['key'] + '.wav')
            _to_wav(ff, mp3, wav, rate)
            cache[s['key']] = _wav_frames(wav)[0]
    big = io.BytesIO()
    t = 0.0
    phase_start = {}
    for s in segments:
        phase_start.setdefault(s['phase'], t)
        if s['kind'] == 'pause':
            n = int(round(s['sec'] * rate))
            big.write(b'\x00\x00' * n)
            s['start'], s['dur'] = t, n / rate
        else:
            frames = cache[s['key']]
            big.write(frames)
            s['start'], s['dur'] = t, len(frames) / 2 / rate
        t += s['dur']
    wav_path = out_mp3 + '.wav'
    with wave.open(wav_path, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(big.getvalue())
    subprocess.run([ff, '-v', 'error', '-y', '-i', wav_path, '-ar', str(cfg.get('sample_rate', 48000)), '-ac', '1',
                    '-codec:a', 'libmp3lame', '-b:a', cfg.get('bitrate', '128k'), '-id3v2_version', '3', out_mp3],
                   check=True, capture_output=True)
    os.remove(wav_path)
    log(f'MP3: {out_mp3} ({fmt(t)} min, {os.path.getsize(out_mp3) / 1e6:.1f} MB)')
    return {'total': t, 'phase_start': phase_start}


def _wrap(draw, text, font, width):
    words, lines, cur = text.split(), [], ''
    for w in words:
        trial = (cur + ' ' + w).strip()
        if draw.textlength(trial, font=font) <= width:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def make_cover(script, path, track, log=print):
    """1000×1000-Cover: YouTube-Vorschaubild abgedunkelt als Hintergrund (falls erreichbar), sonst Farbverlauf."""
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
    import urllib.request
    T = L.lang(script['target'])
    size = 1000
    img = None
    url = (script.get('source') or {}).get('url', '') or ''
    vid = url.rsplit('/', 1)[-1] if 'youtu' in url else None
    if vid:
        for name in ('maxresdefault', 'hqdefault'):
            try:
                req = urllib.request.Request(f'https://img.youtube.com/vi/{vid}/{name}.jpg',
                                             headers={'User-Agent': 'Mozilla/5.0'})
                data = urllib.request.urlopen(req, timeout=20).read()
                if len(data) > 5000:
                    im = Image.open(io.BytesIO(data)).convert('RGB')
                    w, h = im.size
                    side = min(w, h)
                    im = im.crop(((w - side) // 2, (h - side) // 2, (w + side) // 2, (h + side) // 2)).resize((size, size))
                    im = im.filter(ImageFilter.GaussianBlur(6))
                    img = Image.blend(im, Image.new('RGB', (size, size), (12, 16, 32)), 0.55)
                    break
            except Exception:
                continue
    if img is None:
        h = int(hashlib.sha1(script['short_title'].encode()).hexdigest()[:6], 16)
        c1 = ((h >> 16) & 0x7f, (h >> 8) & 0x7f, h & 0x7f)
        img = Image.new('RGB', (size, size))
        px = img.load()
        for y in range(size):
            f = y / size
            col = tuple(int(c1[i] * (1 - f) + 20 * f) for i in range(3))
            for x in range(size):
                px[x, y] = col
    draw = ImageDraw.Draw(img)

    def font(sz, bold=True):
        windir = os.environ.get('WINDIR', r'C:\Windows')
        candidates = [
            os.path.join(windir, 'Fonts', 'segoeuib.ttf' if bold else 'segoeui.ttf'),
            os.path.join(windir, 'Fonts', 'arialbd.ttf' if bold else 'arial.ttf'),
            '/System/Library/Fonts/Supplemental/Arial Bold.ttf' if bold else '/System/Library/Fonts/Supplemental/Arial.ttf',
            '/System/Library/Fonts/Helvetica.ttc',
            '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf' if bold else '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
            '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf' if bold else '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf',
            '/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf' if bold else '/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf',
        ]
        for p in candidates:
            if os.path.exists(p):
                return ImageFont.truetype(p, sz)
        try:
            return ImageFont.load_default(size=sz)
        except TypeError:
            return ImageFont.load_default()

    draw.rounded_rectangle((60, 60, 300, 130), radius=35, fill=(79, 70, 229))
    draw.text((180, 95), f'{T["name_native"]} {script["level"]}', font=font(36), fill='white', anchor='mm')
    draw.text((940, 95), f'{track:02d}', font=font(48), fill=(200, 200, 220), anchor='rm')
    lines = _wrap(draw, script['title_helper'], font(72), 880)[:5]
    y = 300
    for ln in lines:
        draw.text((60, y), ln, font=font(72), fill='white')
        y += 86
    if script.get('title_target'):
        for ln in _wrap(draw, script['title_target'], font(44, False), 880)[:3]:
            draw.text((60, y + 20), ln, font=font(44, False), fill=(220, 220, 235))
            y += 56
    author = (script.get('source') or {}).get('author') or ''
    draw.text((60, 900), author[:60], font=font(34, False), fill=(190, 190, 210))
    draw.text((940, 900), 'Audiobook Studio', font=font(34, False), fill=(190, 190, 210), anchor='ra')
    img.save(path, 'JPEG', quality=88)
    return path


def tag(mp3, script, cfg, track, total, cover_path, comment=''):
    from mutagen.id3 import ID3, TIT2, TPE1, TALB, TPE2, TRCK, TCON, COMM, APIC, TPOS, TDRC, ID3NoHeaderError
    T, H = L.lang(script['target']), L.lang(script['helper'])
    vt = L.voice(script['target'], cfg['voice_gender']['target']).split('-')[2].replace('Neural', '')
    vh = L.voice(script['helper'], cfg['voice_gender']['helper']).split('-')[2].replace('Neural', '')
    try:
        tags = ID3(mp3)
    except ID3NoHeaderError:
        tags = ID3()
    tags.delete(mp3)
    tags = ID3()
    tags.add(TIT2(encoding=3, text=f'{track:02d} – {script["short_title"]} ({T["name_en"]} {script["level"]})'))
    tags.add(TPE1(encoding=3, text=f'{vt} ({script["target"].upper()}) / {vh} ({script["helper"].upper()})'))
    tags.add(TALB(encoding=3, text=cfg['album'].format(target_de=T['name_de'], target_en=T['name_en'], level=script['level'])))
    tags.add(TPE2(encoding=3, text=cfg.get('album_artist', 'YouTube Audiobooks')))
    tags.add(TRCK(encoding=3, text=f'{track}/{total}'))
    tags.add(TPOS(encoding=3, text='1/1'))
    tags.add(TCON(encoding=3, text='Audiobook'))
    import datetime
    tags.add(TDRC(encoding=3, text=str(datetime.date.today().year)))
    tags.add(COMM(encoding=3, lang='eng', desc='Info', text=comment))
    if cover_path and os.path.exists(cover_path):
        with open(cover_path, 'rb') as f:
            tags.add(APIC(encoding=3, mime='image/jpeg', type=3, desc='Cover', data=f.read()))
    tags.save(mp3, v2_version=3)


def next_track(publish_dir, script, cfg, base_stem, local_mp3=None):
    """Ermittelt (track, total) anhand der vorhandenen MP3-Tags im Zielordner (oder der lokalen MP3).
    Zählt nur MP3s desselben Albums (z. B. Türkisch A1) und behält bei erneuter Vertonung die bisherige Tracknummer."""
    from mutagen.id3 import ID3, ID3NoHeaderError
    T = L.lang(script['target'])
    expected_album = cfg['album'].format(target_de=T['name_de'], target_en=T['name_en'], level=script['level'])

    def _read_trck(p):
        try:
            t = ID3(p)
            alb = str(t.get('TALB', '')).strip()
            trck = str(t.get('TRCK', '')).strip()
            parts = trck.split('/')
            num = int(parts[0]) if parts and parts[0].isdigit() else None
            tot = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else None
            return alb, num, tot
        except Exception:
            return '', None, None

    if publish_dir and os.path.isdir(publish_dir):
        own_num = None
        other_nums = []
        other_count = 0
        for f in os.listdir(publish_dir):
            if not f.lower().endswith('.mp3'):
                continue
            p = os.path.join(publish_dir, f)
            alb, num, _ = _read_trck(p)
            if alb and alb != expected_album:
                continue
            if f.startswith(base_stem) or f.endswith('_' + base_stem + '.mp3'):
                own_num = num
            else:
                other_count += 1
                if num:
                    other_nums.append(num)
        if own_num:
            total = max([own_num] + other_nums)
            return own_num, total
        track = (max(other_nums) if other_nums else other_count) + 1
        return track, max([track] + other_nums)

    if local_mp3 and os.path.exists(local_mp3):
        _, num, tot = _read_trck(local_mp3)
        if num:
            return num, (tot or num)
    return 1, 1


def sync_album_total(publish_dir, script, cfg, total):
    """Aktualisiert die Gesamt-Trackzahl (TRCK = i/total) aller MP3s desselben Albums im Zielordner."""
    from mutagen.id3 import ID3, TRCK
    if not publish_dir or not os.path.isdir(publish_dir):
        return
    T = L.lang(script['target'])
    expected_album = cfg['album'].format(target_de=T['name_de'], target_en=T['name_en'], level=script['level'])
    for f in os.listdir(publish_dir):
        if not f.lower().endswith('.mp3'):
            continue
        p = os.path.join(publish_dir, f)
        try:
            t = ID3(p)
            if str(t.get('TALB', '')).strip() != expected_album:
                continue
            trck = str(t.get('TRCK', '')).strip()
            num = trck.split('/')[0]
            if num.isdigit() and trck != f'{int(num)}/{total}':
                t.delall('TRCK')
                t.add(TRCK(encoding=3, text=f'{int(num)}/{total}'))
                t.save(p, v2_version=3)
        except Exception:
            continue



def timeline(segments, total):
    names = {'title': 'Titel', 'vocab': 'Vokabel-Sandwich', 'story': 'Zweisprachige Geschichte', 'immersion': 'Immersion'}
    out = []
    for ph in PHASES:
        segs = [s for s in segments if s['phase'] == ph]
        if not segs:
            continue
        start = segs[0]['start']
        end = segs[-1]['start'] + segs[-1]['dur']
        out.append({'phase': ph, 'name': names[ph], 'start': start, 'end': end})
    return out


def fmt(sec):
    sec = int(round(sec))
    return f'{sec // 60:02d}:{sec % 60:02d}'
