"""Bekannte Vokabeln aus einem Anki-Export (.apkg) oder einer Textliste (ein Wort je Zeile) lesen.

Neue Anki-Versionen packen die Datenbank zstd-komprimiert als collection.anki21b; daneben liegt eine fast leere
collection.anki2. Gelesen wird das Wortfeld (Feld „Turkish“/„Target“ oder das erste Feld, das nicht „ID“ heißt)
samt Wiederholungen und Intervall der zugehörigen Karten. „Bekannt“ heißt: mindestens einmal wiederholt.
"""
import json
import os
import re
import sqlite3
import tempfile
import zipfile

WORD_FIELDS = ('turkish', 'target', 'word', 'front', 'vokabel')


def _strip_html(s):
    return re.sub(r'<[^>]+>|\[sound:[^\]]+\]', '', s).strip()


def load(path):
    """Gibt eine Liste {word, reps, ivl, deck} zurück, sortiert nach Wiederholungen (absteigend)."""
    if path.lower().endswith('.apkg'):
        return _load_apkg(path)
    with open(path, encoding='utf-8-sig') as f:
        words = [w.strip() for w in f if w.strip() and not w.startswith('#')]
    return [{'word': w, 'reps': 1, 'ivl': 0, 'deck': os.path.basename(path)} for w in words]


def _load_apkg(path):
    with tempfile.TemporaryDirectory() as d:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            if 'collection.anki21b' in names:
                import zstandard  # pip install zstandard
                raw = zstandard.ZstdDecompressor().stream_reader(z.open('collection.anki21b')).read()
                db_path = os.path.join(d, 'col.sqlite')
                with open(db_path, 'wb') as f:
                    f.write(raw)
            else:
                member = 'collection.anki21' if 'collection.anki21' in names else 'collection.anki2'
                db_path = z.extract(member, d)
        db = sqlite3.connect(db_path)
        # Ankis Schema nutzt die Sortierung „unicase“, die SQLite nicht kennt
        db.create_collation('unicase', lambda a, b: (a.lower() > b.lower()) - (a.lower() < b.lower()))
        try:
            return _read(db)
        finally:
            db.close()


def _field_index(db):
    """notetype id → Index des Wortfelds, für neue (Tabelle fields) und alte (col.models) Schemata."""
    idx = {}
    tables = {r[0] for r in db.execute("select name from sqlite_master where type='table'")}
    if 'fields' in tables and db.execute('select count(*) from fields').fetchone()[0]:
        for ntid, ord_, name in db.execute('select ntid, ord, name from fields order by ntid, ord'):
            idx.setdefault(ntid, [])
            idx[ntid].append((ord_, name))
    else:
        models = json.loads(db.execute('select models from col').fetchone()[0])
        for mid, m in models.items():
            idx[int(mid)] = [(i, f['name']) for i, f in enumerate(m['flds'])]
    out = {}
    for ntid, flds in idx.items():
        pick = None
        for ord_, name in flds:
            if name.lower() in WORD_FIELDS:
                pick = ord_
                break
        if pick is None:
            pick = next((o for o, n in flds if n.lower() != 'id'), 0)
        out[ntid] = pick
    return out


def _read(db):
    fidx = _field_index(db)
    tables = {r[0] for r in db.execute("select name from sqlite_master where type='table'")}
    if 'decks' in tables and db.execute('select count(*) from decks').fetchone()[0]:
        decks = {r[0]: r[1].replace('\x1f', '::') for r in db.execute('select id, name from decks')}
    else:
        decks = {int(k): v['name'] for k, v in json.loads(db.execute('select decks from col').fetchone()[0]).items()}
    rows = {}
    for nid, mid, flds, did, reps, ivl in db.execute(
            'select n.id, n.mid, n.flds, c.did, c.reps, c.ivl from notes n join cards c on c.nid = n.id'):
        fields = flds.split('\x1f')
        word = _strip_html(fields[fidx.get(mid, 0)] if fidx.get(mid, 0) < len(fields) else fields[0])
        if not word:
            continue
        r = rows.setdefault(nid, {'word': word, 'reps': 0, 'ivl': 0, 'deck': decks.get(did, '')})
        r['reps'] += reps or 0
        r['ivl'] = max(r['ivl'], ivl or 0)
    return sorted(rows.values(), key=lambda r: (-r['reps'], r['word']))


def known_words(entries, min_reps=1):
    return [e['word'] for e in entries if e['reps'] >= min_reps]
