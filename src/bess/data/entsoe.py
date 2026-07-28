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

from bess.data.fixtures import PRICE_COL, validate_price_series, validate_utc_index

# Scope (spec): start with the two adjacent low-countries zones. entsoe-py owns
# the EIC lookup; this set just bounds what the adapter will fetch.
_SUPPORTED_ZONES = ("BE", "NL")

# Session-wide opt-in to the on-disk cache, for callers that do not thread a path
# through every fetch (the examples, the live integration tests, an ad-hoc script).
CACHE_DIR_ENV = "BESS_CACHE_DIR"


def _normalize(raw: pd.Series) -> pd.Series:
    """Coerce a raw entsoe-py price Series to the internal schema (no validation)."""
    s = raw.tz_convert("UTC").sort_index().astype(float)
    s.name = PRICE_COL
    return s


def _assert_spans_window(
    s: pd.Series, start: pd.Timestamp, end: pd.Timestamp, *, source: str
) -> pd.Series:
    """Reject a series that does not cover the whole requested window.

    ``validate_price_series`` only sees the series, so it catches an *interior* hole
    (a day ENTSO-E never published shows up as an irregular step) but not a series
    truncated at either end: that stays perfectly regular and validates clean. The
    requested window is the only reference that reveals it, so it is checked here.
    ENTSO-E treats ``end`` as inclusive, so a full fetch spans exactly ``[start, end]``.
    """
    if len(s) == 0:
        raise ValueError(f"{source}: no price points returned for the requested window")
    first, last = s.index[0], s.index[-1]
    if first > start or last < end:
        raise ValueError(
            f"{source}: returned {first}..{last}, which does not cover the requested "
            f"{start.tz_convert('UTC')}..{end.tz_convert('UTC')} — ENTSO-E published no "
            f"data for part of the window"
        )
    return s


def _cache_path(
    cache_dir: Path, zone: str, start: pd.Timestamp, end: pd.Timestamp, *, kind: str = "da"
) -> Path:
    """Deterministic parquet cache filename for one (kind, zone, window) fetch."""
    fmt = "%Y%m%dT%H%MZ"
    stamp = f"{start.tz_convert('UTC'):{fmt}}_{end.tz_convert('UTC'):{fmt}}"
    return cache_dir / f"{kind}_{zone}_{stamp}.parquet"


def _resolve_cache_dir(cache_dir: Path | None) -> Path | None:
    """Where this fetch caches: explicit argument, else ``$BESS_CACHE_DIR``, else nowhere.

    An explicit ``cache_dir=`` always wins, so a caller that needs a private cache (a
    test's ``tmp_path``) is never redirected by the environment. Otherwise the env var
    opts a whole session in, which is what lets the examples and the live integration
    tests share one cache without threading a path through every call site.

    Unset **or blank** means no cache, keeping the default behaviour "fetch at
    runtime, keep nothing" (so CI, which sets neither, is unaffected). Blank counts as
    unset because ``export BESS_CACHE_DIR=`` is how a shell clears a variable in
    practice, and ``Path("")`` would otherwise resolve to the current working
    directory and scatter parquet files wherever the caller happened to be.
    """
    if cache_dir is not None:
        return Path(cache_dir)
    env = os.environ.get(CACHE_DIR_ENV, "").strip()
    return Path(env) if env else None


def _resolve_token(api_token: str | None) -> str:
    token = api_token or os.environ.get("ENTSOE_API_TOKEN")
    if not token:
        raise RuntimeError(
            "ENTSO-E API token required: pass api_token= or set ENTSOE_API_TOKEN "
            "(see .env.example). No token, no live fetch."
        )
    return token


def _to_utc_hourly(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize a raw entsoe-py forecast frame to the internal UTC **hourly** grid.

    The load and wind/solar forecasts publish at 15-min resolution in zone-local
    time, while the day-ahead price is hourly. Resampling MW (a power) to hourly by
    the **mean** gives the average power over each hour, the correct aggregation to
    align a fundamentals series onto the hourly target grid.
    """
    hourly = df.tz_convert("UTC").sort_index().astype(float).resample("1h").mean()
    return hourly


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
    over ``[start, end]``. ``api_token`` defaults to ``$ENTSOE_API_TOKEN``.

    With a cache directory in play, a prior fetch of the same (zone, window) is
    served from parquet without an API call, and a fresh fetch is written there.
    ``cache_dir`` names one explicitly; otherwise ``$BESS_CACHE_DIR`` supplies it,
    and with neither set nothing is cached (see ``_resolve_cache_dir``).

    Raises ``ValueError`` for an unsupported zone, ``RuntimeError`` if no token is
    available, and ``ValueError`` if the fetched series fails the schema check or
    does not cover the whole requested window.
    """
    zone = zone.upper()
    if zone not in _SUPPORTED_ZONES:
        raise ValueError(f"zone {zone!r} not supported; expected one of {list(_SUPPORTED_ZONES)}")
    source = f"ENTSO-E {zone} {start:%Y-%m-%d}..{end:%Y-%m-%d}"

    resolved_cache_dir = _resolve_cache_dir(cache_dir)
    cache_file = None
    if resolved_cache_dir is not None:
        cache_file = _cache_path(resolved_cache_dir, zone, start, end)
        if cache_file.exists():
            cached = pd.read_parquet(cache_file)[PRICE_COL].astype(float)
            cached.name = PRICE_COL
            validate_price_series(cached, source=f"{source} (cache)")
            return _assert_spans_window(cached, start, end, source=f"{source} (cache)")

    token = api_token or os.environ.get("ENTSOE_API_TOKEN")
    if not token:
        raise RuntimeError(
            "ENTSO-E API token required: pass api_token= or set ENTSOE_API_TOKEN "
            "(see .env.example). No token, no live fetch."
        )

    client = EntsoePandasClient(api_key=token)
    raw = client.query_day_ahead_prices(zone, start=start, end=end)
    series = validate_price_series(_normalize(raw), source=source)
    _assert_spans_window(series, start, end, source=source)

    if cache_file is not None:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        series.to_frame().to_parquet(cache_file)
    return series


# --- R2.1c: exogenous day-ahead fundamentals (load + wind/solar forecasts) ---
#
# Real ENTSO-E schema, verified live 2026-07-24 against NL (build-task 1 probe):
#   query_load_forecast(zone)            -> DataFrame['Forecasted Load'], MW, 15-min, local tz
#   query_wind_and_solar_forecast(zone)  -> DataFrame['Solar','Wind Offshore',
#                                           'Wind Onshore'], MW, 15-min, local tz
# Both are **day-ahead forecasts** for day D published during D-1, so a value for a
# target hour t exists before t (the leakage-safe contemporaneous-alignment property;
# docs/decisions/forecast-feature-alignment.md). We deliberately call the *forecast* endpoints,
# never query_load (realized
# actuals), which would be look-ahead.
#
# Timing is NOT symmetric, and docs/decisions/forecast-feature-alignment.md's "Publication timing"
# table is the reference:
# the load forecast is due >=2 h before day-ahead gate closure (Reg. 543/2013 Art.
# 6(1)(b)), but wind/solar only by 18:00 on D-1, i.e. *after* the auction clears, and is
# then revised intraday (Art. 14(1)(d)). Consequences: alignment is sound for decisions
# taken after day-ahead publication (every current use), not for a decision at gate
# closure; and a historical wind/solar fetch may return a late revision rather than the
# D-1 publication, which no test here can detect.


def fetch_load_forecast(
    zone: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    *,
    api_token: str | None = None,
    cache_dir: Path | None = None,
) -> pd.Series:
    """Fetch the ENTSO-E day-ahead **load forecast** into the internal schema.

    Returns a ``load_da`` Series (MW) on a tz-aware UTC, regular, gap-free **hourly**
    index (the 15-min feed mean-resampled to the price grid). Mirrors
    ``fetch_day_ahead``: token-gated, schema-validated, and cached to parquet when
    ``cache_dir`` or ``$BESS_CACHE_DIR`` gives it somewhere to write.
    """
    zone = zone.upper()
    if zone not in _SUPPORTED_ZONES:
        raise ValueError(f"zone {zone!r} not supported; expected one of {list(_SUPPORTED_ZONES)}")
    source = f"ENTSO-E load-forecast {zone} {start:%Y-%m-%d}..{end:%Y-%m-%d}"

    resolved_cache_dir = _resolve_cache_dir(cache_dir)
    cache_file = None
    if resolved_cache_dir is not None:
        cache_file = _cache_path(resolved_cache_dir, zone, start, end, kind="loadfc")
        if cache_file.exists():
            cached = pd.read_parquet(cache_file)["load_da"].astype(float)
            validate_utc_index(cached.index, source=f"{source} (cache)")
            return cached

    client = EntsoePandasClient(api_key=_resolve_token(api_token))
    raw = client.query_load_forecast(zone, start=start, end=end)
    series = _to_utc_hourly(raw).iloc[:, 0].rename("load_da")
    validate_utc_index(series.index, source=source)

    if cache_file is not None:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        series.to_frame().to_parquet(cache_file)
    return series


def fetch_renewable_forecast(
    zone: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    *,
    api_token: str | None = None,
    cache_dir: Path | None = None,
) -> pd.DataFrame:
    """Fetch the ENTSO-E day-ahead **wind + solar generation forecast**.

    Returns a frame with columns ``[wind_da, solar_da]`` (MW) on a tz-aware UTC,
    regular, gap-free hourly index. ``wind_da`` combines every wind column
    (offshore + onshore); ``solar_da`` sums the solar column(s). Mirrors
    ``fetch_day_ahead``: token-gated, schema-validated, and cached to parquet when
    ``cache_dir`` or ``$BESS_CACHE_DIR`` gives it somewhere to write.
    """
    zone = zone.upper()
    if zone not in _SUPPORTED_ZONES:
        raise ValueError(f"zone {zone!r} not supported; expected one of {list(_SUPPORTED_ZONES)}")
    source = f"ENTSO-E wind/solar-forecast {zone} {start:%Y-%m-%d}..{end:%Y-%m-%d}"

    resolved_cache_dir = _resolve_cache_dir(cache_dir)
    cache_file = None
    if resolved_cache_dir is not None:
        cache_file = _cache_path(resolved_cache_dir, zone, start, end, kind="wsfc")
        if cache_file.exists():
            cached = pd.read_parquet(cache_file)[["wind_da", "solar_da"]].astype(float)
            validate_utc_index(cached.index, source=f"{source} (cache)")
            return cached

    client = EntsoePandasClient(api_key=_resolve_token(api_token))
    raw = client.query_wind_and_solar_forecast(zone, start=start, end=end)
    hourly = _to_utc_hourly(raw)
    wind_cols = [c for c in hourly.columns if str(c).lower().startswith("wind")]
    solar_cols = [c for c in hourly.columns if str(c).lower().startswith("solar")]
    df = pd.DataFrame(
        {
            "wind_da": hourly[wind_cols].sum(axis=1) if wind_cols else 0.0,
            "solar_da": hourly[solar_cols].sum(axis=1) if solar_cols else 0.0,
        },
        index=hourly.index,
    )
    validate_utc_index(df.index, source=source)

    if cache_file is not None:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(cache_file)
    return df


def fetch_fundamentals(
    zone: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    *,
    api_token: str | None = None,
    cache_dir: Path | None = None,
) -> pd.DataFrame:
    """Assemble the R2.1c fundamentals frame ``[load_da, wind_da, solar_da]``.

    Convenience over ``fetch_load_forecast`` + ``fetch_renewable_forecast``, inner-
    joined on the shared hourly UTC index. ``residual_load`` is not added here: it is
    derived in ``make_features`` (spec / golden oracle 1) so the feature layer owns
    the merit-order arithmetic. Feed the result to ``make_features(fundamentals=…)``.
    """
    load = fetch_load_forecast(zone, start, end, api_token=api_token, cache_dir=cache_dir)
    ren = fetch_renewable_forecast(zone, start, end, api_token=api_token, cache_dir=cache_dir)
    df = pd.concat([load, ren], axis=1, join="inner")
    validate_utc_index(df.index, source=f"ENTSO-E fundamentals {zone}")
    return df
