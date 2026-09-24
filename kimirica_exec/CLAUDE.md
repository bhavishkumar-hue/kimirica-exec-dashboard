# Kimirica Executive Sales Dashboard

Streamlit dashboard for Kimirica Lifestyle's leadership (CEO, co-founders, CGO). A manager should
understand the business in 30 seconds. Power BI handles drilldowns; this stays lean and fast.

Owner runs it on **Windows (PowerShell)**, Python 3.14. Use `python -m streamlit run app.py`
(the `streamlit` command isn't on PATH). Never use `%-d` in Python `strftime`; use `metrics.strf()`.

## Commands

```powershell
python -m streamlit run app.py          # run the dashboard
python check_numbers.py                 # reconcile against raw BigQuery (MTD)
python check_numbers.py 2026-09-01 2026-09-17
python make_secrets.py path\to\key.json # write .streamlit/secrets.toml from a service-account key
$env:DEMO_MODE="true"; python -m streamlit run app.py   # synthetic data
```

Add `?refresh=1` to the URL to clear all caches. `.streamlit/secrets.toml` must never be committed.

## Layout of the code

- `app.py` page layout and filters. `config.py` every setting (overridable via secrets/env).
- `bigquery.py` loading, caching, schema detection (`INFORMATION_SCHEMA`), demo fallback.
- `queries.py` SQL. `estimates.py` gross fallback chain. `metrics.py` all business logic.
- `components/` theme (CSS, logo header), kpi_cards (cards + pacing), charts (Plotly), tables, insights.
- `demo_data.py` synthetic data shaped like the real tables. `assets/kimirica_logo.svg` traced logo.

## Data (BigQuery `aerobic-copilot-494105-b6.Datachannel`, all day grain)

| Table | Used for |
| --- | --- |
| `Executive_Sales_Master` (sales_date, channel, category, mrp_sales, gross_sales, quantity_sold, orders) | MRP (authoritative), gross, quantity, orders |
| `Executive_Weekly_Gross_Sales` (sales_date, channel, category, gross_sales; updated weekly by hand) | gross where the master's gross is NULL |
| `Executive_Spends_Master` (spend_date, channel, spend) | ad spends; ignore `source` |
| `AOP_Daily_Target_vs_Achievement` (sales_date DATETIME, Channel, Target_Revenue, Achieved_Revenue) | daily target (Day view) and **achieved** |
| `AOP_targets` (Financial_Year e.g. '2026-27', Month, Channel, Revenue, product columns) | month AOP and year AOP |

## Business rules (agreed with the owner)

- Unloaded days are NULL, never zero. NULL stays NULL end to end (sums use `min_count=1`).
- **Freebie categories** (Consumables, Freebie, Primary, Uncategorised, any spelling) are dropped at load
  from everything, including MRP. Owner hasn't confirmed whether MRP should keep them.
- **Gross fallback:** sales master -> weekly table -> MRP x (1 - channel's discount over its last 28 days of
  actuals, per category) -> MRP x (1 - 11%) if the channel has no gross history.
- **Net sales** = gross / 1.18.
- **AOV:** orders where the sales master has them; elsewhere quantity counts as orders, so AOV = ASP.
  Orders data is unreliable; no orders column is shown. **Website and EBO(Stores) never use
  Executive_Sales_Master's own `orders`** -- it's per category row, so summing it across a channel
  double-counts any order whose lines span more than one category. Their orders come straight from
  `shopify_kimirica.master_orders_flat` (`BQ_ORDERS_TABLE`), one row per real order (`metrics.
  channel_daily`'s `orders_override`, wired from `bigquery.fetch_website_ebo_orders`). Only applies
  to the unfiltered, whole-channel view; a single-category slice keeps its own category-allocated
  orders, which are already correct for that narrower case.
- **Growth** is measured on MRP sales everywhere.
- **AOP is on MRP.** Year AOP = `SUM(Revenue) WHERE Financial_Year = '2026-27'` across all channels
  (unless filtered). Month AOP = that month's Revenue. **Achieved = MRP sales, channel-wise, from
  Executive_Sales_Master up to the selected date** (`metrics.achieved_series`) -- NOT
  `AOP_Daily_Target_vs_Achievement`'s `Achieved_Revenue`. That daily table only carries a combined
  "Amazon" row (no Amazon-SC / Amazon-VC split) and is missing several plan-only channels entirely,
  so it can't represent the FY26-27 plan's per-channel breakdown; MRP sales can, and it's what the
  plan is measured against anyway. The Day view of the AOP-vs-actual chart still takes its *target*
  from the daily table's `Target_Revenue` (no daily figure exists in the monthly AOP plan), but its
  achieved figure is MRP sales too, same as everywhere else. Projected = achieved extended at the
  current daily pace. Channel/table achievement is coloured against the share of time elapsed, not
  against 100%.
- **Amazon-VC** lags ~1 day; its latest date is detected at runtime and its current and comparison windows
  end on that day number. Only flagged if later than its usual 1 day.
- **Periods:** View = Month (default, this month to date) / Financial year / Custom. Compare = Previous
  period (LMTD for a month to date, full previous month for a completed month, previous FY same days,
  or for Custom the same dates one month earlier, or the same dates last year if the range spans more than one month) /
  Custom (owner picks the comparison dates directly) / Last year (same dates a year earlier).
- A source that ends early (ad spends currently stop in May) must not truncate anything; show a short
  note under the cards instead ("No ad spends after 31 May 2026").
- Show a red "these numbers are not real" banner whenever running on demo data or when secrets fail to parse.

## Design preferences (owner is strict about these)

- Minimal and clean. **No taglines or subtitles under headings**, no explanatory footnotes, no `*`/`†`
  markers, no "pp" (use plain % change). The only note allowed under the cards is
  "AOV is ASP for channels where order data isn't available." plus short data-coverage notes.
- Header is just the Kimirica logo, centred. No status line.
- A "Refresh data" button sits at the very bottom of the page (after Highlights/Needs attention),
  clears all caches and reruns. Owner reversed the earlier "no refresh button" rule -- keep it there.
- All KPI cards the same size: 4 x 2 grid (MRP, gross, net, discount / quantity, AOV, ASP, ad spends).
- Pacing ("Current month trend" / "Current FY trend"): month and year panels side by side; AOP, achieved,
  projected, pace; figures on the bar. Always describes the latest loaded month/FY to date, regardless of
  the View/date filters (same for Highlights and Needs attention).
- Monthly trend: bars, last year as faint ghost bars; tooltip shows only value, last year, YoY, MoM.
- Section order: cards, pacing, channel table, category table, what-moved + AOP vs actual,
  monthly trend, highlights + needs attention.

## Status and open items

- BigQuery connected; service account needed BigQuery Job User + Data Viewer (granted).
- Owner reported the year AOP showed 122 Cr vs their SQL total; fixed (all channels, filter on
  Financial_Year). Confirm with `check_numbers.py` section "AOP BY FINANCIAL YEAR" (diff should be 0).
- Verify channel names match across all five tables; mismatches go in `CHANNEL_ALIASES` in config.py.
- Unconfirmed: exact text format of `AOP_targets.Month` (parser handles Apr / April / Apr-26 / 2026-04 / 04).
- Always run `python check_numbers.py` after logic changes and compare with the owner's own SQL.
- **Month AOP and year AOP currently come from `aop_plan.py`, not the live `AOP_targets` BigQuery
  table.** The owner's FY26-27 plan splits Amazon into Amazon-SC / Amazon-VC / Amazon-UAE and adds
  Tata Cliq_Others; `AOP_targets` only has one combined "Amazon" row and no Tata Cliq_Others, so it
  can't represent this yet. `bigquery.load_dashboard_data` calls `aop_plan.hardcoded_aop()` instead of
  `_prepare_aop(fetch_aop_raw())`. This is FY26-27 only and is edited by hand — once `AOP_targets` is
  loaded with the same channel-level detail, switch that one line back to the live query (the swap-back
  comment is right above it in bigquery.py) and delete aop_plan.py. `check_numbers.py`'s AOP section
  still reads the live table, so it will disagree with the dashboard until then.
