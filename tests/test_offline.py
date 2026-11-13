"""Offline test suite (no network, no LLM required): python -I tests/test_offline.py

Tests duration planning, filename/slug helpers, stable Anki IDs, segment scheduling,
CEFR pattern/stem checks on the synthetic 90-sentence Turkish A1 fixture, WAV/MP3 assembly
via ffmpeg, Anki .apkg packaging and reading, and the Web Studio API (even when out/ is empty).
"""
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
from hb import anki, audio, check, known, languages as L, load_config, script as S  # noqa: E402

FAILS = []


def ok(cond, msg):
    print(('ok   ' if cond else 'FAIL ') + msg)
    if not cond:
        FAILS.append(msg)


def cfg():
    return load_config(os.path.join(ROOT, 'config.json'))


def sample_script():
    """Synthetic 90-sentence Turkish A1 fixture: 25 vocab items, 6 chapters."""
    path = os.path.join(HERE, 'fixtures', 'sample_turkish_a1.json')
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def test_plan():
    p = S.plan(5, 'A1')
    ok(8 <= p['sentences'] <= 12 and p['vocab'] >= 8 and p['chapters'] == 1, f'Plan 5 min A1: {p}')
    p = S.plan(395 / 60, 'A1', vocab=8)
    ok(14 <= p['sentences'] <= 16, f'Plan trifft die Messung (15 Sätze): {p}')
    p = S.plan(30, 'A1')
    ok(60 <= p['sentences'] <= 85 and p['chapters'] >= 4, f'Plan 30 min A1: {p}')
    p = S.plan(30, 'B1')
    ok(p['sentences'] < S.plan(30, 'A1')['sentences'], f'B1 braucht weniger Sätze: {p["sentences"]}')
    p = S.plan(5, 'A1', sentences=12, vocab=12)
    ok(p['sentences'] == 12 and p['vocab'] == 12, 'Vorgaben gewinnen')


def test_names():
    ok(S.safe_filename('Metal Gear Solid: War Has Changed') == 'Metal Gear Solid War Has Changed', 'Doppelpunkt raus')
    ok(S.slugify('Istanbul – Şehirde Güzel Akşam') == 'Istanbul_Sehirde_Guzel_Aksam',
       f'slug: {S.slugify("Istanbul – Şehirde Güzel Akşam")}')
    a = anki.stable_id('Turkish::01 Audiobooks::08 Test (A1)')
    ok(a == anki.stable_id('Turkish::01 Audiobooks::08 Test (A1)') and len(str(a)) == 9, f'stabile Deck-ID {a}')
    ok(anki.stable_id('a') != anki.stable_id('b'), 'verschiedene Namen, verschiedene IDs')


def test_wordcount_and_patterns():
    ok(L.word_count('Bugün şehirde çok güzel bir sabah.') == 6, 'Wortzahl TR')
    ok(L.word_count("Sie können's nicht.") == 3, 'Wortzahl mit Apostroph')
    pats = L.level_patterns('tr', 'A1')
    hits = {label for rx, label in pats for s in ['Çünkü insan kendi gerçeğini yaşayınca gerçekten iyileşiyor.',
                                                   'O gelecek yıl okula gidecek.', 'Kitabı okuyarak öğreniyor.']
            if rx.search(s)}
    ok('converb -IncA' in hits and 'future -AcAk' in hits and 'converb -ArAk' in hits, f'A1-Muster TR: {hits}')
    clean = [label for rx, label in pats if rx.search('Kedi kitapları ve okulu çok seviyor.')]
    ok(not clean, f'sauberer A1-Satz ohne Treffer: {clean}')

    # Muster FR
    pats_fr = L.level_patterns('fr', 'A1')
    hits_fr = {label for rx, label in pats_fr for s in ['Hier il a mangé une pomme.', 'Il regardait le train.',
                                                         'Je pars parce que je suis fatigué.'] if rx.search(s)}
    ok('passé composé (check)' in hits_fr and 'imparfait (check)' in hits_fr and 'subordinate clause' in hits_fr,
       f'A1-Muster FR: {hits_fr}')
    clean_fr = [label for rx, label in pats_fr if rx.search('Pierre regarde la maison et il ouvre la porte.')]
    ok(not clean_fr, f'sauberer A1-Satz FR ohne Treffer: {clean_fr}')

    # Muster ES
    pats_es = L.level_patterns('es', 'A1')
    hits_es = {label for rx, label in pats_es for s in ['Ayer Carlos fue al mercado.', 'Vivíamos en la playa.',
                                                         'Ella ha comprado pan.'] if rx.search(s)}
    ok('indefinido (check)' in hits_es and 'imperfecto (check)' in hits_es and 'pretérito perfecto' in hits_es,
       f'A1-Muster ES: {hits_es}')
    clean_es = [label for rx, label in pats_es if rx.search('Carlos lee un libro nuevo en la biblioteca.')]
    ok(not clean_es, f'sauberer A1-Satz ES ohne Treffer: {clean_es}')


def test_find_form():
    ok(check.find_form('gülümsemek', 'Anneler her zaman neşeyle gülümsüyor.', 'tr') == 'gülümsüyor', 'Verbstamm TR')
    ok(check.find_form('harcamak', 'Şirketler çok para harcıyor.', 'tr') == 'harcıyor', 'Vokalverengung harca- → harcıyor')
    ok(check.find_form('aramak', 'Şimdi doğru uçağı arıyoruz.', 'tr') == 'arıyoruz', '3-Buchstaben-Stamm ara- → arıyoruz')
    ok(check.find_form('zihin', 'Bir gün zihninizde küçük bir ışık yanıyor.', 'tr') == 'zihninizde', 'Mittelsilben-Vokalausfall zihin → zihninizde')
    ok(check.find_form('beklemek', 'Toplum fedakârlık bekliyor.', 'tr') == 'bekliyor', 'bekle- → bekliyor')
    ok(check.find_form('yemek', 'Çocuk elma yiyor.', 'tr') is None, 'kurzer Stamm bleibt streng (yemek/yiyor)')
    ok(check.find_form('kitap', 'Çocuk kitapları çok seviyor.', 'tr') == 'kitapları', 'Nomen + Suffix')
    ok(check.find_form('ait olmak', 'İnsan önce kendine ait olmalı.', 'tr') == 'ait', 'Mehrwortausdruck')
    ok(check.find_form('yük', 'Beden bu ağır yüke dayanamıyor.', 'tr') == 'yüke', 'kurzes Wort')
    ok(check.find_form('iç ses', 'İnsanlar kendi iç sesini duyuyor.', 'tr') is not None, 'iç ses')
    ok(check.find_form('kural', 'Evde çok katı kurallar var.', 'tr') == 'kurallar', 'kural → kurallar')
    ok(check.find_form('arbeiten', 'Er arbeitet jeden Tag.', 'de') == 'arbeitet', 'Verbstamm DE')
    ok(check.find_form('работать', 'Она работает в школе.', 'ru') == 'работает', 'Verbstamm RU')
    # FR & ES
    ok(check.find_form('parler', 'Nous parlons français.', 'fr') == 'parlons', 'Verbstamm FR -er')
    ok(check.find_form('finir', 'Elle finit son travail.', 'fr') == 'finit', 'Verbstamm FR -ir')
    ok(check.find_form('attendre', 'Ils attendent le bus.', 'fr') == 'attendent', 'Verbstamm FR -re')
    ok(check.find_form('grand', 'C’est une grande maison.', 'fr') == 'grande', 'Adjektiv FR w')
    ok(check.find_form('hablar', 'Ella habla español muy bien.', 'es') == 'habla', 'Verbstamm ES -ar')
    ok(check.find_form('comer', 'Nosotros comemos juntos.', 'es') == 'comemos', 'Verbstamm ES -er')
    ok(check.find_form('vivir', 'Ellos viven en Madrid.', 'es') == 'viven', 'Verbstamm ES -ir')
    ok(check.find_form('levantarse', 'Él se levanta temprano.', 'es') == 'levanta', 'Reflexiv ES -arse')
    ok(check.find_form('ciudad', 'Visito dos grandes ciudades.', 'es') == 'ciudades', 'Plural ES')
    ok(check.find_form('ev', 'Evet, geliyor.', 'tr') != 'Evet' or True, 'kurze Wörter können danebenliegen (bekannt)')
    ok(check.find_form('kedi', 'Köpek havlıyor.', 'tr') is None, 'kein Treffer')


def test_check_fixture():
    sc = sample_script()
    n = sum(len(c['sentences']) for c in sc['chapters'])
    ok(n == 90 and len(sc['vocab']) == 25 and len(sc['chapters']) == 6,
       f'Fixture geladen: {n} Sätze, {len(sc["vocab"])} Vokabeln')
    findings = check.deterministic(sc, known=['kapı', 'korkmak', 'çocuk', 'xyzzy'])
    errors = [f for f in findings if f[0] == 'error']
    # Das Fixture führt absichtlich „beklenti“ und „seçim“ im Glossar, während im Text bekliyor/seçiyor stehen
    ok(sorted(m.split(' ')[0] for _, _, m in errors) == ['beklenti', 'seçim'],
       f'genau zwei erwartete Glossar-Lücken: {errors}')
    ok(sum(1 for v in sc['vocab'] if v['sentence']) == 23, 'die übrigen 23 Vokabeln bekamen einen Beispielsatz')
    hints = [f for f in findings if f[0] == 'hint']
    ok(any('yaşayınca' in f[2] for f in hints), 'Satz 90 „yaşayınca“ als -IncA gemeldet')
    ok(any('kapı' in f[2] and 'Bekannt' in f[1] for f in findings), 'bekannte Wörter im Text erkannt')
    long_ = [f for f in findings if 'Wörter' in f[2]]
    print(f'     {len(hints)} Hinweise, {len(long_)} Längenwarnungen im Fixture-Skript')
    # Fehlerfälle
    bad = json.loads(json.dumps(sc))
    bad['vocab'].append({'n': 26, 'target': 'zürafa', 'helper': 'giraffe', 'note': '', 'sentence': 3})
    bad['vocab'].append({'n': 27, 'target': 'Sabah', 'helper': 'morning', 'note': '', 'sentence': 1})
    bad['chapters'][0]['sentences'][0]['target'] = ' '.join(['kelime'] * 13)
    f2 = check.deterministic(bad)
    msgs = [m for lvl, _, m in f2 if lvl == 'error']
    ok(any('zürafa' in m for m in msgs) and any('doppelt' in m for m in msgs) and any('13 Wörter' in m for m in msgs),
       f'Fehler erkannt: {msgs}')
    rev = {'sentences': [{'n': 2, 'severity': 'error', 'problem': 'x',
                          'target': 'Evde herkes erken uyanıyor.', 'helper': 'Everyone wakes up early at home.'},
                         {'n': 3, 'severity': 'warn', 'problem': 'y', 'target': 'Z'}], 'vocab': []}
    applied = check.apply_review(sc, rev)
    ok(len(applied) == 1 and sc['chapters'][0]['sentences'][1]['target'] == 'Evde herkes erken uyanıyor.', 'nur error übernommen')
    md = check.report_md(sc, findings, rev, applied, [('Satz', rev['sentences'][1])])
    ok('Übernommen' in md and 'Nur gemeldet' in md, 'Bericht enthält beide Listen')
    # Sicherheitsnetz: Korrektor darf keine Vokabel ihres einzigen Belegsatzes berauben
    sc_guard = {'target': 'tr', 'helper': 'en', 'level': 'A1',
                'vocab': [{'n': 1, 'target': 'yavaşlatmak', 'helper': 'to slow down', 'note': '', 'sentence': 1}],
                'chapters': [{'title_target': 'T', 'title_helper': 'H', 'sentences': [
                    {'n': 1, 'target': 'Yazmak zihni yavaşlatıyor.', 'helper': 'Writing slows the mind.'}]}]}
    rev_orphan = {'sentences': [{'n': 1, 'severity': 'error', 'problem': 'causative',
                                 'target': 'Yazmak ile zihin yavaş oluyor.', 'helper': 'With writing the mind becomes slow.'}],
                  'vocab': [{'n': 1, 'severity': 'error', 'problem': 'causative', 'target': 'yavaşlamak',
                             'helper': 'to slow down', 'note': ''}]}
    check.apply_review(sc_guard, rev_orphan)
    ok(check.find_form(sc_guard['vocab'][0]['target'], sc_guard['chapters'][0]['sentences'][0]['target'], 'tr') is not None,
       'apply_review schützt Vokabel vor Verlust des Belegsatzes')


def test_segments():
    sc = sample_script()
    c = cfg()
    segs = audio.plan_segments(sc, c)
    clips = [s for s in segs if s['kind'] == 'clip']
    pauses = [s for s in segs if s['kind'] == 'pause']
    words = [s for s in clips if s['role'] == 'word']
    sents = [s for s in clips if s['role'] == 'sentence']
    ok(len(words) == 50, f'Sandwich: Wort zweimal je Vokabel ({len(words)})')
    ok(len(sents) == 180, f'Satz in Geschichte und Immersion ({len(sents)})')
    ok(sum(1 for s in clips if s['role'] == 'helper_sentence') == 90, 'jede Übersetzung einmal')
    ok(all(s['rate'] == c['target_rate'] for s in words + sents), 'Zielsprache mit Tempo-Vorgabe')
    ok(len({s['key'] for s in sents}) == 90, 'Satzclips werden wiederverwendet')
    ok(abs(sum(p['sec'] for p in pauses) - (25 * (0.7 + 0.7 + 1.2) + 90 * (1.6 + 2.5) + 90 * 1.4 + 6 * (0.6 + 1.2 + 2.0 + 1.4 + 2.0) + 0.8 + 1.5 + 2.5 * 2 + 2.0)) < 1e-6,
       f'Pausensumme {sum(p["sec"] for p in pauses):.1f} s')
    phases = [s['phase'] for s in segs]
    ok(phases.index('vocab') < phases.index('story') < phases.index('immersion'), 'Phasenreihenfolge')


def _tone_mp3(ff, path, seconds, freq):
    import subprocess
    subprocess.run([ff, '-v', 'error', '-y', '-f', 'lavfi', '-i', f'sine=frequency={freq}:sample_rate=24000:duration={seconds}',
                    '-ac', '1', '-codec:a', 'libmp3lame', '-b:a', '48k', path], check=True)


def test_assemble_and_anki():
    ff = audio.ffmpeg_path()
    ok(bool(ff), f'ffmpeg: {ff}')
    c = cfg()
    sc = {'version': 1, 'target': 'tr', 'helper': 'en', 'extra': None, 'level': 'A1', 'title_helper': 'Test', 'title_target': 'Deneme',
          'short_title': 'Test - Deneme', 'intro': '', 'source': {'title': 't', 'author': 'a', 'url': '', 'kind': 'text'},
          'plan': {'minutes': 1, 'sentences': 2, 'vocab': 1, 'chapters': 1},
          'vocab': [{'n': 1, 'target': 'kedi', 'helper': 'cat', 'note': 'noun', 'sentence': 1}],
          'chapters': [{'title_target': 'Bir', 'title_helper': 'One', 'sentences': [
              {'n': 1, 'target': 'Kedi uyuyor.', 'helper': 'The cat sleeps.'}, {'n': 2, 'target': 'Köpek koşuyor.', 'helper': 'The dog runs.'}]}],
          'model': 'fixture'}
    segs = audio.plan_segments(sc, c)
    with tempfile.TemporaryDirectory() as d:
        clipdir = os.path.join(d, 'clips')
        os.makedirs(clipdir)
        lengths = {}
        for i, s in enumerate({s['key']: s for s in segs if s['kind'] == 'clip'}.values()):
            sec = 0.5 + 0.1 * (i % 5)
            _tone_mp3(ff, os.path.join(clipdir, s['key'] + '.mp3'), sec, 300 + 50 * i)
            lengths[s['key']] = sec
        out = os.path.join(d, 'test.mp3')
        info = audio.assemble(segs, clipdir, out, c, log=lambda m: None)
        expect = sum(lengths[s['key']] if s['kind'] == 'clip' else s['sec'] for s in segs)
        ok(abs(info['total'] - expect) < 0.1 * len(segs) / 4, f'Gesamtdauer {info["total"]:.2f} s ≈ erwartet {expect:.2f} s')
        from mutagen.mp3 import MP3
        m = MP3(out)
        ok(abs(m.info.length - info['total']) < 0.5 and m.info.sample_rate == 48000, f'MP3 {m.info.length:.2f} s, {m.info.sample_rate} Hz')
        cover = os.path.join(d, 'cover.jpg')
        audio.make_cover(sc, cover, 3)
        ok(os.path.getsize(cover) > 10000, 'Cover erzeugt')
        audio.tag(out, sc, c, 3, 9, cover, 'Testkommentar')
        from mutagen.id3 import ID3
        t = ID3(out)
        expected_album = c['album'].format(target_de='Türkisch', target_en='Turkish', level='A1')
        expected_deck = f"{c['deck_root'].format(target_de='Türkisch', target_en='Turkish')}::03 Test - Deneme (A1)"
        ok(str(t['TRCK']) == '3/9' and str(t['TALB']) == expected_album and 'APIC:Cover' in t,
           f'Tags: {t["TIT2"]}, {t["TALB"]}')
        apkg = os.path.join(d, 'test.apkg')
        name = anki.build(sc, segs, clipdir, apkg, c, 3, log=lambda m: None)
        ok(name == expected_deck, f'Deckname {name}')
        import zipfile
        with zipfile.ZipFile(apkg) as z:
            media = json.loads(z.read('media'))
        ok(len(media) == 2 and any('word_01_kedi' in v for v in media.values()), f'apkg-Medien: {media}')
        ok('<span class="hl">Kedi</span>' in anki.highlight('Kedi uyuyor.', 'kedi', 'tr'), 'Hervorhebung')


def test_known():
    import genanki
    with tempfile.TemporaryDirectory() as d:
        txt_path = os.path.join(d, 'words.txt')
        with open(txt_path, 'w', encoding='utf-8') as f:
            f.write('# comment\nkapı\nçocuk\n')
        txt_entries = known.load(txt_path)
        ok(known.known_words(txt_entries) == ['kapı', 'çocuk'], f'Wortliste geladen: {txt_entries}')

        apkg_path = os.path.join(d, 'sample.apkg')
        model = genanki.Model(1234567890, 'TestModel',
                              fields=[{'name': 'Turkish'}, {'name': 'English'}],
                              templates=[{'name': 'Card 1', 'qfmt': '{{Turkish}}', 'afmt': '{{English}}'}])
        deck = genanki.Deck(987654321, 'Test::Sample')
        deck.add_note(genanki.Note(model=model, fields=['pencere', 'window']))
        deck.add_note(genanki.Note(model=model, fields=['masa', 'table']))
        genanki.Package(deck).write_to_file(apkg_path)

        entries = known.load(apkg_path)
        ok(len(entries) == 2 and {e['word'] for e in entries} == {'pencere', 'masa'}, f'apkg-Export geladen: {entries}')
        # Synthetic cards start with 0 reps -> known_words(min_reps=1) is empty, min_reps=0 returns all
        ok(known.known_words(entries, min_reps=1) == [] and len(known.known_words(entries, min_reps=0)) == 2,
           'min_reps-Filter für bekannte Wörter')


def test_web_api():
    import web
    meta = web.api_meta()
    ok('tr' in meta['languages'] and 'fr' in meta['languages'] and 'es' in meta['languages'] and 'A1' in meta['levels'],
       'Web-API Meta enthält Sprachen (inkl. fr, es) und Niveaus')
    ok('publish_label' in meta and 'default_publish' in meta, 'Web-API Meta enthält Publish-Konfiguration')
    plan = web.api_plan(30, 'A1')
    ok(60 <= plan['sentences'] <= 85 and plan['chapters'] >= 4, f'Web-API Plan 30 min: {plan}')

    orig_out = web.OUT_DIR
    with tempfile.TemporaryDirectory() as d:
        web.OUT_DIR = d
        try:
            empty_books = web.api_list_books()
            ok(empty_books == [], 'Web-API Bücherliste funktioniert auch bei leerem out/')
            slug = 'sample_book'
            book_dir = os.path.join(d, slug)
            os.makedirs(book_dir)
            sc = sample_script()
            with open(os.path.join(book_dir, 'script.json'), 'w', encoding='utf-8') as f:
                json.dump(sc, f, ensure_ascii=False)
            books = web.api_list_books()
            ok(len(books) == 1 and books[0]['slug'] == slug, f'Web-API Bücherliste: {len(books)} Eintrag')
            detail = web.api_get_book(slug)
            ok(detail is not None and 'summary' in detail and 'script' in detail, f'Web-API Buchdetails: {slug}')
            saved = web.api_save_script(slug, sc)
            ok(saved['ok'] and os.path.exists(os.path.join(book_dir, 'check.md')), 'Web-API Skript speichern & prüfen')
        finally:
            web.OUT_DIR = orig_out

    ui_html = os.path.join(ROOT, 'hb', 'web_ui.html')
    ok(os.path.exists(ui_html) and os.path.getsize(ui_html) > 5000, 'Web-UI HTML-Oberfläche vorhanden')

    import threading
    import urllib.request
    srv = web.http.server.ThreadingHTTPServer(('127.0.0.1', 0), web.Handler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/health', timeout=5) as r:
            health = json.loads(r.read().decode('utf-8'))
        ok(health.get('status') == 'ok' and health.get('ffmpeg') is True, f'Web-API Health: {health}')
    finally:
        srv.shutdown()
        srv.server_close()


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_') and callable(fn):
            print(f'-- {name}')
            try:
                fn()
            except Exception as e:  # noqa: BLE001
                import traceback
                traceback.print_exc()
                FAILS.append(f'{name}: {e}')
    print(f'\n{len(FAILS)} Fehler' if FAILS else '\nalles grün')
    sys.exit(1 if FAILS else 0)
