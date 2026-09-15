#!/usr/bin/env python3
"""
Lädt dm_artikel.csv und aggregiert die Kaufhistorie pro Produkt
(Kaufhäufigkeit, durchschnittliches Kaufintervall, Tage seit letztem Kauf).

Wird von chat.py als Grundlage für die Tool-Aufrufe des Chat-Agenten genutzt,
lässt sich aber auch eigenständig ausführen, um die aktuell "fälligen"
Produkte auf der Kommandozeile zu sehen:

    python3 purchase_data.py
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

DEFAULT_CSV_PATH = Path("dm_artikel.csv")


@dataclass(frozen=True)
class Purchase:
    name: str
    unit_price: float
    quantity: float
    date: date


@dataclass(frozen=True)
class ProductStats:
    name: str
    purchase_count: int
    first_date: date
    last_date: date
    total_spent: float
    avg_interval_days: float | None  # None, wenn das Produkt nur einmal gekauft wurde
    days_since_last: int

    @property
    def is_overdue(self) -> bool:
        return self.avg_interval_days is not None and self.days_since_last > self.avg_interval_days

    @property
    def overdue_by_days(self) -> float:
        if self.avg_interval_days is None:
            return 0.0
        return self.days_since_last - self.avg_interval_days


# --------------------------------------------------------------------------
# CSV laden
# --------------------------------------------------------------------------

def _parse_date(raw: str) -> date | None:
    raw = raw.strip()
    if not raw:
        return None
    # dm_pdfs_zu_csv.py schreibt ISO-Datumsformat; TT.MM.JJJJ zur Sicherheit
    # ebenfalls akzeptieren, falls sich das Exportformat mal ändert.
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _parse_decimal(raw: str) -> float | None:
    raw = raw.strip()
    if not raw:
        return None
    try:
        return float(raw.replace(",", "."))
    except ValueError:
        return None


def load_purchases(csv_path: Path = DEFAULT_CSV_PATH) -> list[Purchase]:
    """Liest dm_artikel.csv ein und überspringt unvollständige/kaputte Zeilen
    (z.B. Summenzeilen ohne Produktname, die dm_pdfs_zu_csv.py vereinzelt
    fälschlich mit extrahiert)."""
    purchases: list[Purchase] = []

    with csv_path.open(newline="", encoding="utf-8-sig") as csv_file:
        reader = csv.DictReader(csv_file, delimiter=";")
        for row in reader:
            name = (row.get("produktname") or "").strip()
            if not name:
                continue

            purchase_date = _parse_date(row.get("datum") or "")
            if purchase_date is None:
                continue

            unit_price = _parse_decimal(row.get("einzelpreis") or "")
            if unit_price is None:
                continue

            quantity = _parse_decimal(row.get("menge") or "")
            if quantity is None:
                continue

            purchases.append(
                Purchase(name=name, unit_price=unit_price, quantity=quantity, date=purchase_date)
            )

    return purchases


# --------------------------------------------------------------------------
# Aggregation pro Produkt
# --------------------------------------------------------------------------

def compute_product_stats(
    purchases: list[Purchase], reference_date: date | None = None
) -> list[ProductStats]:
    reference_date = reference_date or date.today()

    by_name: dict[str, list[Purchase]] = {}
    for purchase in purchases:
        by_name.setdefault(purchase.name, []).append(purchase)

    stats: list[ProductStats] = []
    for name, entries in by_name.items():
        entries.sort(key=lambda p: p.date)
        first_date, last_date = entries[0].date, entries[-1].date
        purchase_count = len(entries)
        total_spent = sum(p.unit_price * p.quantity for p in entries)

        avg_interval_days: float | None = None
        if purchase_count >= 2:
            span_days = (last_date - first_date).days
            if span_days > 0:
                avg_interval_days = span_days / (purchase_count - 1)

        stats.append(
            ProductStats(
                name=name,
                purchase_count=purchase_count,
                first_date=first_date,
                last_date=last_date,
                total_spent=round(total_spent, 2),
                avg_interval_days=avg_interval_days,
                days_since_last=(reference_date - last_date).days,
            )
        )

    return stats


# --------------------------------------------------------------------------
# Abfragen (Basis für die Chat-Tools)
# --------------------------------------------------------------------------

def list_overdue_products(
    stats: list[ProductStats], min_days_overdue: int = 0, limit: int = 15
) -> list[ProductStats]:
    overdue = [s for s in stats if s.is_overdue and s.overdue_by_days >= min_days_overdue]
    overdue.sort(key=lambda s: s.overdue_by_days, reverse=True)
    return overdue[:limit]


def find_products(purchases: list[Purchase], query: str) -> list[Purchase]:
    query_cf = query.casefold()
    matches = [p for p in purchases if query_cf in p.name.casefold()]
    matches.sort(key=lambda p: p.date)
    return matches


def recent_purchases(
    purchases: list[Purchase], days: int, reference_date: date | None = None
) -> list[Purchase]:
    reference_date = reference_date or date.today()
    cutoff = reference_date - timedelta(days=days)
    matches = [p for p in purchases if p.date >= cutoff]
    matches.sort(key=lambda p: p.date, reverse=True)
    return matches


# --------------------------------------------------------------------------
# Kommandozeilen-Selbsttest
# --------------------------------------------------------------------------

def main() -> None:
    purchases = load_purchases()
    stats = compute_product_stats(purchases)
    overdue = list_overdue_products(stats, limit=15)

    print(f"{len(purchases)} Käufe geladen, {len(stats)} unterschiedliche Produkte.")
    print()
    print("Vermutlich mal wieder fällig:")
    for s in overdue:
        interval = f"{s.avg_interval_days:.0f}" if s.avg_interval_days is not None else "?"
        print(
            f"  - {s.name}"
            f"  (zuletzt vor {s.days_since_last} Tagen, Ø-Intervall {interval} Tage, "
            f"{s.purchase_count}x gekauft)"
        )


if __name__ == "__main__":
    main()
