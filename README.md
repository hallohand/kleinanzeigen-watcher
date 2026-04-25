# Kleinanzeigen-Watcher

Pollt Kleinanzeigen.de in konfigurierbaren Intervallen auf neue Inserate
und benachrichtigt per Telegram-Bot — mehrere Suchprofile parallel,
Bootstrap-Modus beim ersten Lauf (kein Spam mit Bestand), höflicher
Fetcher mit UA-Rotation, robots.txt-Beachtung und Backoff.

## Was es macht

Pro Profil:

1. Baut die Such-URL aus deinen Filtern (Begriff, PLZ + Radius, Preis,
   Versand, Zustand, Kategorie).
2. Holt die Such-Ergebnisseite (SRP) mit `httpx`, ehrt
   `robots.txt`, achtet auf Mindest-Delay und retry-baren Status-Codes.
3. Parst Inserate mit `selectolax` (Titel, Preis, Ort, Entfernung,
   Datum, Bild, TopAd-/PRO-Marker).
4. Filtert gegen die SQLite-DB (`seen_listings`) — nur wirklich neue IDs
   gehen weiter.
5. Schickt für jedes neue Inserat eine Telegram-Nachricht
   (`sendPhoto` mit Vorschau, Fallback auf `sendMessage` wenn das Bild
   nicht ladbar ist).

Beim ersten Polling-Lauf eines Profils werden alle aktuellen Treffer
nur als „gesehen" markiert — keine Notifications, kein Spam.

## Architektur (sehr kurz)

```
config.yaml ──► load_config() ──► Profile-Liste
                                       │
                       ┌───────────────┴───────────────┐
                       ▼                               ▼
              build_search_url()                  Scheduler
                       ▼                          (next_run pro Profil)
                  Fetcher (httpx)
                       ▼
                Parser (selectolax → Listing)
                       ▼
                Storage (SQLite filter_new + mark_seen)
                       ▼
              Notifier (httpx → Telegram)
```

| Datei | Verantwortung |
|---|---|
| `url_builder.py` | Such-URL aus Filtern bauen |
| `fetcher.py` | HTTP-Requests, robots.txt, Retry/Backoff |
| `parser.py` | HTML → `Listing`-Dataclass |
| `storage.py` | SQLite, `(id, profile)` als Composite-PK |
| `notifier.py` | Telegram Bot API, HTML-Format, Photo→Text-Fallback |
| `scheduler.py` | Poll-Loop, First-Run-Bootstrap, SIGTERM-Handling |
| `config.py` | YAML-Loader + Validierung |
| `cli.py` | `test`- und `run`-Subkommandos |
| `logging_setup.py` | StreamHandler + optional RotatingFileHandler |

## Cloud-Deployment (kostenlos via GitHub Actions)

Dieses Repo läuft in Produktion auf GitHub Actions (free tier, public repo).
Zwei Workflows:

| Workflow | Trigger | Was er tut |
|---|---|---|
| `.github/workflows/poll.yml` | alle 10 Min (cron) + manuell | `run --once`, persistiert die SQLite-DB als git commit zurück |
| `.github/workflows/digest.yml` | täglich 07:00 UTC (= 09:00 CEST sommers, 08:00 CET winters) | `top5 --telegram` — schickt die aktuellen Top-Empfehlungen |

**Secrets** im Repo (`Settings → Secrets and variables → Actions`):
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `ANTHROPIC_API_KEY`

**Manuell triggern:**
```bash
gh workflow run poll.yml
gh workflow run digest.yml
gh run list --limit 5     # letzte runs anschauen
```

**Lokales Setup (alternativ, für Entwicklung)** — siehe nächster Abschnitt.

## Schnellstart

```bash
# Voraussetzung: Python 3.11+, ggf. python3-venv (sonst siehe SETUP.md).
git clone <repo-url> ~/Claude/kleinanzeigen && cd ~/Claude/kleinanzeigen
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'

cp .env.example .env                # TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID eintragen
cp config.example.yaml config.yaml  # Profile bearbeiten

# Standalone-Test (kein Telegram, keine DB):
.venv/bin/python -m kleinanzeigen_watcher test \
    --query "office monitor" --plz 01067 --radius 20

# Bootstrap (alle Treffer als gesehen markieren, keine Nachrichten):
.venv/bin/python -m kleinanzeigen_watcher run --config config.yaml --bootstrap

# Hauptbetrieb (Loop):
.venv/bin/python -m kleinanzeigen_watcher run --config config.yaml
```

Vollständige Setup-Anleitung inkl. systemd-User-Service: **`SETUP.md`**.

## Konfiguration

`config.yaml` (Beispiel in `config.example.yaml`):

```yaml
defaults:
  poll_interval_minutes: 10
  request_delay_seconds: 5
  user_agents:
    - "Mozilla/5.0 ..."
profiles:
  - name: office-monitor-dresden
    enabled: true
    query: office monitor
    plz: "01067"
    radius_km: 20
    price_min: 50
    price_max: 200
    shipping: any        # ja | nein | any
    poll_interval_minutes: 10
    # optional:
    # category_id: 225
    # condition: new     # new | like_new | ok | alright | defect
    # include_topads: false
    # include_pro: true
```

Secrets stehen ausschließlich in `.env` (nicht committen).

## Tests

```bash
.venv/bin/pytest        # 94 Tests, ~8 s, alles offline gegen Fixtures
```

Fixtures unter `tests/fixtures/` sind echte Capture-HTMLs der Such-Seite
— keine Tests benötigen Netzwerkzugriff.

## Hintergrund

Detaillierte Recherche zu Datenquelle, URL-Struktur, HTML-Selektoren,
Cloudflare-Status und Library-Wahl: **`RESEARCH.md`**.

## Lizenz

MIT. Keine offizielle Verbindung zu Kleinanzeigen.de — privates
Watcher-Tool. Bitte respektiere `robots.txt` und sei kein höflicherer
Crawler-Bot als Google. Default-Polling-Intervall ist 10 Min. pro
Profil; aggressiver zu werden lohnt sich nicht und verärgert nur den
Server.
