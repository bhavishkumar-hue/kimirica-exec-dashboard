"""
Hardcoded FY 2026-27 AOP plan, owner-provided.

Used INSTEAD OF BigQuery's AOP_targets table, because that table only has one combined
"Amazon" row and no Tata Cliq_Others line, while this plan splits Amazon into SC / VC / UAE
and adds Tata Cliq. Swap back to bigquery.fetch_aop_raw() + _prepare_aop() once AOP_targets
is loaded with this same channel-level detail -- see the wiring in bigquery.load_dashboard_data.

Editing next year's plan (or correcting this one) means editing _PLAN below and redeploying,
since this bypasses the live table entirely.
"""
from __future__ import annotations

import functools

import pandas as pd

FY_START = 2026  # Financial_Year '2026-27'

# channel -> monthly Revenue (Rs), Apr 2026 through Mar 2027, in that order.
_PLAN: dict[str, list[float]] = {
    "Website":          [16857143, 19666667, 25285714, 28095238, 56190476, 36523810,
                          49166667, 56190476, 49166667, 42142857, 63214286, 49166667],
    "Amazon-SC":        [1110588, 1110588, 1110588, 1110588, 1110588, 1110588,
                          1110588, 1110588, 1249412, 1249412, 1249412, 1249412],
    "Amazon-UAE":       [1000000, 1200000, 1400000, 1600000, 1800000, 2000000,
                          2200000, 2400000, 2600000, 2800000, 3000000, 3000000],
    "Flipkart":         [832941, 971765, 1110588, 1249412, 1388235, 1527059,
                          1665882, 1735294, 1804706, 1665882, 1735294, 1665882],
    "Tata Cliq_Others": [694118, 971765, 1249412, 1527059, 2082353, 2221176,
                          3054118, 3470588, 3470588, 2776471, 3470588, 2776471],
    "Myntra":           [2776471, 3470588, 4164706, 4858824, 6941176, 6247059,
                          7635294, 7635294, 9717647, 9023529, 11105882, 9717647],
    "Smytten":          [416471, 451176, 485882, 520588, 555294, 590000,
                          624706, 659412, 694118, 694118, 694118, 555294],
    "Amazon-VC":        [31343750, 35031250, 38718750, 38718750, 46093750, 35031250,
                          55312500, 55312500, 51625000, 64531250, 48859375, 52546875],
    "Nykaa":            [16593750, 14750000, 16593750, 17515625, 20281250, 18437500,
                          23968750, 22125000, 27656250, 27656250, 27656250, 24890625],
    "Tira":             [3630769, 4538462, 4538462, 5446154, 5446154, 3630769,
                          6353846, 5446154, 5446154, 7261538, 5446154, 6353846],
    "Blinkit":          [36307692, 36307692, 36307692, 44461538, 45384615, 45384615,
                          54461538, 43569231, 47200000, 63538462, 39938462, 41753846],
    "Swiggy":           [11800000, 13485714, 15171429, 23600000, 21071429, 21071429,
                          23600000, 20228571, 21914286, 26971429, 16857143, 20228571],
    "Zepto":            [8169231, 9076923, 10892308, 14523077, 14523077, 12707692,
                          16338462, 14523077, 14523077, 19969231, 11800000, 14523077],
    "FK-Minutes":       [779392, 935271, 1091149, 1247028, 1402906, 1558785,
                          1714663, 1870542, 2026420, 2182299, 2338177, 1870542],
    "EBO(Stores)":      [1330000, 2970000, 3310000, 3780000, 6820000, 5825000,
                          8780000, 8435000, 10200000, 9725000, 11975000, 10750000],
}

_MONTHS = pd.date_range("2026-04-01", periods=12, freq="MS")

for _ch, _vals in _PLAN.items():
    assert len(_vals) == 12, f"{_ch} has {len(_vals)} months, expected 12"


@functools.cache   # parsed once per process; callers only read it
def hardcoded_aop() -> pd.DataFrame:
    """FY26-27 AOP plan as (fy_start, date, channel, aop) -- same shape as bigquery._prepare_aop()."""
    rows = [
        {"fy_start": FY_START, "date": d, "channel": ch, "aop": float(v)}
        for ch, values in _PLAN.items()
        for d, v in zip(_MONTHS, values)
    ]
    return pd.DataFrame(rows)


# Projected AOP (owner, Nov 2026): a re-forecast per channel from Jul 2026, in Rs. Months and
# channels it doesn't cover (Apr-Jun, EBO(Stores)) keep the original AOP above.
_PROJECTION_CSV = """Date,Amazon-VC,Nykaa,Tira,Blinkit,Swiggy,Zepto,FK-Minutes,Website,Amazon-SC,Amazon-UAE,Flipkart,Tata Cliq_Others,Myntra,Smytten
01-07-2026,19500000,15000000,4200000,23800000,4700000,3800000,100000,18500000,700000,800000,800000,100000,1100000,100000
01-08-2026,28000000,15000000,5400000,45000000,13000000,15000000,500000,29000000,800000,1000000,1000000,100000,2000000,100000
01-09-2026,25000000,15000000,5000000,27000000,6000000,6000000,1000000,30000000,800000,1500000,1530000,250000,2200000,800000
01-10-2026,30000000,15000000,6000000,52000000,8000000,10000000,800000,40000000,1110000,1500000,1527059,416471,2082353,277647
01-11-2026,25000000,20000000,5000000,45000000,9000000,9000000,1000000,30010311,800000,1500000,2010924,720000,1800000,0
01-12-2026,35000000,17000000,7000000,60000000,12000000,12000000,1000000,33011342,800000,1800000,2010924,720000,1800000,4320000
01-01-2027,35000000,17000000,6000000,45000000,6500000,6500000,800000,49517012,800000,1500000,2010924,720000,2160000,5040000
01-02-2027,45000000,24000000,7000000,60000000,18000000,18000000,1500000,39613610,800000,1800000,2010924,720000,2700000,6120000
01-03-2027,35000000,16000000,6000000,45000000,7000000,7000000,800000,30898616,800000,1500000,2010924,720000,2160000,4660000"""


@functools.cache
def projected_aop() -> pd.DataFrame:
    """Projected AOP in the same shape as hardcoded_aop(): the re-forecast where given, AOP elsewhere."""
    import io
    wide = pd.read_csv(io.StringIO(_PROJECTION_CSV))
    wide["date"] = pd.to_datetime(wide.pop("Date"), format="%d-%m-%Y")
    proj = wide.melt(id_vars="date", var_name="channel", value_name="proj")
    out = hardcoded_aop().merge(proj, on=["date", "channel"], how="outer")
    out["fy_start"] = FY_START
    out["aop"] = out["proj"].where(out["proj"].notna(), out["aop"]).astype(float)
    return out.drop(columns="proj")
