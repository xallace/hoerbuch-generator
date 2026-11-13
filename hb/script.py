"""Aus Quelltext wird die abgestufte Fassung: Planung (wie viele Sätze, Vokabeln, Kapitel für die Wunschdauer),
Prompt, Aufruf des Modells, Normalisierung und Ablage als script.json.

Schätzwerte je Satz (Zielsprache mit 80 % Tempo), nachgemessen am Lauf vom 09.11.2026 (15 A1-Sätze, 8 Vokabeln,
edge-tts Ahmet/Guy → 395 s): zweisprachiger Teil + Immersion ≈ 20,5 s je Satz; je Vokabel im Sandwich ≈ 9,5 s;
Titel und Übergänge ≈ 15 s; je Kapitelansage ≈ 6 s. Höhere Niveaus haben längere Sätze (Faktor).
"""
import math
import re
import unicodedata

from . import languages as L
from . import llm

LEVEL_FACTOR = {'A1': 1.0, 'A2': 1.25, 'B1': 1.5, 'B2': 1.8}
SENT_SECONDS = 20.5
VOCAB_SECONDS = 9.5
FIXED_SECONDS = 15.0
CHAPTER_SECONDS = 6.0

TR_MAP = str.maketrans('ıİşŞğĞçÇöÖüÜâîû', 'iIsSgGcCoOuUaiu')


def slugify(title, max_len=60):
    s = title.translate(TR_MAP)
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode()
    s = re.sub(r"[^A-Za-z0-9]+", '_', s).strip('_')
    s = re.sub(r'_+', '_', s)
    return (s[:max_len].rstrip('_') or 'hoerbuch')


def safe_filename(name):
    """Entfernt alles, was Windows in Dateinamen verbietet (z. B. den Doppelpunkt in „Metal Gear Solid: …“)."""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', name).strip().rstrip('.')
    return name or 'hoerbuch'


def plan(minutes, level, chapter_size=15, vocab=None, sentences=None):
    f = LEVEL_FACTOR.get(level, 1.0)
    if sentences is None:
        s = 12
        v = vocab
        for _ in range(3):
            v_eff = v if v is not None else max(8, min(30, round(s / 4)))
            c = max(1, math.ceil(s / chapter_size))
            s = (minutes * 60 - FIXED_SECONDS - VOCAB_SECONDS * v_eff - CHAPTER_SECONDS * c) / (SENT_SECONDS * f)
            s = max(6, round(s))
        sentences = s
    if vocab is None:
        vocab = max(8, min(30, round(sentences / 4)))
    chapters = max(1, math.ceil(sentences / chapter_size))
    est = FIXED_SECONDS + VOCAB_SECONDS * vocab + CHAPTER_SECONDS * chapters + SENT_SECONDS * f * sentences
    return {'minutes': minutes, 'sentences': sentences, 'vocab': vocab, 'chapters': chapters,
            'estimated_seconds': round(est)}


def build_prompt(source, target, helper, extra, level, p, known=None):
    T, H = L.lang(target), L.lang(helper)
    E = L.lang(extra) if extra else None
    per = math.ceil(p['sentences'] / p['chapters'])
    known_block = ''
    if known:
        known_block = (
            f"\nLEARNER'S KNOWN WORDS ({len(known)} words already reviewed in Anki): "
            + ', '.join(known) +
            "\nUse these words freely in the sentences as anchors (they help the learner), but do NOT choose them as "
            "vocabulary items; the vocabulary items must be NEW words that this story needs.\n")
    extra_field = f'"extra": "translation into {E["name_en"]}", ' if E else ''
    extra_rule = f' and "extra" (the same translation into {E["name_en"]})' if E else ''
    return f"""You are an expert teacher of {T['name_en']} and an author of graded readers for adult learners.
Rewrite the source below as an original, coherent retelling in {T['name_en']} for learners at CEFR level {level},
with a faithful {H['name_en']} translation of every sentence. The result is read aloud as an audiobook.

LEVEL RULES FOR {T['name_en']} {level}: {T['rules'][level]}

STRUCTURE
- Exactly {p['sentences']} sentences, divided into {p['chapters']} chapter(s) of about {per} sentences each, in
  reading order. Each chapter has a short title in {T['name_en']} ("title_target") and {H['name_en']} ("title_helper").
- Follow the source's line of thought from beginning to end and keep its key facts, names and examples. Do not
  invent facts. Simplify the language, not the ideas: a learner should still get what the speaker says.
- Exactly {p['vocab']} vocabulary items ("sandwich words"): the words a learner at {level} most needs for this
  story. Dictionary form (verbs in the infinitive, nouns in the singular), each appearing in at least one sentence,
  no duplicates, no proper names. Each item has "target", "helper" (short translation){extra_rule}, "note" (one or
  two short sentences in {H['name_en']}: the form used in the story with its suffix or ending explained, plus one
  usage hint; do not quote sentence numbers in the note) and "sentence" (the 1-based number, counting all sentences in reading order, of a sentence where
  the word occurs).{known_block}
- {H['name_en']} translations must be accurate and natural and mirror the sentence structure where possible, so
  the learner can map the words.
- "title_helper": a short title in {H['name_en']} (at most 8 words); "title_target": the same in {T['name_en']};
  "short_title": "<speaker or channel> - <short title>" in {H['name_en']}, at most 60 characters, without
  colons or quotation marks; "intro": one or two sentences in {H['name_en']} saying what the source is about.
- Normal orthography only (for Turkish: ı İ ş ğ ç ö ü), no transliteration, no markdown, no numbering or
  speaker labels inside the strings, no line breaks inside a sentence.

OUTPUT: only this JSON object, nothing else:
{{"title_helper": "...", "title_target": "...", "short_title": "...", "intro": "...",
 "vocab": [{{"target": "...", "helper": "...", {extra_field}"note": "...", "sentence": 1}}],
 "chapters": [{{"title_target": "...", "title_helper": "...", "sentences": [{{"target": "...", "helper": "..."}}]}}]}}

SOURCE ({source.get('kind', 'text')}; title: {source.get('title', '')!r}; by {source.get('author', '') or 'unknown'};
{len(source['text'])} characters):
<<<
{source['text']}
>>>"""


def _clean(s):
    s = re.sub(r'\s+', ' ', str(s or '')).strip()
    s = re.sub(r'^\s*(\d+[.)]|[-•*])\s+', '', s)
    return s


def normalize(data, target, helper, extra, level, p, source, model, usage, known=None):
    chapters = []
    n = 0
    for ch in data.get('chapters', []):
        sents = []
        for s in ch.get('sentences', []):
            t, h = _clean(s.get('target')), _clean(s.get('helper'))
            if not t:
                continue
            n += 1
            sents.append({'n': n, 'target': t, 'helper': h})
        if sents:
            chapters.append({'title_target': _clean(ch.get('title_target')), 'title_helper': _clean(ch.get('title_helper')),
                             'sentences': sents})
    vocab = []
    seen = set()
    for i, v in enumerate(data.get('vocab', []), 1):
        w = _clean(v.get('target'))
        if not w or w.lower() in seen:
            continue
        seen.add(w.lower())
        item = {'n': len(vocab) + 1, 'target': w, 'helper': _clean(v.get('helper')), 'note': _clean(v.get('note')),
                'sentence': v.get('sentence')}
        if extra:
            item['extra'] = _clean(v.get('extra'))
        vocab.append(item)
    short = _clean(data.get('short_title')) or _clean(data.get('title_helper')) or source.get('title', 'Hörbuch')
    short = safe_filename(short.replace(':', ' -'))[:60]
    return {
        'version': 1,
        'target': target, 'helper': helper, 'extra': extra, 'level': level,
        'title_helper': _clean(data.get('title_helper')) or short,
        'title_target': _clean(data.get('title_target')),
        'short_title': short,
        'intro': _clean(data.get('intro')),
        'source': {k: source.get(k) for k in ('title', 'author', 'url', 'kind', 'meta')},
        'plan': p,
        'known_count': len(known or []),
        'vocab': vocab,
        'chapters': chapters,
        'model': model,
        'usage': usage,
    }


def all_sentences(script):
    return [s for ch in script['chapters'] for s in ch['sentences']]


def write(source, target, helper, extra, level, p, cfg, known=None, log=print):
    prompt = build_prompt(source, target, helper, extra, level, p, known)
    log(f'Fassung: {p["sentences"]} Sätze, {p["vocab"]} Vokabeln, {p["chapters"]} Kapitel, '
        f'geschätzt {p["estimated_seconds"] // 60}:{p["estimated_seconds"] % 60:02d} min; Prompt {len(prompt)} Zeichen')
    data, usage = llm.generate_json(prompt, cfg['model'], temperature=cfg.get('temperature', 0.4), log=log)
    script = normalize(data, target, helper, extra, level, p, source, cfg['model'], usage, known)
    got = len(all_sentences(script))
    if abs(got - p['sentences']) > max(2, p['sentences'] * 0.2):
        log(f'  Achtung: {got} Sätze statt {p["sentences"]} angefordert')
    if len(script['vocab']) != p['vocab']:
        log(f'  Achtung: {len(script["vocab"])} Vokabeln statt {p["vocab"]}')
    return script
