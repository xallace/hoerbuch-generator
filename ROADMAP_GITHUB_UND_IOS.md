# Fahrplan: GitHub-Veröffentlichung & iPhone-App (Stufe 3)

> **Stand:** 09.11.2026  
> **Aktueller Status:** Stufe 1 (CLI + Portable ZIP) und Stufe 2 (Lokale Web-Oberfläche `web.py` / `hb/web_ui.html`) sind fertiggestellt, getestet (`tests/test_offline.py` grün) und an einem 30-Minuten-Langlauf (`29:03 Min.`) verifiziert.

---

## Teil A: Veröffentlichung des bisherigen Codes auf GitHub (Open-Source-Release)

Bevor das Repository öffentlich auf GitHub gepusht wird, führen wir in der nächsten Sitzung ein kurzes **Privacy-, Lizenz- & Packaging-Cleanup** durch (Dauer: ca. 15–20 Minuten):

### 1. Datenschutz & Pfad-Neutralisierung (Checkliste)
- [x] **`.gitignore` angelegt:** Schützt `gemini_key.txt`, `.env`, `config.local.json`, `out/`, `dist/`, `published/` und `__pycache__/` vor versehentlichen Commits.
- [x] **Persönliche Referenzen neutralisiert:**
  - `README.md` auf vollständige englische Setup-, CLI-, Web-Studio- und 24/7-Betriebsdokumentation umgestellt.
  - `web.py` & `config.json`: Standardpfade (`publish_dir`, `known_path`) generisch über `config.json`, `config.local.json` und Umgebungsvariablen (`HOERBUCH_PUBLISH`, `HOERBUCH_KNOWN`) konfigurierbar gemacht.
  - `build_portable.py` und `tests/test_offline.py`: Auf eine rechtefreie synthetische Test-Fixture (`tests/fixtures/sample_turkish_a1.json`) und synthetische `.apkg`-Tests umgestellt.
- [x] **`LICENSE` hinzugefügt:** MIT-Lizenz im Hauptverzeichnis angelegt; Hinweise zu `edge-tts` und YouTube-Untertiteln in `README.md`.

### 2. GitHub-Repository & Release-Paket
- [x] **Umfassende `README.md` + Deployment-Vorlagen (`Dockerfile`, `docker-compose.yml`, `deploy/`):**
  - Architektur-Diagramm der 6-stufigen Pipeline (`source` → `script` → `check` → `audio` → `anki` → `readme`).
  - Detaillierte Anleitung für lokale Nutzung sowie Dauerbetrieb auf einem eigenen Rechner (Docker, Linux `systemd`, macOS `launchd`, Windows Task Scheduler).
- [x] **GitHub Release (`v1.0.0`):**
  - Das mit `python -I build_portable.py` erzeugte Paket `dist/Hoerbuch-Generator_portable_<YYMMDD>.zip` wird als **Release-Asset** unter *GitHub Releases* bereitgestellt (Zero-Install-Download für Windows-Nutzer).

---

## Teil B: Entwicklungsplan für die iPhone-App (Stufe 3 – iOS / SwiftUI)

Ziel ist eine native, App-Store-taugliche iOS-App (**Arbeitstitel:** *LingoCast* / *Hörbuch Studio*), die ohne Python-Server direkt auf dem iPhone läuft.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/ios-architecture-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="docs/ios-architecture-light.svg">
  <img alt="iOS SwiftUI App Architecture: Share Sheet -> SwiftUI App -> LLM Engine -> Local Validation -> Audio Engine -> 4-Phase Player + .apkg Export" src="docs/ios-architecture-light.svg" width="840">
</picture>

### Phase 1: Lokaler Mobile-Modus im Heimnetz (Sofort nutzbar – 0 Aufwand)
Schon vor dem Bau der Swift-App kann `web.py` mit `--host 0.0.0.0` gestartet werden:
- Auf dem iPhone in Safari `http://<PC-IP>:7865` öffnen → *„Teilen ➔ Zum Home-Bildschirm“*.
- Volle Bedienung vom Sofa aus, direkter Download von `.mp3` (für *BookPlayer* / *MP3 Books*) und `.apkg` (1-Tap-Import in *AnkiMobile*).

### Phase 2: Native SwiftUI-Kern-App (Session 1 auf dem Mac / Xcode)
1. **Datenmodell & Pipeline in Swift (`Codable`):**
   - Exakte Übernahme des bewährten `script.json`-Schemas (`title_target`, `title_helper`, `vocab`, `chapters`, `sentences`).
   - Portierung der Sprachregeln (`languages.py`) und der deterministischen Prüfung (`check.py`: Wortzahl, CEFR-Verbotene-Suffixe, Wortstamm-Matching inkl. türkischer Konsonantenerweichung) nach Swift.
2. **Quellen-Extraktor (`SourceService.swift`):**
   - Abruf von YouTube-Untertiteln und oEmbed-Metadaten direkt vom iPhone (vorteilhaft, da YouTube private Mobilfunk-/Heimnetz-IPs nicht wie Rechenzentrums-IPs blockiert).
   - Artikel-Extraktion über `URLSession` + HTML-Bereinigung.
3. **LLM-Anbindung (`LLMService.swift`):**
   - **Modus A (BYOK / Cloud):** Direkter SSE-Streaming-Aufruf an `gemini-3.8-flash` (API-Key sicher im iOS Keychain gespeichert; Kosten < 0,1 Cent pro Hörbuch).
   - **Modus B (100 % On-Device & kostenlos ab iOS 26):** Anbindung von Apples `FoundationModels`-Framework für lokale Generierung auf der Neural Engine.

### Phase 3: Dynamische Audio-Engine & Karaoke-Player (Session 2)
Statt eine starre 30-Minuten-MP3 vorab zusammenzuschneiden, nutzt die iPhone-App eine **intelligente Segment-Queue**:
1. **Zweistufige Sprachsynthese (`TTSService.swift`):**
   - **Offline-Standard (0 € Kosten, App-Store-konform):** `AVSpeechSynthesizer.write(_:toBufferCallback:)` rendert die Sätze mit den installierten iOS Enhanced/Premium-Stimmen (z. B. *Yelda* / *Cem* für Türkisch, *Samantha* / *Ava* für Englisch, *Anna* / *Petra* für Deutsch) als lokale `.m4a`-Clips.
   - **Optionales Pro-Backend:** Offizielle Cloud-TTS-Schnittstelle (OpenAI TTS / Azure Cognitive Services / Google Cloud TTS).
2. **Interaktiver 4-Phasen-Player (`PlayerView.swift`):**
   - Spielt die Phasen (*Titel* ➔ *Vokabel-Sandwich* ➔ *Zweisprachige Geschichte* ➔ *100 % Immersion*) nahtlos ab, inklusive Lockscreen-Steuerung (`MPNowPlayingInfoCenter`).
   - **Killer-Feature gegenüber statischen MP3s:** Die **Denkpause** (`1,0 s` bis `5,0 s`) und das **Sprechtempo** (`70 %` bis `100 %`) lassen sich **während des Hörens live per Slider** verstellen!
   - Optionaler **M4B/MP3-Dateiexport** (`AVAssetExportSession`) für externe Hörbuch-Player.

### Phase 4: Nativer Anki-Export (`.apkg`) & Share-Extension (Session 3)
1. **Nativer `.apkg`-Generator in Swift (`AnkiExporter.swift`):**
   - Eine `.apkg`-Datei ist technisch eine SQLite3-Datenbank (`collection.anki2`) plus `media`-JSON und Audio-Clips in einem ZIP-Archiv.
   - Da iOS `SQLite3` und `Compression` von Haus aus mitbringt, erzeugt die App das fertige Anki-Deck in unter 1 Sekunde komplett offline und übergibt es per `UIActivityViewController` direkt an **AnkiMobile**.
   - Zusätzlich: **Anki-Import (`.apkg` lesen)** auf dem iPhone, um wie am PC den bereits bekannten Wortschatz (`known_words`) als Anker in den Prompt einzuspeisen.
2. **iOS Share Sheet Extension:**
   - Direkt aus der YouTube-App auf *Teilen ➔ „Lern-Hörbuch“* tippen, um die URL ohne Copy & Paste an die App zu übergeben.
