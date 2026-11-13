"""Gemini über die REST-Schnittstelle (ohne SDK). Schlüssel aus GEMINI_API_KEY, .env oder gemini_key.txt.

Die Modellkennung steht in config.json ("model"). Nutzt Server-Sent Events (:streamGenerateContent?alt=sse),
damit auch bei langen 30-Minuten-Skripten (75–90 Sätze) kontinuierlich Daten fließen und kein Idle-Timeout
(RemoteDisconnected) auftritt. Bei 429/5xx oder Netzabbruch wird mit wachsender Pause neu versucht.
"""
import http.client
import json
import os
import re
import time
import urllib.error
import urllib.request

STREAM_ENDPOINT = 'https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent?alt=sse'


class LLMError(RuntimeError):
    pass


def load_dotenv(path=None):
    """Load simple KEY=VALUE pairs from .env without overriding existing environment variables."""
    if path is None:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(root, '.env')
    if not os.path.isfile(path):
        return
    with open(path, encoding='utf-8') as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith('#'):
                continue
            if line.startswith('export '):
                line = line[7:].strip()
            if '=' not in line:
                continue
            key, val = line.split('=', 1)
            key = key.strip()
            val = val.strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
                val = val[1:-1]
            if key and key not in os.environ:
                os.environ[key] = val


def _key():
    """GEMINI_API_KEY aus der Umgebung/.env, sonst aus gemini_key.txt im Programmordner."""
    load_dotenv()
    key = os.environ.get('GEMINI_API_KEY', '').strip()
    if not key:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        path = os.path.join(root, 'gemini_key.txt')
        if os.path.exists(path):
            key = open(path, encoding='utf-8').read().strip()
    if not key:
        raise LLMError('GEMINI_API_KEY ist nicht gesetzt (Umgebungsvariable, .env oder gemini_key.txt '
                       'im Programmordner).')
    return key


def _strip_fences(text):
    text = text.strip()
    m = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    return m.group(1) if m else text


def generate_json(prompt, model, temperature=0.3, max_output_tokens=65536, retries=4, log=print):
    """Schickt den Prompt per SSE-Stream, setzt die Text-Teile zusammen und gibt das geparste JSON-Objekt
    sowie die Token-Nutzung zurück."""
    gen_cfg = {
        'responseMimeType': 'application/json',
        'temperature': temperature,
        'maxOutputTokens': max_output_tokens,
    }
    if '3.8' in model or '2.5' in model or 'thinking' in model:
        gen_cfg['thinkingConfig'] = {'thinkingBudget': 2048}
    body = {
        'contents': [{'role': 'user', 'parts': [{'text': prompt}]}],
        'generationConfig': gen_cfg,
    }
    data = json.dumps(body).encode('utf-8')
    last = None
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(
            STREAM_ENDPOINT.format(model=model),
            data=data,
            headers={'x-goog-api-key': _key(), 'Content-Type': 'application/json'},
        )
        t0 = time.time()
        parts_text = []
        usage = {}
        finish = None
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                for raw_line in r:
                    line = raw_line.decode('utf-8', 'replace').strip()
                    if not line.startswith('data:'):
                        continue
                    payload = line[5:].strip()
                    if not payload or payload == '[DONE]':
                        continue
                    chunk = json.loads(payload)
                    if chunk.get('usageMetadata'):
                        usage = chunk['usageMetadata']
                    cands = chunk.get('candidates') or []
                    if cands:
                        if cands[0].get('finishReason'):
                            finish = cands[0]['finishReason']
                        content = cands[0].get('content') or {}
                        for p in content.get('parts') or []:
                            if 'text' in p and not p.get('thought'):
                                parts_text.append(p['text'])
        except urllib.error.HTTPError as e:
            msg = e.read().decode('utf-8', 'replace')[:400]
            last = f'HTTP {e.code}: {msg}'
            if e.code in (429, 500, 502, 503, 504) and attempt < retries:
                wait = 10 * attempt
                log(f'  Modell: {last.splitlines()[0]} – neuer Versuch in {wait} s')
                time.sleep(wait)
                continue
            raise LLMError(last)
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as e:
            last = f'Netz ({type(e).__name__}): {e}'
            if attempt < retries:
                wait = 6 * attempt
                log(f'  {last} – neuer Versuch in {wait} s (Versuch {attempt}/{retries})')
                time.sleep(wait)
                continue
            raise LLMError(last)

        text = ''.join(parts_text)
        if not text:
            last = f'Leere Antwort (Ende: {finish})'
            if attempt < retries:
                log(f'  {last} – neuer Versuch')
                time.sleep(4 * attempt)
                continue
            raise LLMError(last)

        log(f'  Modell {model}: {usage.get("promptTokenCount", "?")} Token rein, '
            f'{usage.get("candidatesTokenCount", "?")} raus, {time.time() - t0:.0f} s, Ende: {finish}')
        try:
            return json.loads(_strip_fences(text)), usage
        except json.JSONDecodeError as e:
            last = f'JSON-Fehler ({e}); Ende: {finish}'
            if attempt < retries:
                log(f'  {last} – neuer Versuch')
                continue
            raise LLMError(f'{last}\n{text[:800]}')
    raise LLMError(last or 'unbekannter Fehler')
