"""ENTSO-E day-ahead price adapter → internal price-series schema.

Spec: ``docs/specs/R1.4b-entsoe-loader.md``. Wraps **entsoe-py** (it owns EIC
mapping, the A03 carry-forward expansion, and 60/15-min handling), then
normalizes to the same internal schema the backtest consumes (``price_eur_mwh``
on a tz-aware **UTC** ``DatetimeIndex``, regular and gap-free) and validates it
with the shared ``validate_price_series`` check.

Two entry points share one normalization:

- ``fetch_day_ahead`` — live BE/NL day-ahead from the Transparency Platform
  (token-gated), with an on-disk parquet cache.
- ``parse_day_ahead_xml`` — token-free parse of a raw A44 document, for testing
  the parser against a synthetic XML sample.

No real ENTSO-E data is committed (its terms grant no public-redistribution
right; see the spec's licensing note). CI never reaches the live path.

``data`` is a leaf package: it imports nothing else in ``bess`` (import-linter).
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
from entsoe import EntsoePandasClient
from entsoe.parsers import parse_prices

from bess.data.fixtures import PRICE_COL, validate_price_series

# Scope (spec): start with the two adjacent low-countries zones. entsoe-py owns
# the EIC lookup; this set just bounds what the adapter will fetch.
_SUPPORTED_ZONES = ("BE", "NL")


def _normalize(raw: pd.Series) -> pd.Series:
    """Coerce a raw entsoe-py price Series to the internal schema (no validation)."""
    s = raw.tz_convert("UTC").sort_index().astype(float)
    s.name = PRICE_COL
    return s


def _cache_path(cache_dir: Path, zone: str, start: pd.Timestamp, end: pd.Timestamp) -> Path:
    """Deterministic parquet cache filename for one (zone, window) fetch."""
    fmt = "%Y%m%dT%H%MZ"
    stamp = f"{start.tz_convert('UTC'):{fmt}}_{end.tz_convert('UTC'):{fmt}}"
    return cache_dir / f"da_{zone}_{stamp}.parquet"


def parse_day_ahead_xml(xml_text: str) -> pd.Series:
    """Parse a raw ENTSO-E A44 publication document into the internal schema.

    Token-free entry to the same normalization ``fetch_day_ahead`` applies, used
    to test the parser against a (synthetic) XML sample. Delegates to entsoe-py's
    ``parse_prices``, which performs the A03 carry-forward expansion (a missing
    ``position`` repeats the previous price). Raises ``ValueError`` if no price
    points are present.
    """
    parsed = parse_prices(xml_text)  # {'15min'|'30min'|'60min': Series|None}
    nonempty = [s for s in parsed.values() if s is not None and len(s) > 0]
    if not nonempty:
        raise ValueError("no day-ahead price points found in the ENTSO-E document")
    raw = pd.concat(nonempty).sort_index()
    return validate_price_series(_normalize(raw), source="ENTSO-E XML")


def fetch_day_ahead(
    zone: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    *,
    api_token: str | None = None,
    cache_dir: Path | None = None,
) -> pd.Series:
    """Fetch BE/NL day-ahead prices from ENTSO-E into the internal schema.

    Returns a ``price_eur_mwh`` Series on a tz-aware UTC, regular, gap-free index
    over ``[start, end]``. ``api_token`` defaults to ``$ENTSOE_API_TOKEN``. If
    ``cache_dir`` is given, a prior fetch of the same (zone, window) is served from
    parquet without an API call (and a fresh fetch is written there).

    Raises ``ValueError`` for an unsupported zone, ``RuntimeError`` if no token is
    available, and ``ValueError`` if the fetched series fails the schema check.
    """
    zone = zone.upper()
    if zone not in _SUPPORTED_ZONES:
        raise ValueError(f"zone {zone!r} not supported; expected one of {list(_SUPPORTED_ZONES)}")
    source = f"ENTSO-E {zone} {start:%Y-%m-%d}..{end:%Y-%m-%d}"

    cache_file = None
    if cache_dir is not None:
        cache_file = _cache_path(Path(cache_dir), zone, start, end)
        if cache_file.exists():
            cached = pd.read_parquet(cache_file)[PRICE_COL].astype(float)
            cached.name = PRICE_COL
            return validate_price_series(cached, source=f"{source} (cache)")

    token = api_token or os.environ.get("ENTSOE_API_TOKEN")
    if not token:
        raise RuntimeError(
            "ENTSO-E API token required: pass api_token= or set ENTSOE_API_TOKEN "
            "(see .env.example). No token, no live fetch."
        )

    client = EntsoePandasClient(api_key=token)
    raw = client.query_day_ahead_prices(zone, start=start, end=end)
    series = validate_price_series(_normalize(raw), source=source)

    if cache_file is not None:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        series.to_frame().to_parquet(cache_file)
    return series
