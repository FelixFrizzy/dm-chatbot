#!/usr/bin/env python3
"""
Chat-Assistent für die dm-Kaufhistorie.

Ein kleiner Tool-Calling-Agent (Anthropic Claude): das Modell bekommt keine
fertige Zusammenfassung der Kaufhistorie vorgesetzt, sondern ruft bei Bedarf
Python-Funktionen auf, die auf dm_artikel.csv rechnen (überfällige Produkte,
Kaufhistorie einzelner Artikel, letzte Käufe).

Voraussetzung: ANTHROPIC_API_KEY in der Umgebung oder in .env (siehe
.env.example).

Start:
    python3 chat.py
    python3 chat.py --csv example_data/dm_artikel_beispiel.csv
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from purchase_data import (
    ProductStats,
    Purchase,
    compute_product_stats,
    find_products,
    list_overdue_products,
    load_purchases,
    recent_purchases,
)

DEFAULT_CSV_PATH = Path("dm_artikel.csv")
DEFAULT_MODEL = "claude-haiku-4-5-20251001"

SYSTEM_PROMPT = """\
Du bist ein Einkaufsberater, der dem Nutzer hilft herauszufinden, was er bei \
dm mal wieder kaufen sollte. Du hast Tools, die die echte Kaufhistorie des \
Nutzers auswerten (aus dm_artikel.csv). Stütze deine Antworten immer auf die \
Tool-Ergebnisse statt zu raten, nenne konkrete Daten (letztes Kaufdatum, \
übliches Kaufintervall). Antworte auf Deutsch, kurz und konkret.

Nutze list_overdue_products für allgemeine Einkaufsvorschläge, \
get_product_history bei Fragen zu einem bestimmten Produkt und \
list_recent_purchases bei Fragen zu kürzlichen Einkäufen."""

TOOLS = [
    {
        "name": "list_overdue_products",
        "description": (
            "Listet Produkte, die laut Kaufhistorie überfällig zum Nachkauf "
            "sind (Tage seit letztem Kauf > übliches Kaufintervall), "
            "sortiert nach Dringlichkeit."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "min_days_overdue": {
                    "type": "integer",
                    "description": "Nur Produkte, die mindestens so viele Tage überfällig sind.",
                    "default": 0,
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximale Anzahl Ergebnisse.",
                    "default": 15,
                },
            },
        },
    },
    {
        "name": "get_product_history",
        "description": (
            "Gibt die komplette Kaufhistorie (Datum, Menge, Preis) für "
            "Produkte zurück, deren Name die Suchanfrage enthält "
            "(Teilstring-Suche, Groß-/Kleinschreibung egal)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Such-Teilstring, z.B. 'Kaffee' oder 'Zahncreme'.",
                }
            },
            "required": ["query"],
        },
    },
    {
        "name": "list_recent_purchases",
        "description": "Listet alle Käufe der letzten N Tage, neueste zuerst.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Zeitraum in Tagen.",
                    "default": 30,
                }
            },
        },
    },
]


def execute_tool(
    name: str,
    tool_input: dict,
    purchases: list[Purchase],
    stats: list[ProductStats],
) -> object:
    if name == "list_overdue_products":
        results = list_overdue_products(
            stats,
            min_days_overdue=int(tool_input.get("min_days_overdue", 0)),
            limit=int(tool_input.get("limit", 15)),
        )
        return [
            {
                "produktname": s.name,
                "zuletzt_gekauft": s.last_date.isoformat(),
                "tage_seit_letztem_kauf": s.days_since_last,
                "durchschnittliches_kaufintervall_tage": round(s.avg_interval_days, 1),
                "ueberfaellig_seit_tagen": round(s.overdue_by_days, 1),
                "anzahl_bisheriger_kaeufe": s.purchase_count,
            }
            for s in results
        ]

    if name == "get_product_history":
        matches = find_products(purchases, tool_input.get("query", ""))
        return [
            {
                "produktname": p.name,
                "datum": p.date.isoformat(),
                "menge": p.quantity,
                "einzelpreis": p.unit_price,
            }
            for p in matches
        ]

    if name == "list_recent_purchases":
        matches = recent_purchases(purchases, days=int(tool_input.get("days", 30)))
        return [
            {
                "produktname": p.name,
                "datum": p.date.isoformat(),
                "menge": p.quantity,
                "einzelpreis": p.unit_price,
            }
            for p in matches
        ]

    return {"error": f"Unbekanntes Tool: {name}"}


def run_turn(
    client: anthropic.Anthropic,
    model: str,
    history: list[dict],
    purchases: list[Purchase],
    stats: list[ProductStats],
) -> None:
    while True:
        response = client.messages.create(
            model=model,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=history,
        )
        history.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            for block in response.content:
                if block.type == "text" and block.text.strip():
                    print(f"Assistent> {block.text.strip()}")
            return

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            result = execute_tool(block.name, block.input, purchases, stats)
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )
        history.append({"role": "user", "content": tool_results})


def main() -> None:
    parser = argparse.ArgumentParser(description="Chat-Assistent für die dm-Kaufhistorie")
    parser.add_argument(
        "--csv", type=Path, default=DEFAULT_CSV_PATH, help="Pfad zur Artikel-CSV (Default: dm_artikel.csv)"
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Anthropic Modell-ID")
    args = parser.parse_args()

    load_dotenv()
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print(
            "ANTHROPIC_API_KEY ist nicht gesetzt. Kopiere .env.example nach .env "
            "und trage deinen Key ein (siehe README).",
            file=sys.stderr,
        )
        raise SystemExit(1)

    if not args.csv.exists():
        print(
            f"{args.csv} wurde nicht gefunden. Erst dm_pdfs_zu_csv.py ausführen "
            "oder --csv auf eine vorhandene Datei zeigen lassen "
            "(z.B. example_data/dm_artikel_beispiel.csv).",
            file=sys.stderr,
        )
        raise SystemExit(1)

    purchases = load_purchases(args.csv)
    stats = compute_product_stats(purchases)

    print(f"{len(purchases)} Käufe geladen ({len(stats)} unterschiedliche Produkte) aus {args.csv}")
    print("Frag z.B. 'Was sollte ich mal wieder kaufen?'. 'exit' zum Beenden.\n")

    client = anthropic.Anthropic(api_key=api_key)
    history: list[dict] = []

    while True:
        try:
            user_input = input("Du> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not user_input:
            continue
        if user_input.lower() in {"exit", "quit", "ende"}:
            break

        history.append({"role": "user", "content": user_input})
        run_turn(client, args.model, history, purchases, stats)


if __name__ == "__main__":
    main()
