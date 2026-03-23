"""
IBKR ECB FX Lookup
==================
Reads an IBKR Activity Statement CSV, extracts all unique trade date /
currency pairs within an optional date range, fetches the corresponding
EUR rates directly from the ECB SDMX API, and outputs a reference table.

Output columns: date, currency, eur_rate

Usage
-----
  python ibkr_fx_rates.py <ibkr_activity.csv>
  python ibkr_fx_rates.py <ibkr_activity.csv> --from 2025-01-01 --to 2025-12-31
  python ibkr_fx_rates.py <ibkr_activity.csv> --from 2025-01-01 --to 2025-12-31 --output fx_2025.csv
"""

import csv
import logging
import pandas as pd
import requests
import time
from io import StringIO
from datetime import datetime, date
from typing import Dict, List

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

MAX_GAP_DAYS = 5
RETRIES      = 3


# ── IBKR CSV parser ────────────────────────────────────────────────────────────

def parse_ibkr_csv(path: str) -> pd.DataFrame:
    """
    Parse the Trades section from an IBKR CSV.
    Returns a DataFrame with columns: date, currency.
    """
    trades_rows = []
    header      = None

    with open(path, encoding='utf-8-sig') as f:
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

    df["date"] = (df["datetime"]
                  .str.replace(r"[,;].*", "", regex=True)
                  .str.strip())
    df["date"] = pd.to_datetime(df["date"], format="%Y-%m-%d").dt.date

    return df[["date", "currency"]]


# ── ECB API helpers ────────────────────────────────────────────────────────────

def fetch_ecb_data(currency: str, start: date, end: date) -> str:
    """Fetch raw CSV text from the ECB SDMX API for a currency and date range."""
    url = (
        f"https://data-api.ecb.europa.eu/service/data/"
        f"EXR/D.{currency}.EUR.SP00.A"
        f"?startPeriod={start}&endPeriod={end}&format=csvdata"
    )
    last_err = None
    for attempt in range(1, RETRIES + 1):
        try:
            resp = requests.get(url, timeout=30, headers={"Accept": "text/csv"})
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as e:
            last_err = e
            if attempt < RETRIES:
                wait = attempt * 5
                logging.warning(f"Attempt {attempt} failed ({e.__class__.__name__}), "
                                f"retrying in {wait}s...")
                time.sleep(wait)
    raise RuntimeError(
        f"ECB fetch failed for {currency} after {RETRIES} attempts: {last_err}\n"
        "Check your internet connection or try again later."
    )


def parse_ecb_response(text: str, currency: str) -> Dict[date, float]:
    """
    Parse ECB SDMX CSV response.
    ECB returns foreign units per 1 EUR; inverted to EUR per 1 foreign unit.
    """
    df = pd.read_csv(StringIO(text))
    df.columns = [c.strip() for c in df.columns]

    if "TIME_PERIOD" not in df.columns or "OBS_VALUE" not in df.columns:
        raise ValueError(
            f"Unexpected ECB response columns for {currency}: {list(df.columns)}"
        )

    df["date_obj"] = pd.to_datetime(df["TIME_PERIOD"]).dt.date
    df["rate_raw"] = pd.to_numeric(df["OBS_VALUE"], errors="coerce")
    df = df.dropna(subset=["rate_raw"])

    return {
        row["date_obj"]: round(1 / row["rate_raw"], 6)
        for _, row in df.iterrows()
        if row["rate_raw"] > 0
    }


def map_rates(daily: Dict[date, float], required_dates: List[date],
              currency: str) -> List[Dict]:
    """
    Match each required date to an available ECB rate.
    Falls back to nearest date within MAX_GAP_DAYS (handles weekends/holidays).
    """
    results   = []
    available = sorted(daily.keys())

    for d in required_dates:
        if d in daily:
            rate = daily[d]
        else:
            closest = min(available, key=lambda x: abs((x - d).days))
            gap     = abs((closest - d).days)
            if gap > MAX_GAP_DAYS:
                raise ValueError(
                    f"No ECB rate within {MAX_GAP_DAYS} days of {d} for {currency}. "
                    f"Closest: {closest} ({gap} days away)."
                )
            rate = daily[closest]
        results.append({"date": str(d), "currency": currency, "eur_rate": rate})

    return results


# ── FX orchestrator ────────────────────────────────────────────────────────────

def fetch_fx_rates(pairs: Dict[str, List[date]]) -> List[Dict]:
    """Fetch EUR rates for all currencies and dates in pairs."""
    results = []

    for currency, dates in pairs.items():
        dates = sorted(dates)

        if currency == "EUR":
            results.extend(
                {"date": str(d), "currency": "EUR", "eur_rate": 1.0} for d in dates
            )
            continue

        logging.info(f"Fetching EUR/{currency} rates {dates[0]} → {dates[-1]}")
        text  = fetch_ecb_data(currency, dates[0], dates[-1])
        daily = parse_ecb_response(text, currency)

        if not daily:
            raise ValueError(
                f"No rates parsed for {currency}. "
                "Check the currency code is valid (e.g. USD, GBP, CHF)."
            )

        logging.info(f"  Received {len(daily)} daily rates.")
        results.extend(map_rates(daily, dates, currency))

    return results


# ── Main ───────────────────────────────────────────────────────────────────────

def main(ibkr_csv: str, date_from: str = None, date_to: str = None,
         output_csv: str = None):

    logging.info(f"Loading trades from: {ibkr_csv}")
    df = parse_ibkr_csv(ibkr_csv)
    logging.info(f"Found {len(df)} trade records")

    filter_from = pd.to_datetime(date_from).date() if date_from else None
    filter_to   = pd.to_datetime(date_to).date()   if date_to   else None

    if filter_from:
        df = df[df["date"] >= filter_from]
    if filter_to:
        df = df[df["date"] <= filter_to]

    if df.empty:
        logging.warning("No trades found in the specified period.")
        return

    if filter_from or filter_to:
        label_from = str(filter_from) if filter_from else "beginning"
        label_to   = str(filter_to)   if filter_to   else "end"
        logging.info(f"Date filter: {label_from} → {label_to} ({len(df)} trades retained)")

    pairs: Dict[str, set] = {}
    for _, row in df.drop_duplicates().iterrows():
        ccy = row["currency"].strip().upper()
        pairs.setdefault(ccy, set()).add(row["date"])
    pairs = {k: sorted(v) for k, v in pairs.items()}

    logging.info(
        f"{len(pairs)} currencies, "
        f"{sum(len(v) for v in pairs.values())} unique date/currency pairs"
    )

    results = fetch_fx_rates(pairs)

    result_df = (pd.DataFrame(results)
                   .sort_values(["date", "currency"])
                   .reset_index(drop=True))
    result_df["eur_rate"] = result_df["eur_rate"].round(4)

    print()
    print(result_df.to_string(index=False))
    print(f"\n  {len(result_df)} rows ({len(pairs)} currencies)")

    if output_csv:
        result_df.to_csv(output_csv, index=False, encoding="utf-8-sig")
        logging.info(f"Saved to {output_csv}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Extract EUR FX rates for trade dates from an IBKR activity statement."
    )
    parser.add_argument("ibkr_csv",
                        help="IBKR CSV file containing a Trades section")
    parser.add_argument("--from", dest="date_from", default=None,
                        metavar="YYYY-MM-DD",
                        help="Include trades from this date (inclusive)")
    parser.add_argument("--to",   dest="date_to",   default=None,
                        metavar="YYYY-MM-DD",
                        help="Include trades up to this date (inclusive)")
    parser.add_argument("--output", dest="output",  default=None,
                        metavar="FILE.csv",
                        help="Save output to CSV file")
    args = parser.parse_args()

    main(args.ibkr_csv, args.date_from, args.date_to, args.output)