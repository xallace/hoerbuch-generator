"""Anki-Deck (.apkg) mit genanki: eine Note je Vokabel, zwei Karten (Hören/Erkennen, aktiver Abruf), Wort- und
Satzclip aus den Hörbuch-Aufnahmen. Deck- und Notentyp-IDs sind aus den Namen gehasht (stabil zwischen
Läufen; Pythons hash() wäre pro Prozess zufällig und würde jedes Mal ein neues Deck anlegen).
"""
import hashlib
import html
import os
import re
import shutil

import genanki

from . import languages as L
from .check import find_form
from .script import all_sentences, slugify

CSS = """
.card { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; font-size: 16px;
  text-align: center; color: #1e293b; background-color: #f1f5f9; padding: 16px; margin: 0; }
.nightMode .card { color: #f1f5f9; background-color: #0b0f19; }
.anki-box { max-width: 460px; margin: 0 auto; background: #fff; border-radius: 20px; border: 1px solid #e2e8f0;
  box-shadow: 0 10px 25px -5px rgba(0,0,0,.08); padding: 24px 22px; box-sizing: border-box; }
.nightMode .anki-box { background: #1e293b; border-color: #334155; }
.badge { display: inline-block; font-size: 11px; font-weight: 700; letter-spacing: .07em; text-transform: uppercase;
  color: #4f46e5; background: #eef2ff; border: 1px solid #c7d2fe; padding: 5px 14px; border-radius: 9999px; margin-bottom: 16px; }
.nightMode .badge { color: #818cf8; background: rgba(79,70,229,.15); border-color: rgba(129,140,248,.25); }
.badge-prod { color: #059669; background: #ecfdf5; border-color: #a7f3d0; }
.nightMode .badge-prod { color: #34d399; background: rgba(5,150,105,.15); border-color: rgba(52,211,153,.25); }
.main-word { font-size: 34px; font-weight: 800; color: #0f172a; line-height: 1.25; margin: 10px 0 6px; }
.nightMode .main-word { color: #f8fafc; }
.meaning-text { font-size: 22px; font-weight: 700; color: #4f46e5; margin: 10px 0 6px; line-height: 1.3; }
.nightMode .meaning-text { color: #818cf8; }
.extra-text { font-size: 15px; color: #64748b; }
.prompt-sub { font-size: 13.5px; color: #64748b; margin-top: 10px; }
.divider { height: 1px; background: #e2e8f0; margin: 20px 0 16px; }
.nightMode .divider { background: #334155; }
.section-label { font-size: 10.5px; font-weight: 700; letter-spacing: .08em; text-transform: uppercase; color: #64748b;
  margin-bottom: 6px; text-align: left; }
.context-card { background: #f8fafc; border-radius: 12px; border-left: 4px solid #4f46e5; padding: 12px 14px;
  text-align: left; margin: 12px 0; }
.nightMode .context-card { background: #0f172a; border-left-color: #818cf8; }
.context-tr { font-size: 16px; font-weight: 600; color: #1e293b; line-height: 1.45; margin-bottom: 6px; }
.nightMode .context-tr { color: #e2e8f0; }
.context-en { font-size: 14px; color: #475569; line-height: 1.4; }
.nightMode .context-en { color: #94a3b8; }
.hl { color: #4f46e5; font-weight: 800; text-decoration: underline; text-decoration-thickness: 2px; text-underline-offset: 3px; }
.nightMode .hl { color: #818cf8; }
.grammar-box { background: #fffbeb; border: 1px solid #fef3c7; border-radius: 10px; padding: 12px 14px; text-align: left;
  font-size: 13px; color: #92400e; line-height: 1.5; margin: 14px 0 10px; }
.nightMode .grammar-box { background: rgba(245,158,11,.1); border-color: rgba(245,158,11,.25); color: #fde68a; }
.meta-footer { font-size: 11px; color: #94a3b8; margin-top: 16px; padding-top: 10px; border-top: 1px dashed #e2e8f0; }
"""

FIELDS = ['ID', 'Target', 'Helper', 'Extra', 'AudioTarget', 'ExampleTarget', 'ExampleHelper', 'ExampleAudio',
          'GrammarNote', 'ThemeInfo']

BACK = """
<div class="anki-box">
  <div class="badge{cls}">{badge}</div>
  <div class="main-word">{{{{Target}}}}</div>
  <div style="margin: 8px 0;">{{{{AudioTarget}}}}</div>
  <div class="meaning-text">{{{{Helper}}}}</div>
  {{{{#Extra}}}}<div class="extra-text">{{{{Extra}}}}</div>{{{{/Extra}}}}
  <div class="divider"></div>
  <div class="section-label">Audiobook context</div>
  <div class="context-card">
    <div class="context-tr">{{{{ExampleTarget}}}}</div>
    <div style="margin: 6px 0;">{{{{ExampleAudio}}}}</div>
    <div class="context-en">{{{{ExampleHelper}}}}</div>
  </div>
  <div class="section-label">Morphology &amp; grammar</div>
  <div class="grammar-box">{{{{GrammarNote}}}}</div>
  <div class="meta-footer">{{{{ThemeInfo}}}}</div>
</div>"""


def stable_id(name, digits=9):
    return int(hashlib.sha1(name.encode('utf-8')).hexdigest()[:12], 16) % (10 ** digits) + 10 ** (digits - 1)


def model_for(target, helper, extra):
    T, H = L.lang(target), L.lang(helper)
    name = f'Hörbuch Vokabel {T["name_en"]}-{H["name_en"]}' + (f'+{L.lang(extra)["name_en"]}' if extra else '')
    badge = f'{T["name_en"]} · {{{{ThemeInfo}}}}'
    front1 = f"""
<div class="anki-box">
  <div class="badge">{badge}</div>
  <div class="main-word">{{{{Target}}}}</div>
  <div style="margin: 12px 0;">{{{{AudioTarget}}}}</div>
  <div class="prompt-sub">🎧 Listen &amp; recall the meaning</div>
</div>"""
    front2 = f"""
<div class="anki-box">
  <div class="badge badge-prod">Active recall · {H["name_en"]} ➔ {T["name_en"]}</div>
  <div class="meaning-text" style="font-size: 26px; margin: 16px 0 8px;">{{{{Helper}}}}</div>
  <div class="context-en" style="font-style: italic; margin-bottom: 14px;">"{{{{ExampleHelper}}}}"</div>
  <div class="prompt-sub">✍️ How do you say this in {T["name_en"]}?</div>
</div>"""
    return genanki.Model(
        stable_id(name, 10), name,
        fields=[{'name': f} for f in FIELDS],
        templates=[
            {'name': f'1. {T["name_en"]} ➔ {H["name_en"]} (listen & recognise)', 'qfmt': front1,
             'afmt': BACK.format(cls='', badge=badge)},
            {'name': f'2. {H["name_en"]} ➔ {T["name_en"]} (active recall)', 'qfmt': front2,
             'afmt': BACK.format(cls=' badge-prod', badge=f'Active recall · {H["name_en"]} ➔ {T["name_en"]}')},
        ],
        css=CSS)


def highlight(sentence, word, code):
    form = find_form(word, sentence, code)
    if not form:
        return html.escape(sentence)
    i = sentence.find(form)
    return html.escape(sentence[:i]) + f'<span class="hl">{html.escape(form)}</span>' + html.escape(sentence[i + len(form):])


def build(script, segments, clipdir, out_apkg, cfg, track, log=print):
    T = L.lang(script['target'])
    deck_name = f"{cfg['deck_root'].format(target_de=T['name_de'], target_en=T['name_en'])}::" \
                f"{track:02d} {script['short_title']} ({script['level']})"
    deck = genanki.Deck(stable_id(deck_name), deck_name)
    model = model_for(script['target'], script['helper'], script.get('extra'))
    sents = {s['n']: s for s in all_sentences(script)}
    by_ref = {}
    for s in segments:
        if s['kind'] == 'clip' and s['role'] in ('word', 'sentence') and s['ref'] is not None:
            by_ref.setdefault((s['role'], s['ref']), s['key'])
    media_dir = os.path.join(os.path.dirname(out_apkg), 'anki_media')
    os.makedirs(media_dir, exist_ok=True)
    prefix = slugify(script['short_title'], 24).lower()
    media = []
    theme = f'{script["short_title"]} ({script["level"]})'
    tags = [script['level'], T['name_en'], 'YouTubeAudiobook', slugify(script['short_title'], 30)]
    for v in script['vocab']:
        n = v['n']
        word_clip = by_ref.get(('word', n))
        sent = sents.get(v.get('sentence')) if v.get('sentence') else None
        sent_clip = by_ref.get(('sentence', sent['n'])) if sent else None
        fields = {'ID': f'{n:02d}', 'Target': v['target'], 'Helper': v['helper'], 'Extra': v.get('extra', ''),
                  'AudioTarget': '', 'ExampleTarget': '', 'ExampleHelper': '', 'ExampleAudio': '',
                  'GrammarNote': html.escape(v['note']), 'ThemeInfo': f'{theme} · Word #{n:02d}'}
        if word_clip:
            name = f'{prefix}_word_{n:02d}_{slugify(v["target"], 20).lower()}.mp3'
            shutil.copyfile(os.path.join(clipdir, word_clip + '.mp3'), os.path.join(media_dir, name))
            media.append(os.path.join(media_dir, name))
            fields['AudioTarget'] = f'[sound:{name}]'
        if sent:
            fields['ExampleTarget'] = highlight(sent['target'], v['target'], script['target'])
            fields['ExampleHelper'] = html.escape(sent['helper'])
            if sent_clip:
                name = f'{prefix}_sent_{sent["n"]:02d}.mp3'
                shutil.copyfile(os.path.join(clipdir, sent_clip + '.mp3'), os.path.join(media_dir, name))
                if os.path.join(media_dir, name) not in media:
                    media.append(os.path.join(media_dir, name))
                fields['ExampleAudio'] = f'[sound:{name}]'
        note = genanki.Note(model=model, fields=[fields[f] for f in FIELDS], tags=tags,
                            guid=genanki.guid_for(deck_name, v['target']))
        deck.add_note(note)
    pkg = genanki.Package(deck)
    pkg.media_files = media
    pkg.write_to_file(out_apkg)
    log(f'Anki: {out_apkg} – Deck „{deck_name}“, {len(script["vocab"])} Noten, {len(media)} Clips')
    return deck_name
