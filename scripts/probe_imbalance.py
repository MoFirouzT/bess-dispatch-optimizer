#!/usr/bin/env python3
"""Probe the ENTSO-E imbalance endpoints for BE/NL, before R3.1 has a spec.

CLAUDE.md §7: do not invent the ENTSO-E schema from memory, fetch and print a real
sample first. R3.1 (imbalance-settlement recourse) would price the delivery gap the
bid-curve study measured and left uncharged, but nothing here has ever read an
imbalance endpoint. Whether NL and BE are actually populated on them, at what
resolution, and how far back, decides the gate wording, so it is asked before the
spec is written rather than discovered halfway through it.

**This script answers questions; it does not assert.** It prints what came back and
leaves the judgement to the reader. Nothing is cached and nothing is written.

The four questions, in the order they can kill the phase:

1. **Does the endpoint return anything for BE and NL?** entsoe-py exposes the queries
   for every area; being exposed is not being populated.
2. **What is the schema?** NL settles a single price per ISP with corrections; BE adds
   an incentivising *alpha* component during large system imbalance
   (`docs/market_reference.md`). Those are different column shapes and neither is
   guessable, which is the whole reason for this probe.
3. **What resolution?** The imbalance settlement period is 15 minutes in both zones.
   A series that comes back hourly means something else is being measured.
4. **How far back?** The value studies score 260 delivery days across 2022 to 2025. An
   imbalance record that starts in 2024 cannot be scored on that span, and the gate
   has to say so up front instead of shrinking the window later.

Run (needs `ENTSOE_API_TOKEN`, see `.env.example`)::

    uv run python scripts/probe_imbalance.py
    uv run python scripts/probe_imbalance.py --zones NL

The Transparency Platform migrated to new infrastructure on 2026-09-02 and nothing in
this repo has fetched against it, so a failure here may be the migration rather than
the data. Re-run before reading a null as an answer.
"""

from __future__ import annotations

import argparse
import os
import traceback

import pandas as pd
from entsoe import EntsoePandasClient

# Each entry is (label, method name). Ordered by how much R3.1 needs it: the
# settlement price is the phase, the rest is context.
ENDPOINTS = [
    ("imbalance prices", "query_imbalance_prices"),
    ("imbalance volumes", "query_imbalance_volumes"),
    ("current balancing state", "query_current_balancing_state"),
    ("activated balancing energy prices", "query_activated_balancing_energy_prices"),
]

# Windows chosen to separate "the endpoint is dead" from "the history is short", and
# to straddle the 2025-10-01 switch to a 15-minute market time unit.
WINDOWS = [
    ("recent", "2026-08-01", "2026-08-08"),
    ("post 15-min switch", "2025-11-01", "2025-11-08"),
    ("value-study span", "2024-04-01", "2024-04-08"),
    ("2022 crisis year", "2022-08-01", "2022-08-08"),
]

SEPARATOR = "=" * 78


def describe(df: pd.DataFrame | pd.Series) -> list[str]:
    """What came back, in the terms the four questions are asked in."""
    if isinstance(df, pd.Series):
        df = df.to_frame(name=df.name or "value")
    if df.empty:
        return ["  EMPTY: the call succeeded and returned no rows"]

    lines = [f"  rows={len(df)}  columns={list(df.columns)}"]
    lines.append(f"  dtypes: {dict(df.dtypes.astype(str))}")

    index = df.index
    if isinstance(index, pd.DatetimeIndex):
        step = index.to_series().diff().dropna()
        steps = sorted({str(s) for s in step.unique()})
        lines.append(f"  index: tz={index.tz}  {index[0]} .. {index[-1]}")
        lines.append(f"  step(s) present: {steps[:5]}{' ...' if len(steps) > 5 else ''}")
    else:
        lines.append(f"  index is {type(index).__name__}, not a DatetimeIndex")

    nulls = df.isna().mean()
    worst = nulls.sort_values(ascending=False)
    lines.append(f"  NaN fraction, worst columns: {worst.head(4).round(3).to_dict()}")
    lines.append("  head:")
    lines += ["    " + line for line in df.head(3).to_string().splitlines()]
    return lines


def probe(client: EntsoePandasClient, zone: str, method: str, start: str, end: str) -> list[str]:
    """One call. Any failure is reported and swallowed: a probe never stops early."""
    try:
        result = getattr(client, method)(
            zone,
            start=pd.Timestamp(start, tz="Europe/Brussels"),
            end=pd.Timestamp(end, tz="Europe/Brussels"),
        )
    except Exception as exc:  # noqa: BLE001 - the failure mode *is* the finding
        detail = traceback.format_exc().strip().splitlines()[-1]
        return [f"  FAILED: {type(exc).__name__}: {detail[:160]}"]
    return describe(result)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zones", nargs="+", default=["NL", "BE"])
    parser.add_argument("--windows", nargs="+", default=[w[0] for w in WINDOWS])
    args = parser.parse_args()

    token = os.environ.get("ENTSOE_API_TOKEN")
    if not token:
        raise SystemExit("ENTSOE_API_TOKEN is not set; see .env.example. No token, no probe.")
    client = EntsoePandasClient(api_key=token)

    windows = [w for w in WINDOWS if w[0] in args.windows]
    for zone in args.zones:
        for label, method in ENDPOINTS:
            print(f"\n{SEPARATOR}\n{zone}  {label}  ({method})\n{SEPARATOR}")
            for window_label, start, end in windows:
                print(f"\n-- {window_label}: {start} .. {end}")
                for line in probe(client, zone, method, start, end):
                    print(line)

    print(f"\n{SEPARATOR}\nRead the output against the four questions in this file's docstring.")
    print("Record the answers in the R3.1 spec before writing its gate, not after.")


if __name__ == "__main__":
    main()
