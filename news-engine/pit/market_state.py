"""Foto del mercado justo antes de un evento (§7.2).

Sin esto los analogos son inutiles: una invasion con VIX en 12 no es lo mismo que
con VIX en 38.

Regla de corte: por defecto el cierre del dia habil anterior al evento. Ningun
campo puede tener fecha igual o posterior a la del evento; el cuarto test
bloqueante de §2.2 verifica exactamente eso.

Lo que no se puede medir queda en `null` y aparece listado en `_meta.missing`.
No se estima, no se rellena con el ultimo valor conocido de hace meses, y el
reporte declara la cobertura real (§5.4, §15).
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from typing import Any

import yaml

from pit import macro as macro_mod
from pit import prices as price_mod
from pit.guards import visibility_cutoff_date

DEFAULT_UNIVERSE_PATH = "config/universe.yaml"


def load_universe(path: str = DEFAULT_UNIVERSE_PATH) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def build_market_state(
    conn: sqlite3.Connection,
    as_of: datetime,
    universe: dict[str, Any],
    *,
    strict_prior_day: bool = True,
) -> dict[str, Any]:
    """Devuelve el dict que se persiste en `events_archive.market_state_json`."""
    cutoff = visibility_cutoff_date()
    if strict_prior_day:
        cutoff = min(cutoff, as_of.date() - timedelta(days=1))

    spec: dict[str, dict[str, Any]] = universe.get("market_state", {})
    state: dict[str, Any] = {}
    field_dates: dict[str, str] = {}
    missing: list[str] = []

    # --- niveles directos ---------------------------------------------------
    for field, entry in spec.items():
        kind = entry.get("kind")
        if kind == "price":
            value = _read_price(conn, entry["asset"], cutoff, as_of, field, field_dates)
        elif kind == "macro":
            value = _read_macro(conn, entry["series"], cutoff, as_of, field, field_dates,
                                max_staleness_days=entry.get("max_staleness_days", 10))
        else:
            value = None  # 'unavailable' y 'derived' se resuelven aparte
        state[field] = value
        if value is None and kind in ("price", "macro"):
            missing.append(field)
        elif kind == "unavailable":
            missing.append(field)

    # --- derivados ----------------------------------------------------------
    equity = spec.get("spx_level", {}).get("asset")
    if equity:
        state["spx_20d_return"] = _window_return(conn, equity, cutoff, as_of, sessions=20)
        state["spx_dist_from_52w_high"] = _distance_from_high(conn, equity, cutoff, as_of, sessions=252)
    dollar = spec.get("dxy", {}).get("asset")
    if dollar:
        state["dxy_60d_return"] = _window_return(conn, dollar, cutoff, as_of, sessions=60)

    if state.get("us10y") is not None and state.get("us2y") is not None:
        state["curve_2s10s"] = round(state["us10y"] - state["us2y"], 4)
    else:
        state["curve_2s10s"] = None

    for derived in ("spx_20d_return", "spx_dist_from_52w_high", "dxy_60d_return", "curve_2s10s"):
        if state.get(derived) is None and derived not in missing:
            missing.append(derived)

    faltantes = sorted(set(missing))
    state["_meta"] = {
        "as_of": as_of.isoformat().replace("+00:00", "Z"),
        "cutoff_date": cutoff.isoformat(),
        "field_dates": field_dates,
        "missing": faltantes,
        "coverage": round(1 - len(faltantes) / max(len(state), 1), 3),
    }
    return state


# ---------------------------------------------------------------------------


def _read_price(
    conn: sqlite3.Connection,
    asset: str,
    cutoff: date,
    as_of: datetime,
    field: str,
    field_dates: dict[str, str],
) -> float | None:
    try:
        found, value = price_mod.get_last_price_as_known_at(conn, asset, cutoff, as_of)
    except price_mod.PriceDataError:
        return None
    field_dates[field] = found.isoformat()
    return round(value, 4)


def _read_macro(
    conn: sqlite3.Connection,
    series_id: str,
    cutoff: date,
    as_of: datetime,
    field: str,
    field_dates: dict[str, str],
    *,
    max_staleness_days: int,
) -> float | None:
    boundary = datetime.combine(cutoff, as_of.timetz())
    result = macro_mod.get_latest_macro_as_known_at(
        conn, series_id, boundary, max_staleness_days=max_staleness_days
    )
    if result is None:
        return None
    obs_date, value = result
    field_dates[field] = obs_date.isoformat()
    return round(value, 4)


def _window_return(conn: sqlite3.Connection, asset: str, cutoff: date, as_of: datetime, *, sessions: int) -> float | None:
    days = price_mod.trading_days_before(conn, asset, cutoff, sessions + 1)
    if len(days) < sessions + 1:
        return None
    try:
        return round(price_mod.get_return_as_known_at(conn, asset, days[-1], days[0], as_of), 4)
    except price_mod.PriceDataError:
        return None


def _distance_from_high(conn: sqlite3.Connection, asset: str, cutoff: date, as_of: datetime, *, sessions: int) -> float | None:
    days = price_mod.trading_days_before(conn, asset, cutoff, sessions)
    if len(days) < 2:
        return None
    series = price_mod.get_close_series_as_known_at(conn, asset, days[-1], days[0], as_of)
    if not series:
        return None
    last = series[-1][1]
    peak = max(value for _, value in series)
    return round(last / peak - 1.0, 4)
