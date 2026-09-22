# Kimirica — Executive Sales Dashboard (Streamlit)

A fast, leadership-focused view of sales, growth, channel performance, targets and exceptions.
Power BI remains the place for drilldowns; this app answers "how are we doing?" in 30 seconds.

## Quick start

```bash
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # fill in real values
python -m streamlit run app.py
```

On Windows, use `python -m streamlit` (the `streamlit` command is often not on PATH).

With no BigQuery settings (or `DEMO_MODE = "true"`), the app runs on synthetic data and shows a
"Demo data" badge, so the layout can be reviewed before credentials are ready.

## Credentials

Credentials are read in this order; nothing is hardcoded.

1. `[gcp_service_account]` block in `.streamlit/secrets.toml` (or Streamlit Cloud secrets)
2. `GOOGLE_APPLICATION_CREDENTIALS` environment variable
3. Application Default Credentials (e.g. on Cloud Run / GCE)

The service account needs **BigQuery Data Viewer** on the dataset and **BigQuery Job User** on the project.
Every setting in `config.py` can also be supplied as an environment variable with the same name.

## Source tables

`aerobic-copilot-494105-b6.Datachannel`:

| Table | Setting | Columns used |
| --- | --- | --- |
| `Executive_Sales_Master` | `BQ_TABLE` | `sales_date, channel, category, mrp_sales, gross_sales, quantity_sold` (+ `orders` if present) |
| `Executive_Weekly_Gross_Sales` | `BQ_WEEKLY_TABLE` | `sales_date, channel, category, gross_sales` |
| `Executive_Spends_Master` | `BQ_AD_TABLE` | `spend_date, channel, spend` |
| `AOP_Daily_Target_vs_Achievement` | `BQ_TARGET_TABLE` | `sales_date, Channel, Target_Revenue, Achieved_Revenue` (summed to date × channel) |
| `AOP_targets` | `BQ_AOP_TABLE` | `Financial_Year, Month, Channel, Revenue` (summed to month × channel) |

On startup the app reads `INFORMATION_SCHEMA.COLUMNS` for these tables and switches off anything
that isn't there: no `category` hides the category section, no `orders` makes AOV fall back to ASP,
no AOP column hides pacing and the AOP columns. Missing required columns raise a clear message
instead of a stack trace. `last_updated`, `source` and the weekly `discount` column are not used.

**AOP.** Month and year AOP totals come from `AOP_targets`: the year is the sum of `Revenue` for
the financial year (`SUM(Revenue) WHERE Financial_Year = '2026-27'`, across all channels unless you
filter), the month is that month's sum. `Month` can be `Apr`, `April`,
`Apr-26`, `2026-04` or `04`; January to March fall in the second calendar year of the FY.
Achievement comes from `Achieved_Revenue` in `AOP_Daily_Target_vs_Achievement`, up to the selected
date. Projected = achieved extended at the current daily pace. In the channel table and the AOP chart,
achievement is achieved-to-date ÷ full-month AOP, coloured against the share of the month elapsed
(green when on pace). The "Day" view uses the daily `Target_Revenue`.

`last_updated`, the spends `source` column and the weekly `discount` column are not used.
`CHANNEL_ALIASES` in `config.py` maps source channel names onto the dashboard's names if they
ever differ between tables.

## Data rules

**Net sales** = gross sales ÷ 1.18 (18% GST removed; `GST_RATE`).

**Amazon-VC latest date (dynamic).** The dashboard checks VC's latest loaded date every refresh
(`DYNAMIC_LAG_CHANNELS`). If it is behind the selected date, VC's MTD ends on its latest date, and its
LMTD, last-year, year-to-date and current-month windows end on the same day number, so comparisons
stay like-for-like. The month-end projection paces VC over the days it has. The watchlist flags VC
only when it is later than its normal delay (`EXPECTED_LAG_DAYS`, 1 day).

**Weekly gross channels** (`WEEKLY_GROSS_CHANNELS`). MRP arrives daily; gross arrives weekly.
For each channel, the last date with actual gross is its "last actual" date. After that date,
gross = daily MRP × (1 − discount), where the discount is gross ÷ MRP over the
`EST_LOOKBACK_DAYS` (default 28) days up to the last actual, per category where possible.
Net sales follow from gross. When the next weekly load
arrives, actuals replace the estimates and the discount is recalculated. Estimated values are
used for those days, and a watchlist item appears if a channel's weekly gross is more than
`WEEKLY_OVERDUE_DAYS` old.

## How it stays fast

| Query | Purpose | Cache |
| --- | --- | --- |
| Freshness | Last date with sales per channel (partition-pruned, 120 days) | 10 min |
| Sales history | Everything the table holds (capped by `MAX_HISTORY_DAYS`, 1500) to 3 days ago | 12 h |
| Sales recent | Last 3 days through the financial year end (late data, full-year AOP) | 10 min |
| Weekly gross, ad spends, AOP | Whole window | 15 min |

All visuals are computed in pandas from those results, so a normal page view or filter change
runs no BigQuery job. "Refresh data" clears the caches.
Tune with `HISTORY_DAYS`, `RECENT_DAYS`, `TTL_RECENT_SECONDS`, `TTL_HISTORY_SECONDS`.

## Periods and comparisons

The filter bar has **View**, a period picker, and **Compare with**. The line under it always spells out
both date ranges.

| View | Period | Previous period | Last year |
| --- | --- | --- | --- |
| Month (default: this month) | 1st to latest date, or the full month | Same days of last month (LMTD); a completed month compares with the full previous month | Same dates a year earlier |
| Financial year | FY start to latest date, or the full FY | Same days of the previous FY | Same dates a year earlier |
| Custom | Any range | The equal-length range immediately before it | Same dates a year earlier |

Cards, the channel and category tables, and "what moved" all use the selected period and comparison.
Month pacing uses the month containing the period's end date; year pacing its financial year. AOP in
the tables and the AOP chart covers the whole months in the period, with achievement coloured against
the share of that time elapsed. The monthly trend always shows the 12 months ending at the period end.

Add `?refresh=1` to the URL to clear every cache and re-read BigQuery immediately.

## Freebie categories

Rows whose category is Consumables, Freebie, Primary or Uncategorised (any spelling or case, see
`EXCLUDED_CATEGORIES`) are dropped when the data loads, so they never reach MRP, gross, quantity, AOV,
ASP, the category table or the estimates.

## Date range and partial sources

The period picker spans the full loaded history, not the shortest source. Each source is loaded for
its own range, so a table that stops early (ad spends ending in May, say) never truncates the rest.
Where a source doesn't cover the selected window, a short line under the cards says so, for example
"No ad spends after 31 May 2026", and its figures show as dashes rather than zeros.

## Connecting

Download the service account's JSON key, then run:

```bash
python make_secrets.py path/to/key.json
```

It writes `.streamlit/secrets.toml` with all the table settings and the key converted to valid TOML
(pasting the JSON by hand is the usual reason the dashboard stays on demo data). If the file exists
but can't be parsed, the dashboard shows the exact parse error at the top.

## Checking the numbers

```bash
python check_numbers.py                 # month to date
python check_numbers.py 2026-09-01 2026-09-17
```

Prints, per channel, the raw sales-master totals next to what the dashboard shows, plus the things
that usually explain a mismatch: duplicate rows at the stated grain, channel names that differ
between the four tables, NULL vs 0 gross, and raw vs loaded AOP targets. `mrp_diff` should be 0 on
every row; differences in gross are the weekly table and the estimate rules, shown as `est_days`.

If BigQuery isn't connected, the dashboard falls back to synthetic demo data and shows a red
"these numbers are not real" banner at the top.

## Metric rules

* **Top cards** (eight, same size): MRP sales, gross sales, net sales, discount, quantity, AOV,
  ASP, ad spends. Every card compares MTD with LMTD as a percentage change.
* **Pacing**: month and year side by side, both against AOP on MRP sales, showing AOP, achieved,
  projected (achieved extended at the current daily pace) and pace per day. The bar shows achieved
  solid, projected hatched, and a marker for time elapsed.
* **AOP** targets are on MRP sales; achievement = MRP sales on channel-days with an AOP ÷ AOP.
* **Monthly trend**: last 12 months as bars, with last year as faint bars behind. YoY growth is
  labelled on each bar; the tooltip shows the value, last year, YoY and MoM. The current month is
  hatched and is month to date, compared with the same days last year.
* **Growth** (cards, channel and category tables, "what moved" chart) is measured on MRP sales
  (`GROWTH_METRIC`), since MRP is actual and daily for every channel.
* **Ad spends %** = ad spends ÷ gross sales.
* **Year start** is April (Indian FY) by default. Set `YEAR_START_MONTH = 1` in secrets for calendar year.
  This drives the year-to-date card and the month-on-month section.
* **Discount** = 1 − gross sales ÷ MRP sales (MRP includes freebies).
* **AOV** uses orders where the sales table has them; everywhere else units count as orders, so
  AOV equals ASP.

* NULL means "not tracked" and is shown as "—"; it is never converted to zero (sums use `min_count=1`).
* **MTD** = 1st to selected date. **LMTD** / **LY MTD** = same day numbers (capped at month length).
* **ASP** = gross sales ÷ quantity.
* **Target achievement** compares sales only on channel-days that carry a target, so channels
  without targets don't inflate it.
* **Projected close** assumes the MTD daily pace continues.
* With a category filter active, orders and targets are hidden (they are channel-level facts).

## Watchlist rules (`config.py`)

| Rule | Default |
| --- | --- |
| Channel has no data for the selected date | always flagged |
| Day vs trailing 7-day average | ±35%, channels ≥ 2% of recent sales |
| MTD target achievement | below 85% |
| MoM decline | −15% or worse, channels ≥ 3% share |

## Project layout

```text
app.py                  page layout, filters, section wiring
config.py               settings, schema mapping, channels, colours, thresholds
bigquery.py             client, cached loaders, single data entry point
queries.py              SQL for freshness, sales, weekly gross, ad spends
estimates.py            gross fallback chain (weekly table, then estimates)
check_numbers.py        reconciles the dashboard against raw BigQuery
make_secrets.py         writes .streamlit/secrets.toml from a service-account JSON key
assets/kimirica_logo.svg  vector logo used in the header
metrics.py              periods, KPIs, tables, insights, watchlist, formatting
demo_data.py            synthetic data for design review
components/
    theme.py            CSS tokens, header, section headings
    kpi_cards.py        KPI cards and month pacing strip
    charts.py           Plotly charts (₹ L/Cr axes and tooltips)
    tables.py           sortable formatted tables
    insights.py         highlights and watchlist rendering
```

Adding a channel: append it to `CHANNELS`, `CHANNEL_GROUPS` and `CHANNEL_COLORS`. Channels found
in the data but missing from config still appear (with a neutral colour).

Requires Streamlit 1.52+ (uses `st.dataframe(placeholder=...)`, `st.segmented_control`, keyed containers).
