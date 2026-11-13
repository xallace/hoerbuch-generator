"""README_AND_TRANSCRIPT_<slug>.md im Stil der handgebauten Hörbücher: Kopf, Didaktik, Glossar, Skript, Zeitleiste
(aus den echten Clip-Dauern), Importhinweise. Dazu die Prüfbefunde als Anhang."""
from . import languages as L
from .audio import fmt


def build(script, segments, tl, deck_name, files, cfg, track, total, check_md=None):
    T, H = L.lang(script['target']), L.lang(script['helper'])
    E = L.lang(script['extra']) if script.get('extra') else None
    vt = L.voice(script['target'], cfg['voice_gender']['target'])
    vh = L.voice(script['helper'], cfg['voice_gender']['helper'])
    sents = {s['n']: s for ch in script['chapters'] for s in ch['sentences']}
    n_s = len(sents)
    src = script.get('source') or {}
    total_sec = tl[-1]['end'] if tl else 0
    lines = [f'# {script["short_title"]} ({T["name_de"]} {script["level"]})',
             f'## {script["title_helper"]}' + (f' · {script["title_target"]}' if script.get('title_target') else ''),
             '',
             '> [!NOTE]',
             f'> **Quelle:** {src.get("title", "")}' + (f' – {src.get("author")}' if src.get('author') else '')
             + (f' ({src.get("url")})' if src.get('url') else ''),
             f'> **Niveau:** {T["name_de"]} {script["level"]}, Hilfssprache {H["name_de"]}'
             + (f', Zweitübersetzung {E["name_de"]}' if E else ''),
             f'> **Stimmen:** {vt} ({cfg["target_rate"]}) und {vh} ({cfg["helper_rate"]}), edge-tts',
             f'> **Dauer:** {fmt(total_sec)} min, {len(script["chapters"])} Kapitel, {n_s} Sätze, '
             f'{len(script["vocab"])} Sandwich-Vokabeln; Anki-Deck mit {len(script["vocab"])} Noten',
             f'> **Album:** Track {track:02d}/{total:02d} in „{cfg["album"].format(target_de=T["name_de"], target_en=T["name_en"], level=script["level"])}“',
             f'> **Erzeugt mit:** Hoerbuch-Generator, Modell {script.get("model", "")}',
             '',
             '---', '',
             '## 1. Inhalt und Niveau', '',
             script.get('intro', ''), '',
             f'**Regeln für {T["name_en"]} {script["level"]} (Prompt):** {T["rules"][script["level"]]}', '',
             '---', '',
             f'## 2. Die {len(script["vocab"])} Kernvokabeln', '',
             f'| # | {T["name_de"]} | {H["name_de"]} |' + (f' {E["name_de"]} |' if E else '') + ' Beispielsatz | Grammatik |',
             '|---|---|---|' + ('---|' if E else '') + '---|---|']
    for v in script['vocab']:
        ex = sents.get(v.get('sentence'), {}).get('target', '')
        row = f'| **{v["n"]:02d}** | **{v["target"]}** | {v["helper"]} |'
        if E:
            row += f' {v.get("extra", "")} |'
        row += f' *{ex}* | {v["note"]} |'
        lines.append(row)
    lines += ['', '---', '', f'## 3. Vollständiges Skript ({n_s} Sätze)', '']
    for i, ch in enumerate(script['chapters'], 1):
        lines.append(f'### {T["chapter"]} {i}: {ch["title_target"]} ({ch["title_helper"]})')
        for s in ch['sentences']:
            lines.append(f'{s["n"]}. **{script["target"].upper()}:** {s["target"]}  ')
            lines.append(f'   **{script["helper"].upper()}:** {s["helper"]}')
        lines.append('')
    lines += ['---', '', f'## 4. Hörbuch-Struktur ({fmt(total_sec)} min)', '']
    P = cfg['pauses']
    desc = {
        'title': f'Titel ({vh})',
        'vocab': f'Vokabel-Sandwich: {T["name_de"]} ➔ {H["name_de"]} ➔ {T["name_de"]}, {len(script["vocab"])} Wörter, '
                 f'Zielsprache mit {cfg["target_rate"]}',
        'story': f'Zweisprachige Geschichte: Satz ➔ {P["think"]} s Denkpause ➔ Übersetzung ➔ {P["consolidate"]} s Pause',
        'immersion': f'100 % {T["name_de"]}: alle {n_s} Sätze am Stück mit {P["breath"]} s Atempausen',
    }
    for k, t in enumerate(tl, 1):
        lines.append(f'{k}. **[{fmt(t["start"])} – {fmt(t["end"])}] {t["name"]}:** {desc[t["phase"]]}')
    lines += ['', '---', '', '## 5. Dateien und Import', '']
    for label, path in files:
        lines.append(f'- **{label}:** `{path}`')
    lines += ['', f'Anki ordnet das Deck unter `{deck_name}` ein. Die MP3 trägt ID3v2.3-Tags (Album, Track, Cover) für '
                  'Hörbuch-Player wie BookPlayer oder Smart AudioBook Player.', '']
    if check_md:
        lines += ['---', '', '## Anhang: Prüfbericht', '', check_md.split('\n', 1)[1] if '\n' in check_md else check_md]
    return '\n'.join(lines) + '\n'
