"""Fixture price loader — reads a committed parquet slice into the internal
price-series schema the backtest consumes.

Spec: ``docs/specs/R1.4a-backtest.md`` § "Data". The internal contract is a
``pandas.Series`` named ``price_eur_mwh`` on a tz-aware **UTC** ``DatetimeIndex``
with a regular frequency and no gaps (conventions §1/§4). Raw ENTSO-E shapes are
*not* handled here — that adapter is R1.4b; this only loads the validated fixture.

``data`` is a leaf package: it imports nothing else in ``bess`` (import-linter).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

PRICE_COL = "price_eur_mwh"


def synthetic_day_ahead(days: int = 90, seed: int = 42) -> pd.Series:
    """Deterministic, copyright-clean NL-like hourly day-ahead series.

    A single dominant daily cycle (cheap nights, morning ramp, evening peak) with
    day-to-day level noise and an occasional solar-driven midday dip. Shaped like a
    calm month of Dutch day-ahead prices but **synthetic** — no real or third-party
    market data is committed (conventions / the no-committed-data rule). Used by the
    structural sanity gate (``tests/golden/test_sanity_band.py``) and the worked
    example (``examples/worked_example.py``) so both share one source.
    """
    rng = np.random.default_rng(seed)
    shape = np.array(
        [32, 30, 29, 28, 28, 30, 34, 40, 46, 50, 52, 50,
         47, 45, 46, 50, 57, 66, 78, 90, 94, 84, 64, 44],
        dtype=float,
    )  # fmt: skip
    idx = pd.date_range("2024-01-01", periods=days * 24, freq="1h", tz="UTC")
    out = []
    for _ in range(days):
        p = shape + rng.normal(0, 11) + rng.normal(0, 4, 24)
        if rng.random() < 0.10:  # occasional solar-driven midday dip
            p[11:15] -= rng.uniform(25, 45)
        out.append(p)
    return pd.Series(np.concatenate(out), index=idx, name=PRICE_COL)


def validate_price_series(s: pd.Series, *, source: str = "price series") -> pd.Series:
    """Validate the internal price-series schema; return the series unchanged.

    The schema (conventions §1/§4): a tz-aware **UTC** ``DatetimeIndex``, sorted
    ascending, with a single regular frequency and no gaps. Raises ``ValueError``
    naming ``source`` on any violation. Shared by the fixture loader and the
    ENTSO-E adapter (``bess.data.entsoe``) so both enforce one contract.
    """
    idx = s.index
    if not isinstance(idx, pd.DatetimeIndex):
        raise ValueError(f"{source}: index must be a DatetimeIndex, got {type(idx).__name__}")
    if idx.tz is None or str(idx.tz) != "UTC":
        raise ValueError(f"{source}: index must be tz-aware UTC, got tz={idx.tz}")
    if not idx.is_monotonic_increasing:
        raise ValueError(f"{source}: index must be sorted ascending")

    # A regular, gap-free series: every step equals the modal step.
    if len(idx) >= 2:
        steps = idx.to_series().diff().dropna()
        if steps.nunique() != 1:
            raise ValueError(
                f"{source}: gaps / irregular freq — steps seen: "
                f"{sorted(set(steps))} (expected a single regular frequency)"
            )
    return s


def load_prices(path: str | Path) -> pd.Series:
    """Load and validate a committed price fixture; return the ``price_eur_mwh`` Series.

    Raises ``ValueError`` if the schema is violated (missing column, tz-naive or
    non-UTC index, unordered index, or a gap in an otherwise regular series).
    """
    df = pd.read_parquet(path)
    if PRICE_COL not in df.columns:
        raise ValueError(f"fixture {path} is missing the {PRICE_COL!r} column")

    s = df[PRICE_COL].astype(float)
    s.name = PRICE_COL
    return validate_price_series(s, source=f"fixture {path}")
