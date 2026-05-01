"""
IBKR ECB FX Lookup
==================
Reads an IBKR Activity Statement CSV, extracts all unique trade date /
currency pairs within an optional date range, and fetches the corresponding
EUR rates using the ecbfx package.

Output columns: date, currency, eur_rate

Usage
-----
  python ibkr_fx_rates.py <ibkr_activity.csv>
  python ibkr_fx_rates.py <ibkr_activity.csv> --from 2025-01-01 --to 2025-12-31
  python ibkr_fx_rates.py <ibkr_activity.csv> --from 2025-01-01 --to 2025-12-31 --output fx_2025.csv
"""

import argparse
import csv
import logging
import sys
from datetime import date
from typing import Optional

import pandas as pd

from ecbfx import ECBError, fetch_rates_for_pairs

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)


# ── IBKR CSV parser ────────────────────────────────────────────────────────────

def parse_ibkr_csv(path: str) -> pd.DataFrame:
    """
    Parse the Trades section from an IBKR Activity Statement CSV.
    Returns a DataFrame with columns: date, currency.
    """
    trades_rows = []
    header      = None

    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            parts = next(csv.reader([line]), [])
            if not parts:
                continue

            section = parts[0].strip()
            kind    = parts[1].strip() if len(parts) > 1 else ""

            if section == "Trades" and kind == "Header":
                header = [c.strip() for c in parts[2:]]

            elif section == "Trades" and kind == "Data" and header:
                row = dict(zip(header, [c.strip() for c in parts[2:]]))
                if row.get("Asset Category", "") in ("Stocks", "Stock"):
                    trades_rows.append(row)

    if not trades_rows:
        raise ValueError(
            "No stock trades found. Check that the CSV contains a 'Trades' "
            "section with Asset Category = 'Stocks'."
        )

    df = pd.DataFrame(trades_rows)

    # Guard against column name variations across IBKR export versions
    rename = {"Date/Time": "datetime", "Currency": "currency"}
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})

    df["date"] = (
        df["datetime"]
        .str.replace(r"[,;].*", "", regex=True)
        .str.strip()
    )
    df["date"] = pd.to_datetime(df["date"], format="%Y-%m-%d").dt.date

    return df[["date", "currency"]]


# ── Main ───────────────────────────────────────────────────────────────────────

def main(
    ibkr_csv: str,
    date_from: Optional[str] = None,
    date_to:   Optional[str] = None,
    output_csv: Optional[str] = None,
) -> int:

    logging.info("Loading trades from: %s", ibkr_csv)
    try:
        df = parse_ibkr_csv(ibkr_csv)
    except (ValueError, OSError) as exc:
        logging.error("Failed to parse IBKR CSV: %s", exc)
        return 1

    logging.info("Found %d trade records", len(df))

    filter_from = date.fromisoformat(date_from) if date_from else None
    filter_to   = date.fromisoformat(date_to)   if date_to   else None

    if filter_from:
        df = df[df["date"] >= filter_from]
    if filter_to:
        df = df[df["date"] <= filter_to]

    if df.empty:
        logging.warning("No trades found in the specified period.")
        return 0

    if filter_from or filter_to:
        label_from = str(filter_from) if filter_from else "beginning"
        label_to   = str(filter_to)   if filter_to   else "end"
        logging.info(
            "Date filter: %s → %s (%d trades retained)",
            label_from, label_to, len(df),
        )

    # Build the list of unique (date, currency) pairs
    pairs = [
        (row["date"], row["currency"].strip().upper())
        for _, row in df.drop_duplicates().iterrows()
    ]

    unique_currencies = len({ccy for _, ccy in pairs})
    logging.info(
        "%d currencies, %d unique date/currency pairs",
        unique_currencies, len(pairs),
    )

    # Fetch rates — one HTTP call per currency regardless of pair count
    try:
        results = fetch_rates_for_pairs(pairs, direct=True, decimals=4)
    except ECBError as exc:
        logging.error("ECB fetch failed: %s", exc)
        return 1

    # Rename 'rate' → 'eur_rate' to match the original output schema
    result_df = (
        pd.DataFrame(results)
        .rename(columns={"rate": "eur_rate"})
        [["date", "currency", "eur_rate"]]
        .sort_values(["date", "currency"])
        .reset_index(drop=True)
    )

    print()
    print(result_df.to_string(index=False))
    print(f"\n  {len(result_df)} rows ({unique_currencies} currencies)")

    if output_csv:
        result_df.to_csv(output_csv, index=False, encoding="utf-8-sig")
        logging.info("Saved to %s", output_csv)

    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Extract EUR FX rates for trade dates from an IBKR activity statement."
    )
    parser.add_argument(
        "ibkr_csv",
        help="IBKR CSV file containing a Trades section",
    )
    parser.add_argument(
        "--from", dest="date_from", default=None, metavar="YYYY-MM-DD",
        help="Include trades from this date (inclusive)",
    )
    parser.add_argument(
        "--to", dest="date_to", default=None, metavar="YYYY-MM-DD",
        help="Include trades up to this date (inclusive)",
    )
    parser.add_argument(
        "--output", dest="output", default=None, metavar="FILE.csv",
        help="Save output to CSV file",
    )
    args = parser.parse_args()

    sys.exit(main(args.ibkr_csv, args.date_from, args.date_to, args.output))
