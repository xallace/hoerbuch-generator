"""Sprachtabelle: Namen, edge-tts-Stimmen, Niveauregeln für den Prompt und einfache Niveau-Prüfmuster.

Eine Sprache kann Ziel- oder Hilfssprache sein. Die Regeln sind Anweisungen an das Sprachmodell (Englisch, weil
der Prompt englisch ist). Die Prüfmuster finden typische Verstöße gegen das Niveau rein textlich; sie liefern
Warnungen, keine Urteile – die inhaltliche Prüfung macht der zweite Modell-Durchlauf in check.py.
"""
import re

LANGS = {
    'tr': {
        'name_en': 'Turkish', 'name_de': 'Türkisch', 'name_native': 'Türkçe',
        'voices': {'m': 'tr-TR-AhmetNeural', 'f': 'tr-TR-EmelNeural'},
        'chapter': 'Bölüm',
        'rules': {
            'A1': ("Strict A1 (true beginner). Only the present continuous (-iyor), the existential var/yok and the "
                   "copula with değil. Simple main clauses in Subject-Object-Verb order, 5 to 9 words. Cases limited to "
                   "accusative, dative, locative, ablative and the possessive suffixes. NO past (-di, -miş), NO future "
                   "(-ecek), NO aorist (-r), NO necessitative (-meli), NO conditional (-se), NO subordinate or relative "
                   "clauses (-dığı, -en, -ecek), NO converbs (-erek, -ip, -ince, -ken), NO passive or causative. Use the "
                   "most frequent everyday words; every rarer word must be one of the vocabulary items."),
            'A2': ("A2. Allowed: present continuous, simple past (-di), future (-ecek), aorist (-r), -meli, var/yok, "
                   "simple conjunctions (ve, ama, çünkü, sonra, o zaman), the converb -ip. Sentences of at most 12 "
                   "words, one clause each. NO relative clauses (-dığı, -en), NO -miş, NO conditional, NO passive."),
            'B1': ("B1. Natural but clear Turkish: relative clauses (-en, -dığı), -dığı zaman / -ince, conditional -se, "
                   "reported -miş, passive. At most 16 words per sentence, at most one subordinate clause."),
            'B2': "B2. Natural, idiomatic Turkish for an educated adult reader; keep sentences under 22 words.",
        },
        'patterns': {
            'A1': [
                (r"\w{2,}(dığı|diği|duğu|düğü|tığı|tiği|tuğu|tüğü)\w*", 'relative/participle -DIK'),
                (r"\w{2,}(arak|erek)\b", 'converb -ArAk'),
                (r"\w{2,}(ınca|ince|unca|ünce)\b", 'converb -IncA'),
                (r"\w{2,}(acak|ecek|acağ|eceğ)\w*", 'future -AcAk'),
                (r"\w{2,}(malı|meli)\w*", 'necessitative -mAlI'),
                (r"\w{3,}(mış|miş|muş|müş)(ım|im|um|üm|sın|sin|sun|sün|ız|iz|uz|üz|lar|ler|tır|tir|tur|tür)?\b",
                 'evidential past -mIş'),
                (r"\w{3,}(dı|di|du|dü|tı|ti|tu|tü)(m|k|nız|niz|nuz|nüz|lar|ler)\b", 'simple past -DI (check)'),
                (r"\w{3,}(ıl|il|ul|ül|ın|in|un|ün)(ıyor|iyor|uyor|üyor)\w*", 'passive -Il/-In (check)'),
            ],
            'A2': [
                (r"\w{2,}(dığı|diği|duğu|düğü|tığı|tiği|tuğu|tüğü)\w*", 'relative/participle -DIK'),
                (r"\w{3,}(mış|miş|muş|müş)(ım|im|um|üm|sın|sin|sun|sün|ız|iz|uz|üz|lar|ler|tır|tir|tur|tür)?\b",
                 'evidential past -mIş'),
                (r"\w{3,}(sa|se)(m|n|k|nız|niz|lar|ler)?\b", 'conditional -sA (check)'),
            ],
        },
    },
    'de': {
        'name_en': 'German', 'name_de': 'Deutsch', 'name_native': 'Deutsch',
        'voices': {'m': 'de-DE-ConradNeural', 'f': 'de-DE-KatjaNeural'},
        'chapter': 'Kapitel',
        'rules': {
            'A1': ("Strict A1. Present tense only (plus the modal verbs können, möchten, müssen, wollen). Main clauses, "
                   "5 to 9 words, subject-verb-object; 'und', 'aber', 'oder', 'dann' may join two short main clauses. "
                   "Nominative, accusative and the most common dative phrases (mit dem, in der) only. NO subordinate "
                   "clauses (dass, weil, wenn, obwohl), NO perfect or past tense, NO passive, NO Konjunktiv, NO genitive."),
            'A2': ("A2. Present, Perfekt, Präteritum of sein/haben/modal verbs; subordinate clauses with dass, weil, "
                   "wenn, als; dative; at most 12 words, at most one subordinate clause. NO passive, NO Konjunktiv II, "
                   "NO relative clauses."),
            'B1': ("B1. Clear standard German: Präteritum, relative clauses, passive in the present, Konjunktiv II with "
                   "würde, two-part conjunctions. At most 16 words per sentence."),
            'B2': "B2. Natural educated German; keep sentences under 22 words.",
        },
        'patterns': {
            'A1': [
                (r"\b(dass|obwohl|nachdem|während|bevor|damit|sodass|falls|weil|wenn|als)\b", 'subordinate clause'),
                (r"\b(wurde|wurden|würde|würden|hätte|hätten|wäre|wären|könnte|sollte|müsste)\b", 'passive/Konjunktiv'),
                (r"\b(hat|hast|habe|haben|ist|sind|bin|bist|seid)\b[^.!?]*\bge\w{2,}(t|en)\b", 'Perfekt (check)'),
                (r"\b(der|des|eines|einer)\b \w+s\b", 'genitive (check)'),
            ],
            'A2': [
                (r"\b(wurde|wurden|würde|würden|hätte|hätten|wäre|wären)\b", 'passive/Konjunktiv II'),
                (r"\b(der|die|das|dem|den|dessen|deren)\b,", 'relative clause (check)'),
            ],
        },
    },
    'ru': {
        'name_en': 'Russian', 'name_de': 'Russisch', 'name_native': 'Русский',
        'voices': {'m': 'ru-RU-DmitryNeural', 'f': 'ru-RU-SvetlanaNeural'},
        'chapter': 'Глава',
        'rules': {
            'A1': ("Strict A1. Present tense of imperfective verbs, the verb быть omitted in the present, 'у меня есть' "
                   "/ 'нет'. Nominative, accusative and prepositional (в/на + where) only, personal pronouns and basic "
                   "possessives. Sentences of 4 to 8 words, one clause. NO past or future, NO participles or gerunds, "
                   "NO 'который', NO conditional 'бы', NO instrumental or dative constructions."),
            'A2': ("A2. Present, past of both aspects, future with буду; genitive, dative and instrumental in frequent "
                   "phrases; потому что, если, когда, но, и. At most 12 words, at most one subordinate clause. NO "
                   "participles or gerunds, NO conditional."),
            'B1': ("B1. Clear standard Russian: который-clauses, conditional with бы, prefixed verbs of motion, a few "
                   "common participles. At most 16 words per sentence."),
            'B2': "B2. Natural educated Russian; keep sentences under 22 words.",
        },
        'patterns': {
            'A1': [
                (r"\w{3,}(ющий|ющая|ющее|ющие|ащий|ящий|вший|вшая|вшие|нный|нная|нные|емый|имый|тый)\w*", 'participle'),
                (r"\bбы\b", 'conditional бы'),
                (r"\b(котор\w+)\b", 'relative который'),
                (r"\w{3,}(ла|ли|ло)\b", 'past tense (check)'),
            ],
            'A2': [
                (r"\w{3,}(ющий|ющая|ющее|ющие|ащий|ящий|вший|вшая|вшие|нный|нная|нные|емый|имый)\w*", 'participle'),
                (r"\bбы\b", 'conditional бы'),
            ],
        },
    },
    'uk': {
        'name_en': 'Ukrainian', 'name_de': 'Ukrainisch', 'name_native': 'Українська',
        'voices': {'m': 'uk-UA-OstapNeural', 'f': 'uk-UA-PolinaNeural'},
        'chapter': 'Розділ',
        'rules': {
            'A1': ("Strict A1. Present tense of imperfective verbs, 'у мене є' / 'немає'. Nominative, accusative and "
                   "locative (в/на + where) only. Sentences of 4 to 8 words, one clause. NO past or future, NO "
                   "participles or gerunds, NO 'який', NO conditional 'б/би'."),
            'A2': ("A2. Present, past, future; genitive, dative, instrumental in frequent phrases; тому що, якщо, коли, "
                   "але, і. At most 12 words, at most one subordinate clause. NO participles, NO conditional."),
            'B1': "B1. Clear standard Ukrainian with який-clauses and conditional; at most 16 words per sentence.",
            'B2': "B2. Natural educated Ukrainian; keep sentences under 22 words.",
        },
        'patterns': {
            'A1': [
                (r"\w{3,}(ючий|уючий|ючи|вши|ний|тий)\b", 'participle/gerund (check)'),
                (r"\b(б|би)\b", 'conditional б/би'),
                (r"\b(як\w{1,2})\b,", 'relative який (check)'),
            ],
            'A2': [(r"\b(б|би)\b", 'conditional б/би')],
        },
    },
    'en': {
        'name_en': 'English', 'name_de': 'Englisch', 'name_native': 'English',
        'voices': {'m': 'en-US-GuyNeural', 'f': 'en-US-JennyNeural'},
        'chapter': 'Chapter',
        'rules': {
            'A1': ("Strict A1. Simple present and present continuous, 'there is/are', can/want to. Main clauses of 4 to "
                   "9 words. NO past or perfect tenses, NO passive, NO relative clauses, NO conditionals."),
            'A2': ("A2. Simple present, past simple, 'going to', because/when/but/so clauses. At most 12 words. NO "
                   "perfect tenses, NO passive, NO conditionals."),
            'B1': "B1. Clear standard English with perfect tenses, relative clauses and first/second conditional; at most 16 words.",
            'B2': "B2. Natural educated English; keep sentences under 22 words.",
        },
        'patterns': {
            'A1': [
                (r"\b(had|have|has) (been |)\w+(ed|en)\b", 'perfect tense'),
                (r"\b(would|could|should|might)\b", 'modal of past/conditional'),
                (r"\b(which|whom|whose)\b", 'relative clause'),
                (r"\b(was|were) \w+ed\b", 'passive/past (check)'),
            ],
            'A2': [(r"\b(had|have|has) (been |)\w+(ed|en)\b", 'perfect tense'), (r"\b(would)\b", 'conditional')],
        },
    },
    'fr': {
        'name_en': 'French', 'name_de': 'Französisch', 'name_native': 'Français',
        'voices': {'m': 'fr-FR-HenriNeural', 'f': 'fr-FR-DeniseNeural'},
        'chapter': 'Chapitre',
        'rules': {
            'A1': ("Strict A1 (true beginner). Present tense of indicative only (présent de l'indicatif), plus near future "
                   "(aller + infinitive) and basic modals (pouvoir, vouloir, devoir). Simple main clauses in Subject-Verb-Object "
                   "order, 5 to 9 words; 'et', 'mais', 'ou', 'puis' may join short clauses. NO passé composé, NO imparfait, "
                   "NO futur simple, NO subjonctif, NO conditionnel, NO passive, NO relative clauses (qui, que, dont, où), "
                   "NO subordinate clauses (parce que, quand, si, bien que). Use the most frequent everyday words."),
            'A2': ("A2. Allowed: présent, passé composé with avoir and être, imparfait for state/description, futur proche; "
                   "simple connectors (parce que, quand, si, mais, et, alors). Sentences of at most 12 words, at most one "
                   "subordinate clause. NO subjonctif, NO conditionnel, NO relative pronouns dont/auquel, NO passive."),
            'B1': ("B1. Clear standard French: contrast between imparfait and passé composé, futur simple, conditionnel présent, "
                   "basic subjunctive (il faut que, vouloir que), relative clauses (qui, que, où, dont). At most 16 words "
                   "per sentence, at most one subordinate clause."),
            'B2': "B2. Natural, idiomatic French for an educated adult reader; keep sentences under 22 words.",
        },
        'patterns': {
            'A1': [
                (r"\b(parce qu'|parce que|lorsque|quand|puisque|quoique|bien que|pendant que|si)\b", 'subordinate clause'),
                (r"\b(dont|lequel|laquelle|lesquels|lesquelles|auxquels|auxquelles)\b", 'relative pronoun'),
                (r"\b(serait|seraient|aurait|auraient|devrait|devraient|pourrait|pourraient|voudrait|voudraient|fasse|fassent|puisse|puissent|soit|soient|aient)\b",
                 'subjonctif/conditionnel'),
                (r"\w{3,}(ais|ait|ions|iez|aient)\b", 'imparfait (check)'),
                (r"\b(ai|as|a|avons|avez|ont|suis|es|est|sommes|êtes|sont)\b\s+\w+(é|ée|és|ées|i|ie|is|ies|u|ue|us|ues|ert|erte|erts|ertes|it|ite|its|ites)\b",
                 'passé composé (check)'),
            ],
            'A2': [
                (r"\b(fasse|fassent|puisse|puissent|soit|soient|ait|aient|veuille|veuillent|sache|sachent)\b", 'subjonctif (check)'),
                (r"\b(dont|auquel|auxquels|à laquelle|auxquelles|duquel|desquels|desquelles)\b", 'complex relative pronoun'),
                (r"\b(serait|seraient|aurait|auraient|pourrait|pourraient|devrait|devraient|voudrait|voudraient)\b", 'conditionnel'),
            ],
        },
    },
    'es': {
        'name_en': 'Spanish', 'name_de': 'Spanisch', 'name_native': 'Español',
        'voices': {'m': 'es-ES-AlvaroNeural', 'f': 'es-ES-ElviraNeural'},
        'chapter': 'Capítulo',
        'rules': {
            'A1': ("Strict A1 (true beginner). Present tense of indicative only (presente de indicativo), the existential 'hay', "
                   "and immediate future (ir a + infinitive). Basic modal verbs (querer, poder, tener que). Simple main clauses "
                   "in Subject-Verb-Object order, 5 to 9 words; 'y', 'pero', 'o', 'luego' may join short clauses. NO pretérito "
                   "indefinido (-é, -í, -ó), NO pretérito imperfecto (-aba, -ía), NO pretérito perfecto (he + participio), "
                   "NO subjuntivo, NO condicional, NO passive, NO relative clauses (que, quien, donde), NO subordinate clauses "
                   "(porque, cuando, si, aunque). Use the most frequent everyday words."),
            'A2': ("A2. Allowed: presente, pretérito indefinido, pretérito imperfecto, pretérito perfecto; simple connectors "
                   "(porque, cuando, si, pero, y, entonces). Sentences of at most 12 words, at most one subordinate clause. "
                   "NO subjuntivo, NO condicional, NO relative clauses with cuyo/el cual, NO passive."),
            'B1': ("B1. Clear standard Spanish: contrast between indefinido and imperfecto, futuro simple, condicional, "
                   "present subjunctive with common triggers (quiero que, cuando + future, para que), relative clauses "
                   "(que, quien, donde). At most 16 words per sentence."),
            'B2': "B2. Natural, idiomatic Spanish for an educated adult reader; keep sentences under 22 words.",
        },
        'patterns': {
            'A1': [
                (r"\b(porque|cuando|aunque|mientras|si|ya que|puesto que)\b", 'subordinate clause'),
                (r"\b(quien|quienes|cuyo|cuya|cuyos|cuyas|donde)\b", 'relative pronoun'),
                (r"\b(fue|fueron|estuvo|estuvieron|hizo|dijo|dijeron|tuvo|tuvieron|pudo|puso|vio|dio)\b", 'indefinido (check)'),
                (r"\w{3,}(aba|abas|ábamos|aban|ía|ías|íamos|ían)\b", 'imperfecto (check)'),
                (r"\b(he|has|ha|hemos|habéis|han)\b\s+\w+(ado|ido)\b", 'pretérito perfecto'),
                (r"\b(fuera|fuese|hubiera|hubiese|tuviera|pudiera|quisiera|sería|tendría|podría|habría)\b", 'condicional/subjuntivo'),
            ],
            'A2': [
                (r"\b(fuera|fuese|hubiera|hubiese|tuviera|tuviese|pudiera|pudiese|quisiera)\b", 'subjuntivo pasado'),
                (r"\b(cuyo|cuya|cuyos|cuyas|el cual|la cual|los cuales|las cuales)\b", 'complex relative pronoun'),
                (r"\b(sería|serían|tendría|tendrían|podría|podrían|habría|habrían)\b", 'condicional'),
            ],
        },
    },
}

LEVELS = ('A1', 'A2', 'B1', 'B2')
# words per sentence: (warn above, error above)
MAX_WORDS = {'A1': (9, 12), 'A2': (12, 16), 'B1': (16, 22), 'B2': (22, 30)}


def lang(code):
    code = code.lower()
    if code not in LANGS:
        raise SystemExit(f'Unbekannte Sprache {code!r}. Bekannt: {", ".join(sorted(LANGS))}')
    return LANGS[code]


def voice(code, gender='m'):
    return lang(code)['voices'].get(gender) or next(iter(lang(code)['voices'].values()))


def level_patterns(code, level):
    pats = lang(code).get('patterns', {}).get(level, [])
    return [(re.compile(p, re.IGNORECASE | re.UNICODE), label) for p, label in pats]


def word_count(sentence):
    return len(re.findall(r"[^\W\d_]+(?:['’-][^\W\d_]+)*", sentence, re.UNICODE))
