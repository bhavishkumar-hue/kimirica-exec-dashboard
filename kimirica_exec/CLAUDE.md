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
- **Freebie categories** (Consumables, Freebie, Primary, Secondary, Uncategorised, any spelling) are dropped at load
  from everything, including MRP. Owner hasn't confirmed whether MRP should keep them.
- **Gross fallback:** sales master -> weekly table (real category match, else spread by MRP share --
  "Unmapped" is normalized to no-category at load, so it can't falsely fail to match a real category
  elsewhere; a weekly category that never appears for that channel in the sales master, like
  Swiggy's own "Bath Body And Hair" / "Beauty And Grooming", is spread the same way -- before, all of
  Swiggy's weekly gross was dropped and it ran on the 11% default) -> this channel's own current-month discount (from whichever days that month already
  have real gross) -> MRP x (1 - channel's discount over its last 28 days of actuals, per category)
  -> MRP x (1 - 11%, or CHANNEL_DEFAULT_DISCOUNT) if the channel has no gross history at all.
  **Zepto is temporarily overridden** ahead of all of this: `config.ZEPTO_DISCOUNT_ABS` holds the
  owner's own monthly rupee discount for Apr-Sep 2026; discount% = that ÷ Zepto's own MRP that
  month. Remove once Zepto's weekly/sales-master gross is trustworthy again.
- **Gross is only ever estimated on days with real MRP.** Every estimate step is MRP x (1 - discount),
  so a day with no MRP loaded gets no gross either. A channel whose feed stops (e.g. Tira after Sept
  22) simply ends there; nothing is carried forward. Owner's call, Oct 2026 -- an earlier version
  synthesised gross for those days from the last real discount and was removed.
- **Amazon-UAE has no Discount** (`config.NO_DISCOUNT_CHANNELS`, channel table only): its MRP feed
  is still in testing, so MRP isn't trustworthy and its figures are effectively gross only. Shows
  "--"; a note explains why whenever Amazon-UAE is in scope. Same for a channel group made up only
  of such channels ("International"). Remove once its real MRP is live.
- **Ratios pair numerator and denominator.** Discount and ASP (tables via `_grouped`, KPI cards via
  `block`) only count gross from rows that also have MRP / quantity. ROAS and ad share only count
  gross over the dates ad spend covers (spend data starts partway through the FY; a full-year view
  was dividing six months of gross by one month of spend: 29x ROAS).
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
- Show a red "these numbers are not real" banner whenever running on demo data or when secrets fail to parse.
- The channel and category tables (`components/tables.py`) are each TWO `st.dataframe` calls, not
  one: `st.dataframe`'s interactive column-header sort has no way to keep one row pinned, which is
  what a Total row needs, so the Total row is a second, separate `st.dataframe` with identical
  `column_config` stacked right under the sortable one, its own header hidden via CSS (see the long
  comment in `components/theme.py`). Both use an explicit `row_height=` (`tables.ROW_HEIGHT`, 30px)
  and an exact-fit `height=` (`_fit_height`, no cap, +2px for the frame border) so neither grid ever
  scrolls vertically. Column widths come from `_col_widths`: each column gets just enough for its
  header and widest value (Total included), and `width="stretch"` spreads the spare room. Fixed
  widths made the channel table scroll sideways on 1280-1366px laptops and with Full values on.
  Verified no overflow either way, both tables, 1280-1920px, short and Full values (owner: tables
  must show everything in one view, no scrolling).

## Design preferences (owner is strict about these)

- Minimal and clean. **No taglines or subtitles under section headings** (`T.section()`), no
  explanatory footnotes, no `*`/`†` markers, no "pp" (use plain % change). The one exception is the
  main header itself -- see below. The only note allowed under the cards is exactly
  "AOV is ASP for channels where order data isn't available. Amazon-UAE discount isn't shown." --
  kept deliberately short (owner, Oct 2026); no data-coverage notes are appended to it any more
  (`metrics.coverage_notes` / `bigquery._spans` were removed along with their only caller).
- Header: Kimirica logo, centred, with "Executive Business Performance" as a small uppercase
  subheading directly under it (`.k-sub` in theme.py; owner, Oct 2026). No status line otherwise.
- "Refresh" is a small button at the very bottom of the page, right-aligned, after Highlights (owner,
  Oct 2026: at the top it was too easy to hit by accident). It uses `on_click=_refresh_data`, which
  clears every cache *before* the rerun the click triggers, so one rerun loads fresh data. Clearing
  inline and then calling `st.rerun()` meant two reruns. A toast ("Refreshing data…") is the loading
  cue, since the top-of-page spinner is off screen when the button is clicked.
- `[data-stale="true"]` is forced to full opacity in theme.py. Streamlit fades every element from the
  previous run while a rerun is in progress; a Refresh reloads BigQuery for several seconds, so the
  whole page sat washed out that long (owner called it a glitch). Now numbers swap in place.
- All KPI cards the same size: 3 x 3 grid (MRP, gross, net / discount, quantity, AOV / ASP, ad spends, ROAS).
- Pacing ("Current month trend" / "Current FY trend"): month and year panels side by side; AOP, achieved,
  projected, pace; figures on the bar. Always describes the latest loaded month/FY to date, regardless of
  the View/date filters (same for Highlights). **No "Needs attention" section** -- owner had it removed
  (Sep 2026); `metrics.watchlist()` / `insights.watchlist()` still exist but nothing calls them.
- Monthly trend: bars, last year as faint ghost bars; tooltip shows only value, last year, YoY, MoM.
- Section order: cards, pacing, channel table, category table, what-moved + AOP vs actual,
  monthly trend, highlights.
- Pacing bar has no vertical "today" tick (owner had it removed, Sep 2026) -- just the achieved/
  projected fill and the AOP/Achieved/Projected/Pace stats underneath.
- Channel performance table has an Ad spend column (money-formatted, hidden if the channel/group has
  no ad spend at all). Owner now enters Myntra/Nykaa/Tira's monthly ad spend directly into
  `Executive_Spends_Master` -- no hardcoded override in config.py (removed Sep 2026).
- Table growth column header states the actual comparison ("Growth vs LMTD" / "... vs LY" /
  "... vs Last month", from `P.cmp_short`). The MRP basis is in the column's tooltip; "(MRP)" was
  dropped from the header itself because it got truncated on laptop widths.
- Custom compare pre-fills with what "Previous period" would compare against (all of August for
  September), and its widget is keyed by the selected period so changing the month resets it.
- **Dark mode**: Streamlit detects the viewer's OS/browser preference itself (`st.context.theme`,
  confirmed via testing -- no config.toml entry, no in-app toggle since the menu is hidden).
  `components/theme.py` holds a light and a dark palette; `_apply_theme()` (called first thing in
  `inject_css()`) reassigns the module's colour names (`T.INK`, `T.POS`, ...) each rerun. Every
  other module reads them as plain attribute lookups at the point it builds CSS or a Plotly figure
  (never cached at import), so both the CSS and the charts -- which bake in real hex colours and
  can't be themed via CSS alone -- pick up the right palette automatically. Adding a new hardcoded
  hex colour anywhere instead of a `T.` token will not adapt to dark mode; don't do that.

## Status and open items

- BigQuery connected; service account needed BigQuery Job User + Data Viewer (granted).
- Owner reported the year AOP showed 122 Cr vs their SQL total; fixed (all channels, filter on
  Financial_Year). Confirm with `check_numbers.py` section "AOP BY FINANCIAL YEAR" (diff should be 0).
- Verify channel names match across all five tables; mismatches go in `CHANNEL_ALIASES` in config.py.
- Unconfirmed: exact text format of `AOP_targets.Month` (parser handles Apr / April / Apr-26 / 2026-04 / 04).
- Always run `python check_numbers.py` after logic changes and compare with the owner's own SQL.
- **Myntra has no real gross data anywhere** (found Oct 2026, investigating why its Discount showed
  a flat 11%): `Executive_Sales_Master.gross_sales` is NULL for every single Myntra row in all of
  2026 (checked Jan-Sept), and `Executive_Weekly_Gross_Sales` has never had a single Myntra row,
  checked back to 2024 (that table has only ever held Blinkit/Nykaa/Tira/Zepto, even though
  `config.WEEKLY_GROSS_CHANNELS` lists Myntra too -- it never actually reports into it). With no real
  gross anywhere to learn a rate from, `estimates.fill_gross` is correctly falling through to
  `DEFAULT_DISCOUNT` (11%) for 100% of Myntra's gross, all the time -- this is the dashboard behaving
  exactly as designed given the data it's been handed, not a dashboard bug. Owner's call (Oct 2026):
  fix the upstream pipeline/notebook so Myntra's gross actually loads, rather than hardcoding a
  manual discount in the dashboard (the FK-Minutes/Zepto-style override was offered and declined).
  Nothing to do here until that's fixed upstream.
- **Month AOP and year AOP currently come from `aop_plan.py`, not the live `AOP_targets` BigQuery
  table.** The owner's FY26-27 plan splits Amazon into Amazon-SC / Amazon-VC / Amazon-UAE and adds
  Tata Cliq_Others; `AOP_targets` only has one combined "Amazon" row and no Tata Cliq_Others, so it
  can't represent this yet. `bigquery.load_dashboard_data` calls `aop_plan.hardcoded_aop()` instead of
  `_prepare_aop(fetch_aop_raw())`. This is FY26-27 only and is edited by hand — once `AOP_targets` is
  loaded with the same channel-level detail, switch that one line back to the live query (the swap-back
  comment is right above it in bigquery.py) and delete aop_plan.py. `check_numbers.py`'s AOP section
  still reads the live table, so it will disagree with the dashboard until then.
