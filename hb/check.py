"""Prüfschritt: erst textliche Regeln (Satzlänge, Niveau-Muster, Vokabelvorkommen, Dubletten, Abgleich mit den
bekannten Wörtern), dann ein zweiter Modell-Durchlauf als Korrektor (Grammatik, Niveau, Übersetzung). Fehler
der Stufe „error“ werden auf Wunsch übernommen, der Rest landet als Liste in check.md.
"""
import json
import re

from . import languages as L
from . import llm
from .script import all_sentences


def _lower(s, code):
    if code == 'tr':
        s = s.replace('I', 'ı').replace('İ', 'i')
    return s.lower()


def stem_regex(word, code):
    """Findet eine flektierte Form des Wortes im Satz: Mehrwortausdrücke über das längste Wort, Verben über den
    Stamm ohne Infinitivendung, sonst über den Anfang (mindestens 4 Zeichen)."""
    w = _lower(word, code).strip()
    parts = [p for p in re.split(r"[\s'’-]+", w) if p]
    tail = ''
    if code == 'tr' and parts and re.search(r'(mak|mek)$', parts[-1]) and len(parts[-1]) > 4:
        parts[-1] = parts[-1][:-3]
        # Stammauslaut-Vokal verengt sich vor -iyor (harca- → harcıyor, bekle- → bekliyor, ara- → arıyor): Vokal optional lassen
        if len(parts[-1]) >= 3 and parts[-1][-1] in 'aeıioöuü':
            parts[-1] = parts[-1][:-1]
            tail = '[aeıioöuü]?'
    if code == 'de' and parts and parts[-1].endswith('en') and len(parts[-1]) > 5:
        parts[-1] = parts[-1][:-2]
    if code in ('ru', 'uk') and parts and re.search(r'(ть|ти|ться|тися)$', parts[-1]) and len(parts[-1]) > 5:
        parts[-1] = re.sub(r'(ться|тися|ть|ти)$', '', parts[-1])
    if code == 'es' and parts:
        if re.search(r'(arse|erse|irse)$', parts[-1]) and len(parts[-1]) > 5:
            parts[-1] = re.sub(r'(arse|erse|irse)$', '', parts[-1])
        elif re.search(r'(ar|er|ir)$', parts[-1]) and len(parts[-1]) > 4:
            parts[-1] = parts[-1][:-2]
    if code == 'fr' and parts:
        if re.search(r'(er|ir|re)$', parts[-1]) and len(parts[-1]) > 4:
            parts[-1] = parts[-1][:-2]
    core = max(parts, key=len) if parts else w
    if core != (parts[-1] if parts else w):
        tail = ''
    if len(core) > 5 and code in ('tr', 'ru', 'uk', 'de', 'es', 'fr') and not tail:
        core = core[:max(4, len(core) - 1)]
    core = re.escape(core)
    if code == 'tr':
        core = core.replace('k', '[kğ]').replace('p', '[pb]').replace('t', '[td]').replace('ç', '[çc]')
        # Mittelsilben-Vokalausfall bei 5-buchstabigen Nomen (zihin → zihni, şehir → şehri, fikir → fikri, akıl → aklı)
        if not tail and re.search(r'[bcçdfgğhjklmnprsştvwyz][ıiuü][nrl]$', core):
            core = core[:-2] + '[ıiuü]?' + core[-1]
    return re.compile(r'(?<![^\W\d_])' + core + tail + r'[^\W\d_]*', re.UNICODE)


def find_form(word, sentence, code):
    m = stem_regex(word, code).search(_lower(sentence, code))
    if not m:
        return None
    return sentence[m.start():m.end()]


def deterministic(script, known=None):
    code, level = script['target'], script['level']
    sents = all_sentences(script)
    findings = []
    warn_n, err_n = L.MAX_WORDS.get(level, (22, 30))
    pats = L.level_patterns(code, level)
    for s in sents:
        wc = L.word_count(s['target'])
        if wc > err_n:
            findings.append(('error', f'Satz {s["n"]}', f'{wc} Wörter (Grenze {err_n} für {level})'))
        elif wc > warn_n:
            findings.append(('warn', f'Satz {s["n"]}', f'{wc} Wörter (Richtwert {warn_n} für {level})'))
        if not s['helper']:
            findings.append(('error', f'Satz {s["n"]}', 'Übersetzung fehlt'))
        for rx, label in pats:
            for m in rx.finditer(s['target']):
                findings.append(('hint', f'Satz {s["n"]}', f'{label}: „{m.group(0)}“'))
    if script['plan'] and abs(len(sents) - script['plan']['sentences']) > max(2, script['plan']['sentences'] * 0.2):
        findings.append(('warn', 'Umfang', f'{len(sents)} Sätze statt {script["plan"]["sentences"]}'))
    seen = {}
    for v in script['vocab']:
        key = _lower(v['target'], code)
        if key in seen:
            findings.append(('error', f'Vokabel {v["n"]}', f'doppelt: {v["target"]} (auch Nr. {seen[key]})'))
        seen[key] = v['n']
        if not v['helper']:
            findings.append(('error', f'Vokabel {v["n"]}', f'{v["target"]}: Übersetzung fehlt'))
        if script.get('extra') and not v.get('extra'):
            findings.append(('warn', f'Vokabel {v["n"]}', f'{v["target"]}: Zweitübersetzung fehlt'))
        hit = None
        idx = v.get('sentence')
        if isinstance(idx, int) and 1 <= idx <= len(sents) and find_form(v['target'], sents[idx - 1]['target'], code):
            hit = idx
        else:
            for s in sents:
                if find_form(v['target'], s['target'], code):
                    hit = s['n']
                    break
            if hit and idx != hit:
                findings.append(('fixed', f'Vokabel {v["n"]}', f'{v["target"]}: Beispielsatz {idx} → {hit}'))
        if hit is None:
            findings.append(('error', f'Vokabel {v["n"]}', f'{v["target"]} kommt in keinem Satz vor'))
        v['sentence'] = hit
    if known:
        kset = {_lower(k, code) for k in known}
        dup = [v['target'] for v in script['vocab'] if _lower(v['target'], code) in kset]
        if dup:
            findings.append(('hint', 'Bekannt', f'{len(dup)} Vokabeln sind schon im Anki-Bestand: {", ".join(dup)}'))
        used = sorted({k for k in known if any(find_form(k, s['target'], code) for s in sents)}, key=str.lower)
        findings.append(('info', 'Bekannt', f'{len(used)} von {len(known)} bekannten Wörtern kommen im Text vor'
                         + (': ' + ', '.join(used) if used else '')))
    return findings


REVIEW_PROMPT = """You are a strict proofreader for graded readers in {T}. Below is a learner text at CEFR {level}
with {H} translations. Check EVERY sentence and vocabulary item for:
(a) grammar, spelling or orthography errors in the {T} text (wrong suffix, vowel harmony, agreement, word order);
(b) violations of the level rules — {rules}
(c) a {H} translation that does not match the {T} sentence;
(d) vocabulary notes that are wrong (wrong meaning, wrong morphology).
Report only real problems. For each, give a corrected version that keeps the meaning and the level.
severity "error" = must be fixed (grammar error, clear level violation, wrong translation); "warn" = stylistic or
borderline. Do not rewrite sentences that are correct.

OUTPUT: only JSON:
{{"summary": "one or two sentences on overall quality and level fit",
 "sentences": [{{"n": 12, "severity": "error", "problem": "...", "target": "corrected {T}", "helper": "corrected {H}"}}],
 "vocab": [{{"n": 3, "severity": "warn", "problem": "...", "target": "...", "helper": "...", "note": "..."}}]}}

VOCABULARY:
{vocab}

TEXT:
{text}"""


def llm_review(script, cfg, log=print):
    T, H = L.lang(script['target']), L.lang(script['helper'])
    sents = all_sentences(script)
    text = '\n'.join(f'{s["n"]}. {s["target"]} | {s["helper"]}' for s in sents)
    vocab = '\n'.join(f'{v["n"]}. {v["target"]} = {v["helper"]} — {v["note"]}' for v in script['vocab'])
    prompt = REVIEW_PROMPT.format(T=T['name_en'], H=H['name_en'], level=script['level'],
                                  rules=T['rules'][script['level']], vocab=vocab, text=text)
    data, usage = llm.generate_json(prompt, cfg['model'], temperature=0.1, log=log)
    return data, usage


def apply_review(script, review, fix_levels=('error',)):
    """Übernimmt Korrekturen der angegebenen Stufen. Verhindert dabei, dass eine Vokabel durch eine Satz- oder
    Vokabelkorrektur ihren einzigen Belegsatz im Text verliert."""
    code = script.get('target', 'tr')
    all_s = all_sentences(script)
    sents = {s['n']: s for s in all_s}
    had_match = {v['n']: any(find_form(v['target'], s['target'], code) for s in all_s) for v in script.get('vocab', [])}
    applied = []
    sent_backups = {}
    for item in review.get('sentences', []) or []:
        n, sev = item.get('n'), item.get('severity', 'warn')
        if sev in fix_levels and n in sents:
            s = sents[n]
            old = (s['target'], s['helper'])
            if item.get('target'):
                s['target'] = item['target'].strip()
            if item.get('helper'):
                s['helper'] = item['helper'].strip()
            if old != (s['target'], s['helper']):
                sent_backups[n] = old
                applied.append(('Satz', n, old, (s['target'], s['helper']), item.get('problem', '')))
    vocab = {v['n']: v for v in script.get('vocab', [])}
    vocab_backups = {}
    for item in review.get('vocab', []) or []:
        n, sev = item.get('n'), item.get('severity', 'warn')
        if sev in fix_levels and n in vocab:
            v = vocab[n]
            old = (v['target'], v['helper'], v['note'])
            for k in ('target', 'helper', 'note'):
                if item.get(k):
                    v[k] = item[k].strip()
            if old != (v['target'], v['helper'], v['note']):
                vocab_backups[n] = old
                applied.append(('Vokabel', n, old, (v['target'], v['helper'], v['note']), item.get('problem', '')))
    # Sicherheitsnetz: keine Vokabel darf ihren Belegsatz im Text verlieren
    for v in script.get('vocab', []):
        vn = v['n']
        if not had_match.get(vn):
            continue
        if any(find_form(v['target'], s['target'], code) for s in all_s):
            continue
        # 1. Versuch: Vokabel-Änderung zurücknehmen, falls das alte Wort im aktuellen Text vorkommt
        if vn in vocab_backups and any(find_form(vocab_backups[vn][0], s['target'], code) for s in all_s):
            v['target'], v['helper'], v['note'] = vocab_backups[vn]
            applied = [a for a in applied if not (a[0] == 'Vokabel' and a[1] == vn)]
            continue
        # 2. Versuch: Zugehörigen Beispielsatz (und ggf. Vokabel) zurücknehmen
        sn = v.get('sentence')
        if sn in sent_backups:
            sents[sn]['target'], sents[sn]['helper'] = sent_backups[sn]
            applied = [a for a in applied if not (a[0] == 'Satz' and a[1] == sn)]
            if not any(find_form(v['target'], s['target'], code) for s in all_s) and vn in vocab_backups:
                v['target'], v['helper'], v['note'] = vocab_backups[vn]
                applied = [a for a in applied if not (a[0] == 'Vokabel' and a[1] == vn)]
    return applied


def report_md(script, findings, review, applied, skipped):
    T = L.lang(script['target'])
    lines = [f'# Prüfung: {script["short_title"]} ({T["name_de"]} {script["level"]})', '']
    counts = {}
    for lvl, _, _ in findings:
        counts[lvl] = counts.get(lvl, 0) + 1
    lines.append('## Textliche Prüfung')
    lines.append(', '.join(f'{k}: {v}' for k, v in sorted(counts.items())) or 'keine Befunde')
    lines.append('')
    for lvl, where, msg in findings:
        lines.append(f'- **{lvl}** · {where}: {msg}')
    lines.append('')
    lines.append('## Korrektor (Sprachmodell)')
    if review is None:
        lines.append('nicht gelaufen')
    else:
        lines.append(review.get('summary', ''))
        lines.append('')
        if applied:
            lines.append('### Übernommen')
            for kind, n, old, new, why in applied:
                lines.append(f'- {kind} {n}: {why}')
                lines.append(f'  - vorher: {" | ".join(old)}')
                lines.append(f'  - nachher: {" | ".join(new)}')
        if skipped:
            lines.append('')
            lines.append('### Nur gemeldet (nicht übernommen)')
            for kind, item in skipped:
                lines.append(f'- {kind} {item.get("n")} ({item.get("severity")}): {item.get("problem", "")}'
                             + (f' → „{item.get("target")}“' if item.get('target') else ''))
    return '\n'.join(lines) + '\n'


def run(script, cfg, known=None, fix=True, use_llm=True, log=print):
    findings = deterministic(script, known)
    review, applied, skipped = None, [], []
    if use_llm:
        log('Korrektor-Durchlauf …')
        review, _ = llm_review(script, cfg, log=log)
        if fix:
            applied = apply_review(script, review)
        fixed_keys = {(k, n) for k, n, *_ in applied}
        for kind, key in (('Satz', 'sentences'), ('Vokabel', 'vocab')):
            for item in review.get(key, []) or []:
                if (kind, item.get('n')) not in fixed_keys:
                    skipped.append((kind, item))
        if applied:
            findings = deterministic(script, known)  # nach den Korrekturen noch einmal
    errors = [f for f in findings if f[0] == 'error']
    log(f'Prüfung: {len(errors)} Fehler, {sum(1 for f in findings if f[0] == "warn")} Warnungen, '
        f'{sum(1 for f in findings if f[0] == "hint")} Hinweise; Korrektor: {len(applied)} übernommen, {len(skipped)} gemeldet')
    return findings, review, applied, skipped
