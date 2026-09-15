#!/usr/bin/env python3
"""
Extrahiert Produktname, Einzelpreis, Menge und Kaufdatum aus dm-Kassenbons
und dm-Rechnungen (PDF) und schreibt sie in eine CSV-Datei.

Es werden zwei PDF-Layouts erkannt:
  1. Kassenbon (Kassenzettel aus der Filiale, Thermodrucker-Layout)
  2. Rechnung (Online-Bestellung, Tabellen-Layout mit
     "Artikelbezeichnung / Einzelpreis / Menge / Gesamtpreis")

Alles, was kein Artikel ist (Telefonnummern, Kundennummern, MwSt-Tabellen,
Rabatte/Coupons, PAYBACK-Infos, Fußzeilen usw.), wird ignoriert.

Eingabe:
    ./downloads/**/*.pdf

Ausgabe:
    ./dm_artikel.csv           -> Produktname; Einzelpreis; Menge; Datum
    ./dm_nicht_erkannt.csv     -> PDFs, bei denen nichts extrahiert werden konnte
    ./extraction-debug/*.txt   -> Rohtext zur Fehlersuche (nur bei Problemen)

Installation:
    python3 -m pip install pymupdf

Start:
    python3 dm_pdfs_zu_csv.py
"""

from __future__ import annotations

import csv
import re
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    import pymupdf
except ImportError:
    print(
        "PyMuPDF fehlt.\n"
        "Installiere es mit:\n"
        "  python3 -m pip install pymupdf",
        file=sys.stderr,
    )
    raise SystemExit(1)


PDF_DIR = Path("downloads")
OUTPUT_CSV = Path("dm_artikel.csv")
UNRECOGNIZED_CSV = Path("dm_nicht_erkannt.csv")
DEBUG_DIR = Path("extraction-debug")


@dataclass(frozen=True)
class Item:
    name: str
    unit_price: str      # Einzelpreis, deutsches Format (Komma), z.B. "1,45"
    quantity: str         # Menge, z.B. "2"
    date: str              # Kaufdatum, Format TT.MM.JJJJ


# --------------------------------------------------------------------------
# Hilfsfunktionen
# --------------------------------------------------------------------------

def normalize_space(value: object) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def clean_name(value: str) -> str:
    text = normalize_space(value)
    # Vereinzelte Kommas/Bindestriche am Rand entfernen, die durch den
    # Zeilenumbruch im Original entstehen (z.B. "... 23 g , Bio").
    text = re.sub(r"\s+,\s+", ", ", text)
    text = text.strip(" ,-")
    return text


# --------------------------------------------------------------------------
# PDF-Text lesen
# --------------------------------------------------------------------------

def read_pdf_pages(pdf_path: Path) -> list[str]:
    with pymupdf.open(pdf_path) as document:
        return [page.get_text("text", sort=True) for page in document]


# --------------------------------------------------------------------------
# Kassenbon-Layout (Filialkauf, Thermodrucker)
# --------------------------------------------------------------------------

KASSENBON_DATE_RE = re.compile(r"^(\d{2}\.\d{2}\.\d{4})\s+\d{2}:\d{2}\b")
KASSENBON_STOP_WORDS = ("summe", "zwischensumme")

# Menge mit "x" am Zeilenanfang, z.B. "2x 0,95 dmBio Kids Meerestiere 1,90 2"
QTY_TOKEN_RE = re.compile(r"^\d+[x×]$", re.IGNORECASE)
# Preis-Token, z.B. "1,90" oder "-14,70"
PRICE_TOKEN_RE = re.compile(r"^-?\d{1,4}[.,]\d{2}$")
# MwSt-Klassen-Token am Zeilenende, z.B. "2", "§1"
TAXCLASS_TOKEN_RE = re.compile(r"^§?\d{1,2}$")


def parse_kassenbon_line(line: str) -> Item | None | tuple[None, None]:
    """Versucht, eine Kassenbon-Zeile als Artikel zu erkennen.

    Rückgabe: (name, unit_price, quantity) oder None, falls keine Artikelzeile.
    """
    tokens = line.split()
    if len(tokens) < 3:
        return None

    # Die letzten zwei Tokens muessen "Gesamtpreis" + "MwSt-Klasse" sein.
    if not TAXCLASS_TOKEN_RE.match(tokens[-1]):
        return None
    if not PRICE_TOKEN_RE.match(tokens[-2]):
        return None

    total_price = tokens[-2]

    if QTY_TOKEN_RE.match(tokens[0]) and PRICE_TOKEN_RE.match(tokens[1] if len(tokens) > 1 else ""):
        # z.B. "2x 0,95 dmBio Kids Meerestiere 1,90 2"
        quantity = tokens[0][:-1]
        unit_price = tokens[1]
        name_tokens = tokens[2:-2]
    else:
        # z.B. "dmBio Gemüsepf. Bulgur&Quinoa 2,35 2" (Menge = 1)
        quantity = "1"
        unit_price = total_price
        name_tokens = tokens[:-2]

    if not name_tokens:
        return None

    name = clean_name(" ".join(name_tokens))
    if not re.search(r"[A-Za-zÄÖÜäöüß]", name) or len(name) < 2:
        return None

    try:
        if not (0 < float(quantity.replace(",", ".")) <= 100):
            return None
        if not (0 <= float(unit_price.replace(",", ".")) <= 1000):
            return None
    except ValueError:
        return None

    return name, unit_price, quantity


def extract_kassenbon(pages: list[str]) -> tuple[str | None, list[Item]]:
    full_text = "\n".join(pages)
    lines = [normalize_space(line) for line in full_text.splitlines()]
    lines = [line for line in lines if line]

    date: str | None = None
    items: list[Item] = []

    for line in lines:
        if date is None:
            match = KASSENBON_DATE_RE.match(line)
            if match:
                date = match.group(1)

        lower = line.casefold()
        if any(lower == word or lower.startswith(word + " ") for word in KASSENBON_STOP_WORDS):
            # Ab hier kommen nur noch Summen/MwSt-Aufstellung/Fusszeile.
            break

        parsed = parse_kassenbon_line(line)
        if parsed is None:
            continue

        name, unit_price, quantity = parsed
        if date is None:
            continue
        items.append(Item(name=name, unit_price=unit_price, quantity=quantity, date=date))

    return date, items


# --------------------------------------------------------------------------
# Rechnungs-Layout (Online-Bestellung, Tabelle)
# --------------------------------------------------------------------------

TABLE_HEADER = "Artikelbezeichnung"
TABLE_FOOTER = "dm-drogerie markt GmbH"

ITEM_HEADER_RE = re.compile(
    r"^(?P<brand>.+?)\s+(?P<unit>\d+[.,]\d{2})\s*€\s*\((?P<tax>\d)\)\s+"
    r"(?P<qty>\d+)\s+(?P<total>\d+[.,]\d{2})\s*€\s*$"
)
# Zeile mit "je Einheit"-Preisangabe, die aus der Artikelbeschreibung entfernt wird,
# z.B. "34,52 € je 1 kg." oder "0,12 € je 1 m."
PER_UNIT_SUFFIX_RE = re.compile(
    r"\s*\d+[.,]\d{2}\s*€\s*je\s*[\d.,]*\s*\S+\.?\s*$"
)

ORDER_DATE_RE = re.compile(r"Auftragsdatum:\s*(\d{2}\.\d{2}\.\d{4})")
INVOICE_DATE_RE = re.compile(r"Rechnungsdatum:\s*(\d{2}\.\d{2}\.\d{4})")


def extract_invoice_date(full_text: str) -> str | None:
    match = ORDER_DATE_RE.search(full_text)
    if match:
        return match.group(1)
    match = INVOICE_DATE_RE.search(full_text)
    if match:
        return match.group(1)
    return None


def extract_table_block(page_text: str) -> str | None:
    header_index = page_text.find(TABLE_HEADER)
    if header_index == -1:
        return None
    start = header_index + len(TABLE_HEADER)

    end_candidates = [len(page_text)]
    footer_index = page_text.find(TABLE_FOOTER, start)
    if footer_index != -1:
        end_candidates.append(footer_index)
    # "Summe" markiert den Beginn der Summen-/Rabatt-/MwSt-Zeilen und
    # taucht wegen der doppelten Textebene auch als "SummeSumme" auf,
    # was hier als Teilstring ebenfalls gefunden wird.
    summe_index = page_text.find("Summe", start)
    if summe_index != -1:
        end_candidates.append(summe_index)

    end = min(end_candidates)
    return page_text[start:end]


def extract_rechnung(pages: list[str]) -> tuple[str | None, list[Item]]:
    full_text = "\n".join(pages)
    date = extract_invoice_date(full_text)

    items: list[Item] = []

    for page_text in pages:
        block = extract_table_block(page_text)
        if not block:
            continue

        lines = [normalize_space(line) for line in block.splitlines()]
        lines = [line for line in lines if line]

        current: dict | None = None
        description_lines: list[str] = []

        def flush() -> None:
            if current is None:
                return
            description = clean_name(
                " ".join(description_lines)
            )
            name = clean_name(f"{current['brand']} {description}".strip())
            if name and date:
                items.append(
                    Item(
                        name=name,
                        unit_price=current["unit"],
                        quantity=current["qty"],
                        date=date,
                    )
                )

        for line in lines:
            match = ITEM_HEADER_RE.match(line)
            if match:
                flush()
                current = {
                    "brand": match.group("brand").strip(),
                    "unit": match.group("unit"),
                    "qty": match.group("qty"),
                }
                description_lines = []
                continue

            if current is not None:
                stripped = PER_UNIT_SUFFIX_RE.sub("", line).strip()
                if stripped:
                    description_lines.append(stripped)

        flush()

    return date, items


# --------------------------------------------------------------------------
# Hauptprogramm
# --------------------------------------------------------------------------

def looks_like_rechnung(pages: list[str]) -> bool:
    return any(TABLE_HEADER in page for page in pages)


def write_debug_text(pdf_path: Path, text: str) -> Path:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    output_path = DEBUG_DIR / f"{pdf_path.stem}.txt"
    output_path.write_text(text, encoding="utf-8")
    return output_path


def main() -> None:
    pdf_paths = sorted(PDF_DIR.rglob("*.pdf"))

    if not pdf_paths:
        print(
            f"Keine PDFs unter {PDF_DIR.resolve()} gefunden.\n"
            "Prüfe, ob PDF_DIR im Skript auf den richtigen Ordner zeigt.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    all_items: list[Item] = []
    unrecognized: list[dict[str, str]] = []

    print(f"{len(pdf_paths)} PDF-Dateien gefunden.")

    for index, pdf_path in enumerate(pdf_paths, start=1):
        print(f"[{index}/{len(pdf_paths)}] {pdf_path.name}")

        try:
            pages = read_pdf_pages(pdf_path)
        except Exception as error:
            unrecognized.append(
                {"datei": str(pdf_path), "grund": f"PDF konnte nicht gelesen werden: {error}"}
            )
            print(f"  Fehler beim Lesen: {error}")
            continue

        if looks_like_rechnung(pages):
            date, items = extract_rechnung(pages)
            art = "Rechnung"
        else:
            date, items = extract_kassenbon(pages)
            art = "Kassenbon"

        if items:
            print(f"  {art}: {len(items)} Artikel erkannt (Datum: {date}).")
            all_items.extend(items)
        else:
            debug_path = write_debug_text(pdf_path, "\n".join(pages))
            unrecognized.append(
                {
                    "datei": str(pdf_path),
                    "grund": f"{art}: keine Artikel erkannt (Datum: {date or 'unbekannt'})",
                }
            )
            print(f"  Nicht erkannt. Debug-Text: {debug_path}")

    # Nach Datum (TT.MM.JJJJ -> sortierbar machen) und Name sortieren.
    def sort_key(item: Item) -> tuple[str, str]:
        d, m, y = item.date.split(".")
        return f"{y}-{m}-{d}", item.name.casefold()

    all_items.sort(key=sort_key)

    with OUTPUT_CSV.open("w", newline="", encoding="utf-8-sig") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=["produktname", "einzelpreis", "menge", "datum"],
            delimiter=";",
        )
        writer.writeheader()
        writer.writerows(
            {
                "produktname": item.name,
                "einzelpreis": item.unit_price,
                "menge": item.quantity,
                "datum": item.date,
            }
            for item in all_items
        )

    with UNRECOGNIZED_CSV.open("w", newline="", encoding="utf-8-sig") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=["datei", "grund"], delimiter=";")
        writer.writeheader()
        writer.writerows(unrecognized)

    print()
    print(f"CSV-Zeilen:      {len(all_items)}")
    print(f"Nicht erkannt:   {len(unrecognized)}")
    print(f"Ergebnis:        {OUTPUT_CSV.resolve()}")
    print(f"Prüfliste:       {UNRECOGNIZED_CSV.resolve()}")


if __name__ == "__main__":
    main()
