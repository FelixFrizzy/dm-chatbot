# dm-rechnungen

Kleine Pipeline, die aus dm-Kassenbons/-Rechnungen eine durchsuchbare
Kaufhistorie macht und einen Chat-Assistenten anbietet, der auf Basis dieser
Historie sagt, was mal wieder fällig ist ("Wann habe ich zuletzt Kaffee
gekauft?", "Was sollte ich nachbestellen?").

## Ablauf

```
1. Login (Playwright)         node dm-login.js
        │  speichert Session lokal als dm-auth.json
        ▼
2. Bulk-Download (Playwright)  npx playwright test dm-download.spec.js
        │  lädt alle Belege als PDF nach downloads/
        ▼
3. PDF → CSV (Python)          python3 dm_pdfs_zu_csv.py
        │  extrahiert Produktname, Preis, Menge, Datum nach dm_artikel.csv
        ▼
4. Chat-Assistent (Python)     python3 chat.py
           nutzt Claude (Tool-Calling) über die aggregierte Kaufhistorie
```

Schritt 1–3 laufen einmalig bzw. bei Bedarf erneut (Download ist
idempotent, bereits geladene PDFs werden übersprungen). Schritt 4 ist der
eigentliche Chat.

## Setup

### 1. Login & Download (Node.js / Playwright)

```bash
npm install
npx playwright install chrome
```

**Anleitung zum Einloggen:**

1. `node dm-login.js` starten. Es öffnet sich ein sichtbares Chrome-Fenster.
2. Im Browser mit dem **eigenen** dm.de-Konto vollständig einloggen und
   danach "Meine Einkäufe" öffnen.
3. Zurück im Terminal Enter drücken. Das Skript speichert die eingeloggte
   Session automatisch:
   - `dm-browserprofil/` – vollständiges Chrome-Profil (für erneute Logins)
   - `dm-auth.json` – Playwright-Session (Cookies/LocalStorage), wird vom
     Download-Skript verwendet

   Beide Dateien enthalten eine gültige, angemeldete Session und sind über
   `.gitignore` von Git ausgeschlossen – sie sollten **nie** committet oder
   geteilt werden.
4. Belege herunterladen:
   ```bash
   npx playwright test dm-download.spec.js
   ```
   Lädt alle Kassenbons/Rechnungen als PDF nach `downloads/`. Läuft der
   Download später erneut, werden nur neue Belege nachgeladen.

Es werden zu keinem Zeitpunkt Zugangsdaten im Code oder in einer Datei
hinterlegt – der Login passiert manuell im echten Browser, automatisiert wird
nur das anschließende Session-Handling.

### 2. PDF → CSV (Python)

```bash
python3 -m venv venv && source venv/bin/activate   # optional, empfohlen
pip install -r requirements.txt
python3 dm_pdfs_zu_csv.py
```

Erzeugt `dm_artikel.csv` (Produktname, Einzelpreis, Menge, Datum) sowie
`dm_nicht_erkannt.csv` für Belege, die nicht geparst werden konnten.

### 3. Chat-Assistent

Benötigt einen eigenen Anthropic API-Key (nicht identisch mit einem
Claude-Abo): Konto auf [console.anthropic.com](https://console.anthropic.com)
anlegen, etwas Guthaben aufladen und einen Key erstellen. Mit dem genutzten
Modell (Claude Haiku) kostet eine Chat-Session realistisch Bruchteile eines
Cents bis wenige Cent.

```bash
cp .env.example .env    # ANTHROPIC_API_KEY eintragen
python3 chat.py
```

Ohne eigene dm-Kaufhistorie lässt sich der Assistent auch direkt mit
Beispieldaten ausprobieren:

```bash
python3 chat.py --csv example_data/dm_artikel_beispiel.csv
```

Beispiel-Dialog:

```
Du> Was sollte ich mal wieder kaufen?
Assistent> Laut deiner Kaufhistorie sind u. a. diese Produkte überfällig:
  - Denkmit Vollwaschmittel Pulver, 20 WL (zuletzt vor 90 Tagen, sonst alle ~40 Tage)
  - dmBio Kaffee gemahlen, 500 g (zuletzt vor 70 Tagen, sonst alle ~30 Tage)
  ...
```

Der Assistent ist ein **Tool-Calling-Agent**: Claude bekommt keine fertige
Zusammenfassung vorgesetzt, sondern ruft bei Bedarf Python-Funktionen auf
(`list_overdue_products`, `get_product_history`, `list_recent_purchases`),
die live auf `dm_artikel.csv` rechnen. Die Logik zur Auswertung der
Kaufhistorie (Kaufintervalle, "überfällig seit X Tagen" usw.) steckt in
[`purchase_data.py`](purchase_data.py) und lässt sich auch ohne Chat direkt
ausführen: `python3 purchase_data.py`.

## Datenschutz

Alles Personenbezogene bleibt lokal und ist über `.gitignore` ausgeschlossen:
`downloads/`, `dm-auth.json`, `dm-browserprofil/`, `dm-chrome-profile/`,
`dm_artikel.csv`, `dm_nicht_erkannt.csv`, `.env`. Im Repository liegen nur
Code und die frei erfundene Beispieldatei `example_data/dm_artikel_beispiel.csv`.

## Bekannte Grenzen

- Produkte werden über exakten Namensabgleich zusammengeführt. Leicht
  abweichende Bezeichnungen oder Packungsgrößen (z. B. durch Sortiment- oder
  Rezeptänderungen) werden aktuell als unterschiedliche Produkte gezählt.
- Nicht jeder Beleg lässt sich zuverlässig parsen; nicht erkannte PDFs landen
  in `dm_nicht_erkannt.csv` und im Ordner `extraction-debug/`.
