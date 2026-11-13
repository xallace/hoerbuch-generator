# Hörbuch-Generator (Audiobook Studio)

Turn any **YouTube video**, **web article**, **text file**, or **raw text** into a structured **CEFR-graded language-learning audiobook** (`.mp3`), a matching **Anki flashcard deck** (`.apkg`) with word + sentence audio clips, and a full **bilingual transcript & study guide** (`README_AND_TRANSCRIPT_<slug>.md`).

> **Note:** All CLI/pipeline logic, configuration, and this documentation are in English. The browser UI (`hb/web_ui.html`) currently uses German interface labels.

---

## Table of Contents

- [Features & 6-Stage Pipeline](#features--6-stage-pipeline)
- [Supported Languages & Voices](#supported-languages--voices)
- [Quick Start (Local Machine)](#quick-start-local-machine)
- [Setting Up & Keeping It Running 24/7 on Its Own Machine](#setting-up--keeping-it-running-247-on-its-own-machine)
  - [Prerequisites & Network Notes](#1-prerequisites--network-notes)
  - [Security Notice (Important Before Exposing Port 7865)](#2-security-notice-important-before-exposing-port-7865)
  - [Option A: Docker & Docker Compose (Recommended Cross-Platform)](#3-option-a-docker--docker-compose-recommended-cross-platform)
  - [Option B: Dedicated Linux Machine (`systemd`)](#4-option-b-dedicated-linux-machine-systemd)
  - [Option C: Dedicated macOS Machine (`launchd`)](#5-option-c-dedicated-macos-machine-launchd)
  - [Option D: Dedicated Windows Machine (Task Scheduler / Portable ZIP)](#6-option-d-dedicated-windows-machine-task-scheduler--portable-zip)
  - [Accessing Studio From Other Devices (LAN, Tailscale, Caddy HTTPS)](#7-accessing-studio-from-other-devices-lan-tailscale-caddy-https)
  - [Health Checks, Updates, Backups & Maintenance](#8-health-checks-updates-backups--maintenance)
- [Configuration](#configuration)
- [CLI Reference](#cli-reference)
- [Offline Tests](#offline-tests)
- [Building the Windows Portable ZIP](#building-the-windows-portable-zip)
- [Troubleshooting](#troubleshooting)
- [Usage Notice & License](#usage-notice--license)

---

## Features & 6-Stage Pipeline

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/pipeline-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="docs/pipeline-light.svg">
  <img alt="Hörbuch-Generator 6-Stage Pipeline: Input -> 1. source -> 2. script -> 3. check -> 4. audio / 5. anki / 6. readme" src="docs/pipeline-light.svg" width="840">
</picture>

1. **`source`** — Extracts full YouTube transcripts (`youtube-transcript-api`, falling back to `yt-dlp` subtitles) + video metadata via YouTube oEmbed, or cleans plain text from a webpage, local file, or direct text input.
2. **`script`** — Calls the Gemini REST API via Server-Sent Events (`:streamGenerateContent?alt=sse`) to generate a coherent graded retelling aligned to CEFR grammar rules (`A1`–`B2`), chapter structure, and target duration (`--minutes`). If `--known` is provided, previously reviewed Anki words are woven in as context anchors and excluded from new vocabulary selection.
3. **`check`** — Runs deterministic checks (word counts, CEFR disallowed grammar regexes, duplicate/missing vocabulary, stem matching including Turkish consonant softening and vowel drop) followed by a second Gemini proofreader pass. `error`-level corrections are applied automatically (unless `--no-fix`) with safeguards preventing a vocabulary card from losing its example sentence.
4. **`audio`** — Synthesizes unique words, sentences, and announcements via `edge-tts` (target language slowed to `-20%` by default, helper language at `+0%`), caches clips by `(voice, rate, text)` hash, inserts exact PCM silence pauses in Python, encodes a single 48 kHz mono MP3 via `ffmpeg`, generates a 1000×1000 cover image, and writes ID3v2.3 tags. Builds the audiobook in **four listening phases**:
   1. **Title** (helper + target title)
   2. **Vocabulary Sandwich** (`target → helper → target`)
   3. **Bilingual Story** (`target → thinking pause → helper → consolidation pause`)
   4. **100% Immersion** (full story in target language only)
5. **`anki`** — Packages a `.apkg` deck (`genanki`) with deterministic deck/note IDs, two card directions (*listen & recognize* and *active recall*), highlighted target words inside context sentences (`<span class="hl">`), grammar notes, and embedded word + sentence `.mp3` clips.
6. **`readme`** — Outputs a structured Markdown study guide with real segment timestamps, vocabulary table, full bilingual script, import hints, and check report.

**Zero-dependency Web Studio (`web.py`):** Uses Python's standard-library `http.server.ThreadingHTTPServer` with HTTP `206` byte-range streaming for instant audio seeking, live job logs, phase/sentence jump buttons (`▶`), an in-browser `script.json` & vocabulary editor, and one-click re-synthesis.

---

## Supported Languages & Voices

Any language below can serve as `--target`, `--helper`, or `--extra`:

| Code | Language | Male Voice (`edge-tts`) | Female Voice (`edge-tts`) |
|---|---|---|---|
| `tr` | Turkish | `tr-TR-AhmetNeural` | `tr-TR-EmelNeural` |
| `de` | German | `de-DE-ConradNeural` | `de-DE-KatjaNeural` |
| `ru` | Russian | `ru-RU-DmitryNeural` | `ru-RU-SvetlanaNeural` |
| `uk` | Ukrainian | `uk-UA-OstapNeural` | `uk-UA-PolinaNeural` |
| `en` | English | `en-US-GuyNeural` | `en-US-JennyNeural` |
| `fr` | French | `fr-FR-HenriNeural` | `fr-FR-DeniseNeural` |
| `es` | Spanish | `es-ES-AlvaroNeural` | `es-ES-ElviraNeural` |

Supported CEFR levels: `A1`, `A2`, `B1`, `B2`.

---

## Quick Start (Local Machine)

### Prerequisites
- **Python 3.12+** (tested on Python 3.12.10)
- **Gemini API key** from [Google AI Studio](https://aistudio.google.com/apikey)
- **`ffmpeg`** in `PATH` (automatically provided via `imageio-ffmpeg` from `requirements.txt`, or install system `ffmpeg` for best performance)

### Install & Run

```bash
git clone https://github.com/xallace/hoerbuch-generator.git
cd hoerbuch-generator

python -m venv .venv
# Linux / macOS:
source .venv/bin/activate
# Windows PowerShell:
# .venv\Scripts\Activate.ps1

pip install -r requirements.txt

cp .env.example .env
# Edit .env and set GEMINI_API_KEY=AIza...
```

Run the offline verification suite (requires no internet and no API key):

```bash
python -I tests/test_offline.py
```

Launch the **Web Studio** (opens `http://127.0.0.1:7865` in your browser):

```bash
python -I web.py
```

Or generate an audiobook directly from the **CLI**:

```bash
python -I hoerbuch.py "https://www.youtube.com/watch?v=xo-tYjGDtqw" \
  --target tr --helper en --extra de --level A1 --minutes 10
```

> **Windows Zero-Install Option:** Download `Hoerbuch-Generator_portable_<date>.zip` from [GitHub Releases](https://github.com/xallace/hoerbuch-generator/releases), extract it anywhere, place your key in `.env` or `gemini_key.txt`, and double-click `Starte_Web_UI.bat`.

---

## Setting Up & Keeping It Running 24/7 on Its Own Machine

This section explains how to deploy Hörbuch-Generator on a dedicated machine (home mini-PC, Raspberry Pi, spare laptop, Mac mini, or VPS) so the Web Studio stays online continuously, survives reboots and crashes, and serves audiobooks to your phone or desktop over your network.

### 1. Prerequisites & Network Notes

- **Minimum hardware:** Any 64-bit x86 or ARM machine with 1 GB+ RAM and 2 GB+ free disk space (`out/` stores intermediate WAV/MP3 clips per book; a 30-minute audiobook uses ~50–100 MB including cached clips).
- **Residential IP vs. Cloud VPS:** YouTube often rate-limits or blocks transcript requests from cloud/datacenter IP ranges (AWS, Hetzner, DigitalOcean). Running on a **home machine / mini-PC / Raspberry Pi** on your residential connection avoids this issue cleanly.
- **Persistent storage directories:**
  - `out/<slug>/` — intermediate JSONs, cached TTS clips, generated `.mp3`, `.apkg`, `cover.jpg`, and `README_AND_TRANSCRIPT_*.md`
  - `published/` (or your custom `HOERBUCH_PUBLISH` directory) — clean export copies triggered by `--publish` or the UI Publish button

### 2. Security Notice (Important Before Exposing Port 7865)

`web.py` is designed as a lightweight single-user studio and **does not include user authentication**. Anyone who can reach port `7865` can browse generated files and start Gemini API jobs.

- **Localhost only (safest):** Keep `--host 127.0.0.1` and access remotely via SSH tunnel or reverse proxy.
- **Home LAN only:** Bind `--host 0.0.0.0` behind your router's NAT, enable host firewall rules allowing port `7865` **only** from your local subnet (or Private network profile), and **never port-forward `7865` directly to the public internet**.
- **Remote access from anywhere:** Use **[Tailscale](https://tailscale.com/)** (zero open ports) or put **Caddy / Nginx with HTTPS + Basic Auth** in front of `127.0.0.1:7865`.

---

### 3. Option A: Docker & Docker Compose (Recommended Cross-Platform)

Works identically on Linux, Raspberry Pi (ARM64), macOS, and Windows (Docker Desktop). Includes system `ffmpeg`, DejaVu fonts for cover generation, non-root execution, log rotation, `/api/health` checks, and `restart: unless-stopped`.

```bash
git clone https://github.com/xallace/hoerbuch-generator.git
cd hoerbuch-generator

cp .env.example .env
# Edit .env: set GEMINI_API_KEY=... (and optionally HOERBUCH_KNOWN / HOERBUCH_PUBLISH)
```

Start in detached mode (auto-starts on Docker daemon boot and restarts automatically on crash):

```bash
docker compose up -d --build
```

Verify health and view live logs:

```bash
docker compose ps
curl http://127.0.0.1:7865/api/health
docker compose logs -f
```

Run a one-off CLI job inside the running container or an ephemeral container:

```bash
docker compose exec hoerbuch-studio \
  python -I hoerbuch.py "https://youtu.be/..." --target tr --helper en --level A1 --minutes 10
```

Stop or update:

```bash
git pull
docker compose up -d --build
```

---

### 4. Option B: Dedicated Linux Machine (`systemd`)

Tested layout for Ubuntu / Debian / Raspberry Pi OS using `/opt/hoerbuch-generator` and a dedicated non-privileged user.

#### Step 1 — Install system packages & create service user

```bash
sudo apt update && sudo apt install -y git python3 python3-venv ffmpeg fonts-dejavu-core
sudo useradd --system --no-create-home --home-dir /opt/hoerbuch-generator --shell /bin/bash hoerbuch
```

#### Step 2 — Clone, create virtualenv, install dependencies

```bash
sudo git clone https://github.com/xallace/hoerbuch-generator.git /opt/hoerbuch-generator
sudo chown -R hoerbuch:hoerbuch /opt/hoerbuch-generator

sudo -u hoerbuch bash -c '
  cd /opt/hoerbuch-generator
  python3 -m venv .venv
  .venv/bin/pip install --upgrade pip
  .venv/bin/pip install -r requirements.txt
  .venv/bin/python -I tests/test_offline.py
'
```

#### Step 3 — Configure `.env` with restricted permissions

```bash
cp /opt/hoerbuch-generator/.env.example /opt/hoerbuch-generator/.env
nano /opt/hoerbuch-generator/.env   # set GEMINI_API_KEY=...
chmod 600 /opt/hoerbuch-generator/.env
sudo chown -R hoerbuch:hoerbuch /opt/hoerbuch-generator
```

*(If running under your own user instead of `hoerbuch`, edit `User=` and `Group=` in `deploy/systemd/hoerbuch-studio.service`.)*

#### Step 4 — Install & enable the `systemd` service

```bash
sudo cp /opt/hoerbuch-generator/deploy/systemd/hoerbuch-studio.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now hoerbuch-studio.service
```

#### Step 5 — Verify & monitor

```bash
sudo systemctl status hoerbuch-studio.service
curl http://127.0.0.1:7865/api/health
journalctl -u hoerbuch-studio.service -f
```

If using UFW firewall on your LAN:

```bash
sudo ufw allow from 192.168.0.0/16 to any port 7865 proto tcp comment "Hoerbuch Studio LAN"
```

---

### 5. Option C: Dedicated macOS Machine (`launchd`)

Ideal for an always-on Mac mini or Mac Studio.

#### Step 1 — Install Python 3.12 & ffmpeg via Homebrew

```bash
brew install python@3.12 ffmpeg
git clone https://github.com/xallace/hoerbuch-generator.git ~/hoerbuch-generator
cd ~/hoerbuch-generator

python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -I tests/test_offline.py

cp .env.example .env
nano .env   # set GEMINI_API_KEY=...
mkdir -p logs
```

#### Step 2 — Configure & load the LaunchAgent

Edit `deploy/macos/com.hoerbuch.studio.plist` and replace `YOUR_USER` with your macOS username (`whoami`), then install it:

```bash
sed "s/YOUR_USER/$USER/g" deploy/macos/com.hoerbuch.studio.plist > ~/Library/LaunchAgents/com.hoerbuch.studio.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.hoerbuch.studio.plist
```

Verify, view logs, or restart:

```bash
curl http://127.0.0.1:7865/api/health
tail -f ~/hoerbuch-generator/logs/studio.out.log ~/hoerbuch-generator/logs/studio.err.log

# Stop / unload:
launchctl bootout gui/$(id -u)/com.hoerbuch.studio
```

> **Tip for headless Macs:** Disable automatic sleep in **System Settings → Energy** (or run `sudo pmset -a sleep 0 disksleep 0 autorestart 1`) so the machine stays reachable after power events.

---

### 6. Option D: Dedicated Windows Machine (Task Scheduler / Portable ZIP)

#### Step 1 — Set up the project (Python 3.12 or Portable Release ZIP)

Either clone the repo with Python 3.12 installed:

```powershell
git clone https://github.com/xallace/hoerbuch-generator.git C:\Services\hoerbuch-generator
cd C:\Services\hoerbuch-generator
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python -I tests\test_offline.py
Copy-Item .env.example .env
notepad .env   # set GEMINI_API_KEY=...
```

**Or** download the `Hoerbuch-Generator_portable_<date>.zip` asset from [GitHub Releases](https://github.com/xallace/hoerbuch-generator/releases), extract it to `C:\Services\hoerbuch-generator`, and place your API key in `.env` or `gemini_key.txt`.

#### Step 2 — Register persistent background auto-start via Task Scheduler

Run PowerShell (as Administrator if you want `-AtStartup` and `-OpenFirewall`):

```powershell
# Localhost only (runs at user logon, restarts automatically up to 3 times on crash):
powershell -ExecutionPolicy Bypass -File .\deploy\windows\install-task.ps1

# Dedicated LAN server (runs at Windows boot, binds 0.0.0.0:7865, opens Private firewall):
powershell -ExecutionPolicy Bypass -File .\deploy\windows\install-task.ps1 -BindHost 0.0.0.0 -AtStartup -OpenFirewall
```

To verify or remove later:

```powershell
Invoke-RestMethod http://127.0.0.1:7865/api/health
Get-ScheduledTask -TaskName HoerbuchGeneratorStudio

# Uninstall:
powershell -ExecutionPolicy Bypass -File .\deploy\windows\install-task.ps1 -Uninstall
```

> **Prevent sleep on a dedicated Windows host:** Run `powercfg /change standby-timeout-ac 0` in an elevated prompt so Windows stays online while plugged in.

---

### 7. Accessing Studio From Other Devices (LAN, Tailscale, Caddy HTTPS)

Once running with `--host 0.0.0.0 --port 7865`:

- **Local Wi-Fi / LAN:** Open `http://<machine-ip>:7865` (e.g. `http://192.168.1.42:7865`) in Safari or Chrome on your phone/tablet.
  - On **iPhone / iPad Safari:** Tap **Share → Add to Home Screen** for a full-screen Studio web app. You can download `.mp3` directly into *BookPlayer* / *Files* and tap `.apkg` to import straight into *AnkiMobile*.
- **Secure access outside your home (Tailscale):** Install [Tailscale](https://tailscale.com/) on both the host machine and your phone/laptop, then visit `http://<tailscale-machine-name>:7865` over an encrypted WireGuard tunnel without opening any router ports.
- **Public domain with HTTPS + Basic Auth (Caddy):** Bind `web.py` to `127.0.0.1:7865` and place Caddy in front:

```caddyfile
audiobooks.example.com {
    basic_auth {
        learner $2a$14$REPLACE_WITH_CADDY_HASH_PASSWORD
    }
    reverse_proxy 127.0.0.1:7865
}
```

Generate the password hash with `caddy hash-password`.

---

### 8. Health Checks, Updates, Backups & Maintenance

- **Health endpoint:** `GET /api/health` returns JSON without making external API calls:
  ```json
  {"status": "ok", "running": false, "has_api_key": true, "ffmpeg": true}
  ```
- **Updating to a new release:**
  - `systemd` / `launchd` / Windows task:
    ```bash
    git pull
    .venv/bin/pip install -r requirements.txt
    .venv/bin/python -I tests/test_offline.py
    # Then restart the service (systemctl restart hoerbuch-studio / Docker rebuild / Restart-ScheduledTask)
    ```
- **What to back up:**
  - `.env` / `gemini_key.txt` (your API key)
  - `config.local.json` (your custom paths/album settings)
  - `published/` (or only the `.mp3`, `.apkg`, and `README_AND_TRANSCRIPT_*.md` files inside `out/<slug>/`)
- **Reclaiming disk space:** Inside `out/<slug>/`, `clips/` holds cached individual `.mp3` and decoded `.wav` fragments. Once you are done editing a book, you can safely delete `out/<slug>/clips/` and `out/<slug>/anki_media/` while keeping the final `.mp3`, `.apkg`, `script.json`, and `README_AND_TRANSCRIPT_*.md`.

---

## Configuration

Settings live in [`config.json`](config.json). For machine-specific overrides that survive `git pull` and are excluded by `.gitignore`, create a **`config.local.json`** file next to `config.json` (only override keys you want to change):

```json
{
  "model": "gemini-3.8-flash",
  "album": "{target_en} {level} – Audiobooks",
  "deck_root": "{target_en}::01 Audiobooks",
  "publish_dir": "published",
  "known_path": "./known_words.apkg"
}
```

### Environment Variables

| Variable | Purpose | Default |
|---|---|---|
| `GEMINI_API_KEY` | Google Gemini API key | Required (also read from `.env` or `gemini_key.txt`) |
| `HOERBUCH_KNOWN` | Path to `.apkg` export or word list (`.txt`) of known words | `config.local.json` `known_path` or unset |
| `HOERBUCH_PUBLISH` | Destination folder for `--publish` / UI Publish button | `config.local.json` `publish_dir` or `./published` |
| `HOERBUCH_HOST` | Default bind address for `web.py` | `127.0.0.1` |
| `HOERBUCH_PORT` | Default port for `web.py` | `7865` |

---

## CLI Reference

```bash
python -I hoerbuch.py <INPUT> [options]
```

| Flag | Description | Default |
|---|---|---|
| `input` | YouTube URL, webpage URL, file path, or raw text | Required |
| `--target` | Target language (`tr`, `de`, `ru`, `uk`, `en`, `fr`, `es`) | `tr` |
| `--helper` | Helper language for translations & announcements | `en` |
| `--extra` | Optional second vocabulary translation language (e.g. `de`) | `None` |
| `--level` | CEFR level (`A1`, `A2`, `B1`, `B2`) | `A1` |
| `--minutes` | Approximate target MP3 duration in minutes | `10` |
| `--sentences` | Override planned sentence count | Auto from `--minutes` |
| `--vocab` | Override planned sandwich vocabulary count | Auto from sentences |
| `--known` | Path to `.apkg` or `.txt` word list of already reviewed words | `None` |
| `--voice-target` | Target voice gender (`m` or `f`) | `m` |
| `--voice-helper` | Helper voice gender (`m` or `f`) | `m` |
| `--steps` | Comma-separated subset of `source,script,check,audio,anki,readme` or `all` | `all` |
| `--name` | Custom output folder & filename stem under `out/` | Slugified title |
| `--publish` | Copy final MP3, `.apkg`, and README into this folder and sync album track totals | `None` |
| `--track`, `--total` | Explicit ID3 track number / total tracks | Auto-detected |
| `--no-fix` | Report proofreader fixes in `check.md` without modifying `script.json` | `False` |
| `--no-review` | Skip the LLM proofreader pass (run deterministic checks only) | `False` |
| `--model` | Override Gemini model from `config.json` | `gemini-3.8-flash` |
| `--config` | Path to alternate config JSON | `config.json` |

**Tip:** Every stage builds on files inside `out/<slug>/`. You can edit `out/<slug>/script.json` manually (or in the Web Studio) and re-render just audio, Anki, and README without calling Gemini again:

```bash
python -I hoerbuch.py "https://youtu.be/..." --name My_Book --steps audio,anki,readme
```

---

## Offline Tests

The repository includes an offline test suite covering duration planning, slug/filename sanitization, deterministic Anki IDs, CEFR pattern regexes, stem matching, WAV/MP3 assembly, cover generation, ID3 tagging, `.apkg` export/import, and the Web Studio HTTP API (zero internet or LLM calls required; requires `ffmpeg` via `imageio-ffmpeg` or system `PATH`):

```bash
python -I tests/test_offline.py
```

---

## Building the Windows Portable ZIP

On a 64-bit Windows machine, you can package a self-contained portable ZIP containing Embedded Python from `python.org`, pinned wheels from `requirements.lock`, `Starte_Web_UI.bat`, `hoerbuch.cmd`, and `test.cmd`:

```powershell
python -I build_portable.py
# Output: dist\Hoerbuch-Generator_portable_<YYMMDD>.zip
```

It never bundles `.env`, `gemini_key.txt`, `config.local.json`, `out/`, or `published/`.

---

## Troubleshooting

- **`GEMINI_API_KEY ist nicht gesetzt`:** Verify `.env` sits in the repository root (not `.env.txt` on Windows) or pass `EnvironmentFile=` in `systemd`.
- **Gemini `404` on model:** Models evolve over time. Check available models in Google AI Studio and update `"model"` in `config.local.json` or pass `--model`.
- **YouTube transcript fails (`RequestBlocked` / `IpBlocked`):** YouTube frequently blocks cloud/datacenter IP addresses. Run on a residential host or VPN, or paste the transcript text directly into a `.txt` file / Web UI input.
- **`edge-tts` timeouts or short-clip retries:** Built-in retry logic automatically re-records stub clips. If your host sits behind a strict firewall, ensure outbound WebSocket/HTTPS connections to `speech.platform.bing.com` (`443`) are allowed.
- **Port `7865` already in use:** Change `HOERBUCH_PORT=7866` in `.env` or pass `--port 7866`.

---

## Usage Notice & License

- **Software License:** Released under the [MIT License](LICENSE).
- **Third-Party Services:** Text-to-speech uses [`edge-tts`](https://github.com/rany2/edge-tts) (Microsoft's unofficial online TTS service) and transcript fetching uses YouTube subtitles via [`youtube-transcript-api`](https://github.com/jdepoix/youtube-transcript-api) / [`yt-dlp`](https://github.com/yt-dlp/yt-dlp). Intended strictly for **personal, non-commercial, and educational use**. Users are responsible for complying with the terms of service of upstream APIs and source content.
