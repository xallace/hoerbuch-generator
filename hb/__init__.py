"""Hörbuch-Generator: YouTube-Video oder Text → Lernhörbuch (MP3) + Anki-Deck (.apkg).

Stufen: source (Text holen) → script (Sprachmodell schreibt die Fassung) → check (prüfen, ggf. korrigieren)
→ audio (edge-tts + ffmpeg) → anki (genanki) → readme. Einstieg: hoerbuch.py im Ordner darüber.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')


def load_config(path=None):
    """Load config.json and merge optional config.local.json overrides."""
    cfg_path = path or os.path.join(ROOT, 'config.json')
    with open(cfg_path, encoding='utf-8') as f:
        cfg = json.load(f)
    local_path = os.path.join(os.path.dirname(os.path.abspath(cfg_path)), 'config.local.json')
    if os.path.exists(local_path):
        with open(local_path, encoding='utf-8') as f:
            local = json.load(f)
        for key, val in local.items():
            if isinstance(val, dict) and isinstance(cfg.get(key), dict):
                cfg[key] = {**cfg[key], **val}
            else:
                cfg[key] = val
    return cfg


def resolve_path(value, base=ROOT):
    """Expand env vars / user home and turn relative paths into absolute paths under base."""
    if not value:
        return ''
    expanded = os.path.expanduser(os.path.expandvars(str(value).strip()))
    if os.path.isabs(expanded):
        return os.path.normpath(expanded)
    return os.path.normpath(os.path.join(base, expanded))
