# Setup — Kleinanzeigen-Watcher

Pragmatische Schritt-fuer-Schritt-Anleitung fuer Pop!\_OS / Linux Mint XFCE
(oder jede andere Linux-Desktop-Distribution mit systemd).

---

## Voraussetzungen

- **Python 3.11+** (`python3 --version` pruefen).
- **git**.
- **sudo-Rechte** — nur einmalig fuer `apt install python3-venv`,
  falls du den Standard-Venv-Weg gehst. Den Workaround ohne sudo gibt es im
  naechsten Schritt.
- **Telegram-Account** (Mobile oder Desktop) — fuer den BotFather-Dialog
  und zum Empfangen der Benachrichtigungen.

---

## 1. Telegram-Bot anlegen

1. In Telegram nach **`@BotFather`** suchen, Chat oeffnen, `/newbot`
   senden.
2. Anzeigename eingeben (frei waehlbar, z. B. `Kleinanzeigen Watcher`).
3. Username eingeben — muss auf `bot` enden, z. B.
   `kleinanzeigen_jonas_bot`. Username muss global eindeutig sein.
4. BotFather antwortet mit dem Token im Format `123456789:AAH-...`.
   **Kopieren und sicher ablegen** — Token = Vollzugriff auf den Bot.

### Eigene Chat-ID herausfinden

**Variante A (einfach):** In Telegram **`@userinfobot`** anschreiben
(`/start` reicht). Antwortet mit der numerischen User-ID — das ist die
Chat-ID fuer 1:1-Nachrichten.

**Variante B (ohne Drittbot):**
1. Eigenem Bot eine beliebige Nachricht schicken (z. B. `hi`).
2. Im Browser aufrufen:
   `https://api.telegram.org/bot<TOKEN>/getUpdates`
3. Im JSON-Response: `result[0].message.chat.id` ist die Chat-ID.

---

## 2. Repo + Venv aufsetzen

```bash
git clone <repo-url> ~/Claude/kleinanzeigen
cd ~/Claude/kleinanzeigen
```

**Standard-Weg (empfohlen):**
```bash
sudo apt install python3-venv     # einmalig, falls noch nicht da
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e '.[dev]'
```

> **Workaround ohne `python3-venv`-Paket** (sudo nicht moeglich oder
> nicht gewollt):
> ```bash
> python3 -m venv --without-pip .venv
> curl -sS https://bootstrap.pypa.io/get-pip.py | .venv/bin/python
> .venv/bin/pip install -e '.[dev]'
> ```
> Damit ist das Venv funktional aequivalent zu einem `python3-venv`-Setup.

Verifikation:
```bash
.venv/bin/python -c "import kleinanzeigen_watcher; print('ok')"
```

---

## 3. Konfiguration

```bash
cp .env.example .env
cp config.example.yaml config.yaml
```

**`.env`** — Token und Chat-ID eintragen:
```
TELEGRAM_BOT_TOKEN=123456789:AAH-dein-echter-token
TELEGRAM_CHAT_ID=987654321
```
> `.env` steht in `.gitignore`. Nicht committen.

**`config.yaml`** — Profile bearbeiten. Jedes Profil kennt mindestens
`name`, `query` und `enabled`. Optional: `plz`, `radius_km`,
`price_min`/`price_max`, `shipping`, `poll_interval_minutes`. Siehe
`config.example.yaml` fuer eine annotierte Vorlage.

---

## 4. Test-Lauf (manuell, kein Service)

```bash
.venv/bin/python -m kleinanzeigen_watcher test \
    --query "office monitor" --plz 01067 --radius 20
```

Der `test`-Befehl:
- baut die SRP-URL aus den Argumenten,
- macht **einen** HTTP-Request gegen kleinanzeigen.de,
- parst die Treffer mit `selectolax`,
- gibt die ersten ~25 Listings als Tabelle auf stdout aus,
- **schreibt nichts** in die SQLite-DB und sendet **keine** Telegram-
  Nachricht.

Erwartetes Verhalten: ein paar Sekunden Latenz, dann eine Liste mit
ID, Titel, Preis und URL. Bei 403/429 sieht man die Cloudflare-Antwort
direkt im Log — dann Backoff in `config.yaml` erhoehen oder UA rotieren.

---

## 5. Systemd-User-Service installieren

User-Service heisst: laeuft unter dem eigenen Account, kein root,
Logs gehen in das User-Journal.

```bash
mkdir -p ~/.config/systemd/user
cp systemd/kleinanzeigen-watcher.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now kleinanzeigen-watcher
```

**Wichtig — `enable-linger`:**
```bash
loginctl enable-linger "$USER"
```
Ohne Linger beendet systemd alle User-Services beim Logout aus der
GUI-Session. Mit Linger laeuft der User-Manager unabhaengig von einer
aktiven Session weiter — der Watcher bleibt also auch laufen, wenn du
dich abmeldest oder den Rechner ueber Auto-Login neu startest, ohne
dich einzuloggen.

Live mitlesen:
```bash
journalctl --user -u kleinanzeigen-watcher -f
```

Status:
```bash
systemctl --user status kleinanzeigen-watcher
```

---

## 6. Operations

### Profil pausieren / aktivieren

`config.yaml` editieren, `enabled: false` setzen, Service neu laden:
```bash
systemctl --user reload-or-restart kleinanzeigen-watcher
```

### Logs ansehen

```bash
journalctl --user -u kleinanzeigen-watcher --since "1 hour ago"
journalctl --user -u kleinanzeigen-watcher -f                  # follow
journalctl --user -u kleinanzeigen-watcher -p warning          # nur >= warn
```

### SQLite-DB inspizieren

```bash
cd ~/Claude/kleinanzeigen
sqlite3 kleinanzeigen.db 'SELECT * FROM seen_listings ORDER BY first_seen_at DESC LIMIT 20;'
sqlite3 kleinanzeigen.db 'SELECT profile, COUNT(*) FROM seen_listings GROUP BY profile;'
```

### Service deaktivieren / entfernen

```bash
systemctl --user disable --now kleinanzeigen-watcher
rm ~/.config/systemd/user/kleinanzeigen-watcher.service
systemctl --user daemon-reload
# optional Linger zurueckdrehen, wenn keine anderen User-Services laufen:
loginctl disable-linger "$USER"
```

### Komplett zuruecksetzen (Dedup-Historie loeschen)

```bash
systemctl --user stop kleinanzeigen-watcher
rm ~/Claude/kleinanzeigen/kleinanzeigen.db
systemctl --user start kleinanzeigen-watcher
```
> Achtung: beim ersten Lauf nach dem Reset werden **alle** aktuell
> sichtbaren Listings als "neu" eingestuft und gemeldet. Profile vorher
> auf `enabled: false` setzen, falls das nicht gewuenscht ist.

---

## 7. Fehlersuche

### Service startet nicht

```bash
systemctl --user status kleinanzeigen-watcher
journalctl --user -u kleinanzeigen-watcher -n 50 --no-pager
```
Typische Ursachen:
- `EnvironmentFile=...` zeigt auf nicht existierende `.env` → Datei
  anlegen (Schritt 3).
- Pfad zum venv-Python falsch → `.venv/bin/python --version` pruefen,
  ggf. Pfad in der Unit anpassen.
- `ProtectSystem=strict` blockiert Schreibzugriff → `ReadWritePaths`
  muss das Repo enthalten (ist in der mitgelieferten Unit der Fall).

### Keine Telegram-Nachrichten

1. Token + Chat-ID manuell testen:
   ```bash
   curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        -d chat_id="${TELEGRAM_CHAT_ID}" -d text="ping"
   ```
   `"ok": true` im Response = alles korrekt. `401` = Token falsch,
   `400 chat not found` = Chat-ID falsch (oder Bot wurde noch nie
   angeschrieben — dem Bot einmal `/start` senden).
2. Im Journal nach `Notifier`/`Telegram`-Eintraegen suchen.
3. Variablen tatsaechlich gesetzt?
   ```bash
   systemctl --user show kleinanzeigen-watcher -p Environment
   ```

### Cloudflare 403 / 429

- Im Journal nach `403` oder `429` suchen.
- In `config.yaml` `request_delay_seconds` erhoehen (10–15 s),
  `poll_interval_minutes` ebenfalls hoch (15–30 min).
- UA-Liste in `defaults.user_agents` erweitern bzw. aktualisieren —
  alte UA-Strings (Firefox 100 etc.) sind verdaechtig.
- Bei dauerhaftem 403: `cloudscraper` als Plan B aktivieren (siehe
  `RESEARCH.md`, Abschnitt a / d).

### "Heute"/"Gestern" werden falsch geparst

Zeitzone des Hosts pruefen:
```bash
timedatectl
```
Sollte `Europe/Berlin` sein. Sonst entweder System-TZ setzen oder
in `config.yaml` explizit `timezone: Europe/Berlin` ergaenzen.

### Venv neu bauen (Dependencies kaputt)

```bash
systemctl --user stop kleinanzeigen-watcher
rm -rf .venv
python3 -m venv .venv      # oder Workaround aus Schritt 2
.venv/bin/pip install -e '.[dev]'
systemctl --user start kleinanzeigen-watcher
```
