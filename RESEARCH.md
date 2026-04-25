# RESEARCH — Kleinanzeigen-Watcher

Synthese aus drei parallelen Recherche-Subagents (OSS-Bestand, URL/HTML, Telegram).
Stand: 2026-04-25.

---

## a) Datenquelle

### Offizielle API / Feeds
- **Keine offizielle Public-API.** Die historische `kleinanzeigen-api` (eBay) ist eingestellt.
- **Kein RSS-Feed nutzbar:** `/s-feed.rss` und `/s-bestandsliste.html` sind in `robots.txt` per `Disallow:` gesperrt.
- **Sitemap** (`/sitemap_index.xml`) ist erlaubt, aber zu grob für Watcher-Zwecke (keine Filter, kein Datum auf Listing-Ebene).
- → **Wir müssen die HTML-Suchergebnisseiten (SRP) scrapen.** Diese sind nach robots.txt erlaubt.

### Bestehende OSS-Projekte (Top 5)

| Projekt | Stars | Letzter Commit | Lizenz | Bewertung |
|---|---|---|---|---|
| [okainov/ebay-kleinanzeigen](https://github.com/okainov/ebay-kleinanzeigen) | ~73 | aktiv | **keine** | Funktional am nächsten (URL-Input, 15-Min-Polling, Telegram). Lizenz-Lücke = juristisch riskant. |
| [vinc3PO/ebayKleinanzeigenAlert](https://github.com/vinc3PO/ebayKleinanzeigenAlert) | ~64 | reifend | **MIT** | Sauberste Architektur, SQLAlchemy-Persistenz, Click-CLI. Cron-Modell statt Loop. |
| [Superschnizel/Kleinanzeigen-Telegram-Bot](https://github.com/Superschnizel/Kleinanzeigen-Telegram-Bot) | ~10 | gemischt | GPL-3.0 (viral) | Regex-Filter, Telegram-Steuerung. Lizenz-Inkompatibilität. |
| [Second-Hand-Friends/kleinanzeigen-bot](https://github.com/Second-Hand-Friends/kleinanzeigen-bot) | 386 | sehr aktiv | AGPL-3.0 | **Posten** statt Watching, aber Goldgrube für Anti-Bot-Wissen (Chromium via CDP). |
| [JoeKL/KleinanzeigenTelegramBot](https://github.com/JoeKL/KleinanzeigenTelegramBot) | 1 | jung | MIT | Multi-Threading-Worker, zu unreif. |

### Empfehlung Datenquelle
**Eigenbau, mit Inspiration aus okainov + vinc3PO.** Begründung:
- okainov hat keine Lizenz (= "alle Rechte vorbehalten", rechtlich heikel zum Forken).
- vinc3PO ist MIT, aber Cron-Modell und kein Cloudflare-Plan B — der Funktionsumfang ist klein genug für einen sauberen Eigenbau in einem Tag.
- Übernehmenswert: vinc3POs SQLAlchemy-Schema als Vorlage, okainovs schlankes Polling-Modell, beide CSS-Selektor-Ansätze als Sanity-Check.

---

## b) URL-Struktur

### Schema
```
https://www.kleinanzeigen.de/s-{plz?}/{slug}/{filter-tokens?}/{page?}/k{0|catID}{l? r?}
```
Pfad-Tokens werden mit `/` getrennt, sub-Filter an Kategorie/Keyword mit `+` verkettet.
Sortierung kommt als Query-Parameter `?sortingField=SORTING_DATE`.

### Filter → URL-Mapping (empirisch verifiziert, alle HTTP 200)

| Filter | Format | Beispiel |
|---|---|---|
| Suchbegriff | Slug, Spaces → `-`, Umlaute auflösen | `office-monitor` |
| PLZ | Erstes Pfad-Segment nach `/s-` | `/s-01067/...` |
| Radius (km) | Suffix an `l1`: `r5/r10/r20/r50/r100/r200` | `k0l1r20` |
| Kategorie-ID | `c<int>` als letztes Token | `/c225` |
| Preis | `preis:min:max` (offene Grenzen leer: `preis::200`) | `/s-preis:50:200/...` |
| Zustand | `+global.zustand:new\|like_new\|ok\|alright\|defect` | `/c225+global.zustand:new` |
| Versand | `versand:ja\|nein` als Pfad-Token | `/versand:ja/k0` |
| Sortierung | Query `?sortingField=SORTING_DATE` (Default ohnehin Datum) | |
| Pagination | `/s-seite:N/...` | `/s-seite:2/office-monitor/k0` |

**Robots.txt-Konflikte:** `anbieter:privat`, `anzeige:angebote`, `anzeige:gesuche` sind per `Disallow:` gesperrt → diese Filter clientseitig nach dem Parsen anwenden, **nicht** in die URL einbauen.

### Kategorie-IDs
Format `c<int>`. Beispiele: `c0` = alle, `c161` Multimedia, `c225` PC-Zubehör. Sub-Kategorien als `c225+pc_zubehoer_software.art_s:monitore`. Auffinden via Sidebar-Parsing der Kategorieseite oder Sitemap.

### HTML-Selektoren (stabil, empirisch verifiziert)

Container: `<article class="aditem" data-adid="…" data-href="/s-anzeige/…">` — `data-adid` ist die zuverlässigste Dedup-Key.

| Feld | Selektor |
|---|---|
| Listing-Container | `article.aditem` |
| Listing-ID | `article.aditem[data-adid]` |
| Detail-URL | `article.aditem[data-href]` |
| Titel | `h2.text-module-begin a.ellipsis` (Text) |
| Preis | `p.aditem-main--middle--price-shipping--price` (Text: `"5 €"`, `"55 € VB"`, `"VB"`, `"Zu verschenken"`) |
| Beschreibung | `p.aditem-main--middle--description` |
| Ort/PLZ | `div.aditem-main--top--left` (Text nach `<i class="icon-pin-gray">`) |
| Datum | `div.aditem-main--top--right` (Text: `"Heute, 19:31"`, `"Gestern, 09:14"`, `"23.04.2026"`) |
| Bild | `div.aditem-image img[src]` |
| TopAd-Marker | `li.ad-listitem.is-topad` oder `.badge-topad` |
| PRO/Gewerblich | `div.badge-hint-pro-small-srp` |

**Defensiv:** Von `data-adid` aus traversieren statt globale CSS-Pfade. CSS-Klassen sind funktional benannt (`aditem-main--middle--price-shipping--price`) — relativ stabil, brechen aber bei Redesigns.

### Cloudflare / Bot-Schutz (aktuell)
- Default `curl` (UA `curl/8.x`): **HTTP 200, 315 KB HTML** — derzeit kein Schutz aktiv.
- Trotzdem defensiv: realistischer Desktop-UA, `Accept-Language: de-DE,de;q=0.9`, `Accept-Encoding: gzip, deflate, br`, **5–10 s Delay** zwischen Requests, leichte UA-Rotation (2–3 Strings), kein paralleles Scraping.
- Bei 403/429: Exponential Backoff (60s → 5min → 30min). `cloudscraper` als Plan B in Architektur einplanen, aber nicht ab Tag 1.
- Polling-Intervall: **5–15 min pro Suche**, nicht aggressiver.

### Robots.txt — was ist erlaubt?
- **Erlaubt:** `/s-…/k0` (Suchergebnisse), `/sitemap_index.xml`.
- **Disallow:** `/ad/`, `/VIP`, `/MVIP` (Detail-Endpoints!), `/s-feed.rss`, `/search`, alle `anbieter:*`-Filter, `anzeige:angebote/gesuche`-Filter, `+options:*`.
- **Konsequenz:** Detail-View-Abrufe meiden — die SRP-Snippets reichen für Watcher-Zwecke.
- **Kein `Crawl-delay`** explizit, also höflich-konservativ selbst setzen.

### Empfohlene Parser-Library: **selectolax**
- Lexbor-Backend: ~5–10 ms pro SRP vs. ~80–150 ms BeautifulSoup+lxml.
- Standalone (keine externen C-Deps wie lxml/libxml2 nötig).
- Saubere CSS-Selektor-API: `tree.css('article.aditem')`, `node.attributes['data-adid']`.
- BeautifulSoup als Fallback-Plan B, falls Detail-Parsing dazukommt.

---

## c) Telegram-Bot

### Setup-Anleitung
1. **Bot anlegen:** In Telegram `@BotFather` → `/newbot` → Anzeigename → Username (muss auf `bot` enden) → Token kopieren (Format `123456789:AAH…`).
2. **Eigene Chat-ID:** `@userinfobot` anschreiben (gibt numerische ID zurück) — oder dem eigenen Bot eine Nachricht schicken und einmalig `https://api.telegram.org/bot<TOKEN>/getUpdates` aufrufen, dort steht `result[0].message.chat.id`.
3. **Token + Chat-ID in `.env`:** Niemals ins Repo committen.

### Empfohlene Library: **`httpx` direkt** (kein `python-telegram-bot`)
Begründung: `python-telegram-bot` (v22, 2026) ist exzellent gepflegt, aber seit v20 zwingend `asyncio`-basiert und für Update-Handling/Bot-Frameworks ausgelegt. Wir brauchen nur zwei Outbound-Endpoints (`sendMessage`, `sendPhoto`) bei <50 Nachrichten/Tag — `httpx` direkt sind ~30 Zeilen Code, kein Event-Loop-Zwang, ein Dependency-Brocken weniger.

### Rate-Limits Bot-API
- Global: ~30 msg/sec broadcast-weit.
- Pro 1-zu-1-Chat: max. 1 msg/sec.
- Pro Gruppe: max. 20 msg/min.
- Bei Überschreitung: HTTP 429 mit `parameters.retry_after` im JSON.
- **Für unser Volume (<50/Tag): praktisch irrelevant.** Trotzdem 1s `time.sleep` zwischen Sendungen + Retry-Wrapper für 429.

### Markdown vs. HTML vs. MarkdownV2
**Empfehlung: `parse_mode="HTML"`.**
- `MarkdownV2` ist strikt (18 Sonderzeichen müssen escaped werden — Punkt im Preis `1.299 €` würde brechen).
- HTML braucht nur `&`, `<`, `>` per `html.escape()` zu escapen, URLs in `href` müssen NICHT escaped werden.
- Format: `<b>{titel}</b>\n{preis}\n<a href="{url}">Anzeige öffnen</a>`.

### Photo-Send Risiken
- 5 MB Limit bei URL-Übergabe, 10 MB bei Direkt-Upload, Caption max. 1024 Zeichen.
- Hotlink-Schutz auf `img.kleinanzeigen.de` ist aktuell unauffällig, aber Fallback (Bild-URL → Text-Nachricht mit Link) sollte im Sender eingebaut sein.

---

## d) Empfehlung: Tech-Stack

| Bereich | Wahl | Begründung |
|---|---|---|
| Sprache | Python 3.11+ | User-Vorgabe, Type-Hints/StructuralPM/`tomllib` |
| HTTP-Client | `httpx` | HTTP/2-Support, sync API, gleiche Lib für Telegram + Scraper |
| HTML-Parser | `selectolax` | 10× schneller als BeautifulSoup, einfache CSS-Selektoren, standalone |
| Persistenz | SQLite via stdlib `sqlite3` | User-Vorgabe (inspizierbar), kein ORM-Overhead bei diesem Schema |
| Konfig-Format | **YAML** (`PyYAML`) | Mehrzeilige Listen + Kommentare lesbarer als TOML; Profile sind verschachtelt (Listen + Sub-Dicts), TOML ist hier umständlicher |
| Secrets | `.env` via `python-dotenv` | Standard, einfach, systemd-`EnvironmentFile` kann dieselbe Datei lesen |
| Telegram | `httpx` direkt gegen Bot-API | s.o. |
| Logging | stdlib `logging` + `RotatingFileHandler` | Keine externe Lib nötig |
| Scheduler | Eigene Mainloop mit `time.sleep` + Pro-Profil-`next_run`-Zeitstempel | `apscheduler` wäre Overkill für unsere Anforderungen |
| Tests | `pytest` + HTML-Fixtures (echte Captures) | User-Vorgabe |
| Service | systemd unit (User-Service oder System-Service) | User-Vorgabe |

### Daten-Fluss
```
config.yaml ──► Config-Loader ──► Profile-Liste
                                       │
                       ┌───────────────┴───────────────┐
                       ▼                               ▼
                 [pro Profil im Loop]
                       │
       Fetcher (httpx, UA-Rotation, Backoff)
                       │
                       ▼
                Parser (selectolax → Listing-Objekte)
                       │
                       ▼
              Storage (SQLite: SELECT existing, INSERT new)
                       │
                  [neue IDs]
                       ▼
              Notifier (httpx → Telegram, Rate-limited)
```

### SQLite-Schema (Vorschlag)
```sql
CREATE TABLE seen_listings (
    id TEXT PRIMARY KEY,           -- data-adid
    profile TEXT NOT NULL,         -- Name aus config.yaml
    first_seen_at TIMESTAMP NOT NULL,
    title TEXT,
    price TEXT,
    url TEXT
);
CREATE INDEX idx_profile ON seen_listings(profile);
```

### Risiken (priorisiert)
1. **Cloudflare kann jederzeit aktiviert werden** — heute kein Schutz, aber kein Verlass darauf. Plan B: `cloudscraper` oder Headless-Browser (Playwright) als Fallback-Modul vorsehen.
2. **CSS-Selektor-Drift** bei Redesigns — defensiv von `data-adid` aus traversieren, Tests mit Fixtures fangen Regressions.
3. **Datums-Parsing** ("Heute"/"Gestern"/`23.04.2026`) — explizite Zeitzone Berlin, Race-Condition um Mitternacht beachten.
4. **TopAds & PRO-Inserate** — sonst wiederholt sich derselbe Sponsoring-TopAd in jedem Polling. Filter konfigurierbar pro Profil machen.
5. **Robots.txt-Filter** (`anbieter:privat`, `anzeige:angebote`) — clientseitig anwenden, nicht via URL.
