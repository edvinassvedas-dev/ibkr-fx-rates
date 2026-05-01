# ibkr-fx-rates

A Python command-line tool that reads an IBKR Activity Statement CSV, extracts
all unique trade date / currency combinations, fetches the corresponding EUR
exchange rates from the ECB SDMX API, and outputs a reference table.

Intended for tax reporting — the ECB is the standard authoritative source for
EUR reference rates across EU jurisdictions.

Built on top of [ecbfx](https://github.com/edvinassvedas-dev/ecbfx).

---

## Output

A table with one row per unique trade date / currency pair:

| date | currency | eur_rate |
|---|---|---|
| 2025-10-28 | USD | 0.8598 |
| 2025-11-07 | GBP | 1.1842 |
| 2026-01-20 | USD | 0.8527 |

Sorted by date ascending. EUR trades included with rate `1.0`. Rates rounded to
4 decimal places, matching ECB source precision.

---

## How rates are calculated

The ECB publishes reference rates as foreign currency units per 1 EUR
(e.g. EUR/USD = 1.1728 means 1.1728 USD per 1 EUR). The script inverts this to
get EUR per 1 foreign unit: `1 / 1.1728 = 0.8527`.

When a trade date falls on a weekend or bank holiday (no ECB rate published),
the tool uses the most recent prior trading day's rate (Last Observation
Carried Forward). This applies to the first date in a range too — a period
starting on January 1st will not error.

---

## Requirements

```
Python 3.9+
pandas
ecbfx >= 0.2.0
```

Install dependencies:

```bash
pip install -r requirements.txt
```

---

## Usage

```bash
# Full history
python ibkr_fx_rates.py activity.csv

# Specific period
python ibkr_fx_rates.py activity.csv --from 2025-01-01 --to 2025-12-31

# Save to CSV
python ibkr_fx_rates.py activity.csv --from 2025-01-01 --to 2025-12-31 --output fx_2025.csv
```

Progress is printed with timestamps. Without `--output`, results are printed to
the terminal only. With `--output`, results are both printed and saved to CSV.

---

## Parameters

| Parameter | Description |
|---|---|
| `ibkr_csv` | Trades CSV file |
| `--from YYYY-MM-DD` | Include trades from this date (inclusive) |
| `--to YYYY-MM-DD` | Include trades up to this date (inclusive) |
| `--output FILE.csv` | Save results to CSV file |

---

## Input file

The tool reads the `Trades` section of the input CSV, extracting `Date/Time`
and `Currency` columns. All other sections are ignored.

---

## Data source

Rates are fetched from the **ECB SDMX API** (`data-api.ecb.europa.eu`). This
is the same source displayed on the ECB website and is updated each business
day at approximately 16:00 CET.

The API is called once per currency regardless of how many trades share that
currency, covering the full date range needed. Retries up to 3 times with
exponential backoff on failure.

---

## Notes

- Only stock trades (`Asset Category = Stocks`) are processed
- 4 decimal places matches ECB source precision; additional decimals would be
  false precision given the ECB publishes 4 significant figures

---

## License

MIT — do whatever you like.
