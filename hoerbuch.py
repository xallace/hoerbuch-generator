"""Hörbuch-Generator: YouTube-Link, Webseite, Textdatei oder Text → Lernhörbuch (MP3) + Anki-Deck (.apkg) + README.

Beispiele (aus diesem Ordner, Python 3.12 mit -I):
  python -I hoerbuch.py https://youtu.be/xo-tYjGDtqw --target tr --helper en --level A1 --minutes 5 --known known_words.apkg
  python -I hoerbuch.py text.md --target de --helper uk --level A1 --minutes 10 --track 3 --total 3
  python -I hoerbuch.py <url> --steps script,check          # nur Fassung schreiben und prüfen
  python -I hoerbuch.py <url> --steps audio,anki,readme     # vorhandene script.json vertonen

Ablage: out/<slug>/ mit source.json, script.json, check.md, clips/, <slug>.mp3, <slug>.apkg,
README_AND_TRANSCRIPT_<slug>.md. Jede Stufe setzt auf den Dateien der vorigen auf und lässt sich einzeln
wiederholen. Mit --publish DIR werden MP3, apkg und README zusätzlich dorthin kopiert.
Voraussetzungen: GEMINI_API_KEY (.env, Umgebungsvariable oder gemini_key.txt), Internet (edge-tts, YouTube).
"""
import argparse
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hb import ROOT, anki, audio, check, known as known_mod, languages as L, llm, load_config, readme, script as S, source  # noqa: E402

STEPS = ('source', 'script', 'check', 'audio', 'anki', 'readme')


def log(msg):
    print(msg, flush=True)


def load_cfg(path):
    return load_config(path)


def main(argv=None):
    llm.load_dotenv()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('input', help='YouTube-URL, andere URL, Pfad zu einer Textdatei oder der Text selbst')
    ap.add_argument('--target', default='tr', help='Zielsprache (tr, de, ru, uk, en, fr, es)')
    ap.add_argument('--helper', default='en', help='Hilfssprache für Übersetzung und Ansagen')
    ap.add_argument('--extra', default=None, help='optionale Zweitübersetzung der Vokabeln (z. B. de)')
    ap.add_argument('--level', default='A1', choices=L.LEVELS)
    ap.add_argument('--minutes', type=float, default=10, help='Zieldauer der MP3 (Richtwert)')
    ap.add_argument('--sentences', type=int, help='Satzzahl erzwingen (statt aus --minutes)')
    ap.add_argument('--vocab', type=int, help='Zahl der Sandwich-Vokabeln erzwingen')
    ap.add_argument('--known', help='.apkg-Export oder Wortliste: bekannte Wörter als Anker, nicht als Vokabeln')
    ap.add_argument('--track', type=int, help='Tracknummer im Album (Standard: Zahl der MP3s in --publish + 1, sonst 1)')
    ap.add_argument('--total', type=int, help='Trackzahl im Album (Standard: = --track)')
    ap.add_argument('--out', default=os.path.join(ROOT, 'out'), help='Ausgabeordner (Unterordner je Hörbuch)')
    ap.add_argument('--name', help='Ordner-/Dateiname statt des Titels')
    ap.add_argument('--publish', help='Ordner, in den MP3, apkg und README zusätzlich kopiert werden')
    ap.add_argument('--steps', default='all', help='Komma-Liste aus ' + ','.join(STEPS) + ' oder all')
    ap.add_argument('--no-fix', action='store_true', help='Korrekturen des Prüfdurchlaufs nur melden, nicht übernehmen')
    ap.add_argument('--no-review', action='store_true', help='Prüfung ohne zweiten Modell-Durchlauf')
    ap.add_argument('--model', help='Gemini-Modell (Standard aus config.json)')
    ap.add_argument('--voice-target', choices=('m', 'f'), help='Stimme der Zielsprache')
    ap.add_argument('--voice-helper', choices=('m', 'f'), help='Stimme der Hilfssprache')
    ap.add_argument('--config', default=os.path.join(ROOT, 'config.json'))
    a = ap.parse_args(argv)

    cfg = load_cfg(a.config)
    if a.model:
        cfg['model'] = a.model
    if a.voice_target:
        cfg['voice_gender']['target'] = a.voice_target
    if a.voice_helper:
        cfg['voice_gender']['helper'] = a.voice_helper
    L.lang(a.target), L.lang(a.helper)
    if a.extra:
        L.lang(a.extra)
    steps = STEPS if a.steps == 'all' else tuple(s.strip() for s in a.steps.split(','))
    for s in steps:
        if s not in STEPS:
            raise SystemExit(f'Unbekannte Stufe {s!r}')

    known = None
    if a.known:
        entries = known_mod.load(a.known)
        known = known_mod.known_words(entries)
        log(f'Bekannte Wörter: {len(known)} von {len(entries)} Einträgen aus {a.known}')

    # --- source -------------------------------------------------------------------------------------------------
    src_cache = None
    if a.name:
        folder = os.path.join(a.out, S.safe_filename(a.name))
        os.makedirs(folder, exist_ok=True)
        src_path = os.path.join(folder, 'source.json')
        if 'source' in steps or not os.path.exists(src_path):
            src_cache = source.fetch(a.input, prefer_langs=(a.helper, 'en', a.target), log=log)
            with open(src_path, 'w', encoding='utf-8') as f:
                json.dump(src_cache, f, ensure_ascii=False, indent=1)
    else:
        src_cache = source.fetch(a.input, prefer_langs=(a.helper, 'en', a.target), log=log)
        folder = os.path.join(a.out, S.safe_filename(S.slugify(src_cache['title'])))
        os.makedirs(folder, exist_ok=True)
        src_path = os.path.join(folder, 'source.json')
        with open(src_path, 'w', encoding='utf-8') as f:
            json.dump(src_cache, f, ensure_ascii=False, indent=1)
    with open(src_path, encoding='utf-8') as f:
        src = json.load(f)
    slug = os.path.basename(folder)
    log(f'Ordner: {folder}')

    script_path = os.path.join(folder, 'script.json')

    def save_script(sc):
        with open(script_path, 'w', encoding='utf-8') as f:
            json.dump(sc, f, ensure_ascii=False, indent=1)

    # --- script -------------------------------------------------------------------------------------------------
    if 'script' in steps:
        p = S.plan(a.minutes, a.level, cfg.get('chapter_size', 15), vocab=a.vocab, sentences=a.sentences)
        sc = S.write(src, a.target, a.helper, a.extra, a.level, p, cfg, known=known, log=log)
        save_script(sc)
        log(f'Fassung gespeichert: {script_path}')
    if not os.path.exists(script_path):
        raise SystemExit(f'{script_path} fehlt – Stufe script zuerst laufen lassen.')
    with open(script_path, encoding='utf-8') as f:
        sc = json.load(f)

    # --- check --------------------------------------------------------------------------------------------------
    check_path = os.path.join(folder, 'check.md')
    if 'check' in steps:
        findings, review, applied, skipped = check.run(sc, cfg, known=known, fix=not a.no_fix,
                                                       use_llm=not a.no_review, log=log)
        save_script(sc)
        md = check.report_md(sc, findings, review, applied, skipped)
        with open(check_path, 'w', encoding='utf-8') as f:
            f.write(md)
        with open(os.path.join(folder, 'check.json'), 'w', encoding='utf-8') as f:
            json.dump({'findings': findings, 'review': review, 'applied': applied}, f, ensure_ascii=False, indent=1)
        errors = [x for x in findings if x[0] == 'error']
        if errors:
            log('Fehler nach der Prüfung (siehe check.md):')
            for _, where, msg in errors:
                log(f'  - {where}: {msg}')

    # --- audio --------------------------------------------------------------------------------------------------
    suffix = f'_{L.lang(a.target)["name_en"]}_{a.level}'
    base = S.safe_filename(a.name if (a.name and a.name.endswith(suffix)) else f'{slug}{suffix}')
    mp3_path = os.path.join(folder, base + '.mp3')
    apkg_path = os.path.join(folder, base + '.apkg')
    cover_path = os.path.join(folder, 'cover.jpg')
    seg_path = os.path.join(folder, 'segments.json')
    clipdir = os.path.join(folder, 'clips')
    track = a.track
    auto_track, auto_total = audio.next_track(a.publish, sc, cfg, base, local_mp3=mp3_path)
    if track is None:
        track = auto_track
    total = a.total or max(track, auto_total)

    segments = None
    if 'audio' in steps:
        segments = audio.plan_segments(sc, cfg)
        audio.synthesize(segments, clipdir, cfg, log=log)
        info = audio.assemble(segments, clipdir, mp3_path, cfg, log=log)
        audio.make_cover(sc, cover_path, track, log=log)
        comment = (f'{L.lang(a.target)["name_en"]} {a.level} audiobook from a YouTube source: '
                   f'{len(sc["vocab"])} sandwich words, {len(S.all_sentences(sc))} sentences, '
                   f'{len(sc["chapters"])} chapters; target voice at {cfg["target_rate"]}. Built with Hoerbuch-Generator.')
        audio.tag(mp3_path, sc, cfg, track, total, cover_path, comment)
        with open(seg_path, 'w', encoding='utf-8') as f:
            json.dump({'segments': segments, 'total': info['total']}, f, ensure_ascii=False)
    if segments is None and ('anki' in steps or 'readme' in steps):
        if not os.path.exists(seg_path):
            raise SystemExit('segments.json fehlt – Stufe audio zuerst laufen lassen.')
        with open(seg_path, encoding='utf-8') as f:
            segments = json.load(f)['segments']

    # --- anki ---------------------------------------------------------------------------------------------------
    deck_name = None
    if 'anki' in steps:
        deck_name = anki.build(sc, segments, clipdir, apkg_path, cfg, track, log=log)

    # --- readme -------------------------------------------------------------------------------------------------
    readme_path = os.path.join(folder, f'README_AND_TRANSCRIPT_{slug}.md')
    if 'readme' in steps:
        total_sec = segments[-1]['start'] + segments[-1]['dur']
        tl = audio.timeline(segments, total_sec)
        if deck_name is None:
            T = L.lang(a.target)
            deck_name = f"{cfg['deck_root'].format(target_de=T['name_de'], target_en=T['name_en'])}::" \
                        f"{track:02d} {sc['short_title']} ({a.level})"
        check_md = open(check_path, encoding='utf-8').read() if os.path.exists(check_path) else None
        files = [('MP3', os.path.basename(mp3_path)), ('Anki', os.path.basename(apkg_path)),
                 ('Fassung', 'script.json'), ('Prüfung', 'check.md')]
        with open(readme_path, 'w', encoding='utf-8') as f:
            f.write(readme.build(sc, segments, tl, deck_name, files, cfg, track, total, check_md))
        log(f'README: {readme_path}')

    if a.publish:
        os.makedirs(a.publish, exist_ok=True)
        for p in (mp3_path, apkg_path, readme_path):
            if os.path.exists(p):
                shutil.copy2(p, a.publish)
        audio.sync_album_total(a.publish, sc, cfg, total)
        log(f'Kopiert nach {a.publish}')
    log('Fertig.')


if __name__ == '__main__':
    main()
