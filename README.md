# ibkr-fx-rates

A Python command-line tool that reads an IBKR Activity Statement CSV, extracts
all unique trade date / currency combinations, fetches the corresponding EUR
exchange rates from the ECB, and outputs a reference table.

Intended for tax reporting — the ECB is the standard authoritative source for
EUR reference rates across EU jurisdictions.

Built on top of [ecbfx](https://github.com/edvinassvedas-dev/ecbfx).

---

## Output

A table with one row per unique trade date / currency pair:

| date       | currency | eur_rate |
|------------|----------|----------|
| 2025-10-28 | USD      | 0.8598   |
| 2025-11-07 | GBP      | 1.1842   |
| 2026-01-20 | USD      | 0.8527   |

Sorted by date ascending. EUR trades included with rate `1.0`.

---

## Requirements

```
Python 3.9+
pandas
ecbfx
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

Without `--output`, results are printed to
the terminal only.

---

## Parameters

| Parameter           | Description                                 |
|---------------------|---------------------------------------------|
| `ibkr_csv`          | Trades CSV file                             |
| `--from YYYY-MM-DD` | Include trades from this date (inclusive)   |
| `--to YYYY-MM-DD`   | Include trades up to this date (inclusive)  |
| `--output FILE.csv` | Save results to CSV file                    |

---

## Input file

The tool reads the `Trades` section of the input CSV, extracting `Date/Time`
and `Currency` columns. Only rows with `Asset Category = Stocks` are processed;
all other sections and asset categories are ignored.

---

## License

MIT — do whatever you like.
