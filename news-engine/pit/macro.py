"""Macro point-in-time con vintages de ALFRED (§2.1b).

FRED devuelve la serie revisada de hoy. ALFRED devuelve lo que se publico en una
fecha dada. El payroll se revisa dos veces y el PBI tres: el numero que movio al
mercado el dia del release casi nunca es el que hoy figura en la base.

Para analisis historico se usa ALFRED. Siempre. `get_macro_as_known_at()` es la
unica puerta de lectura y devuelve el vintage vigente a la fecha pedida.

Endpoint: mismo host que FRED, `output_type=2` (all vintages) sobre
/fred/series/observations. Requiere FRED_API_KEY.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from core.clock import format_utc, now
from pit.guards import require_visible

ALFRED_URL = "https://api.stlouisfed.org/fred/series/observations"
DEFAULT_TIMEOUT = 60.0

# Series minimas para regimenes (§4) y market_state (§7.2).
CORE_SERIES = (
    "CPIAUCSL",       # CPI headline
    "CPILFESL",       # core CPI
    "UNRATE",
    "PAYEMS",
    "DGS10",
    "DGS2",
    "DFF",            # fed funds efectiva
    "BAMLH0A0HYM2",   # HY OAS
    "GDPC1",
)


class MacroDataError(RuntimeError):
    """Falta el dato macro pedido, o falta la credencial para traerlo."""


@dataclass(frozen=True)
class MacroObservation:
    series_id: str
    obs_date: date
    vintage_date: date
    value: float | None


# ---------------------------------------------------------------------------
# Escritura
# ---------------------------------------------------------------------------


def upsert_observations(conn: sqlite3.Connection, rows: list[MacroObservation], source: str = "alfred") -> int:
    fetched = format_utc(now())
    payload = [
        (row.series_id, row.obs_date.isoformat(), row.vintage_date.isoformat(), row.value, source, fetched)
        for row in rows
    ]
    conn.executemany(
        """INSERT OR REPLACE INTO macro_observations
           (series_id, obs_date, vintage_date, value, source, fetched_at_utc)
           VALUES (?, ?, ?, ?, ?, ?)""",
        payload,
    )
    return len(payload)


# ---------------------------------------------------------------------------
# Lectura point-in-time
# ---------------------------------------------------------------------------


def get_macro_as_known_at(
    conn: sqlite3.Connection,
    series_id: str,
    obs_date: date,
    as_of: datetime,
) -> float | None:
    """Valor de `series_id` para el periodo `obs_date`, tal como se conocia en
    `as_of`. None si a esa fecha el dato todavia no se habia publicado.

    Devolver None es informacion: significa "el mercado todavia no lo sabia".
    """
    row = conn.execute(
        """SELECT vintage_date, value FROM macro_observations
           WHERE series_id = ? AND obs_date = ? AND vintage_date <= ?
           ORDER BY vintage_date DESC LIMIT 1""",
        (series_id, obs_date.isoformat(), as_of.date().isoformat()),
    ).fetchone()
    if row is None:
        return None

    require_visible("macro", f"{series_id}@{obs_date.isoformat()}", date.fromisoformat(row["vintage_date"]))
    return None if row["value"] is None else float(row["value"])


def get_latest_macro_as_known_at(
    conn: sqlite3.Connection,
    series_id: str,
    as_of: datetime,
    *,
    max_staleness_days: int | None = None,
) -> tuple[date, float] | None:
    """Ultima observacion publicada de la serie a la fecha `as_of`.

    Para CPI en marzo de 2020 esto devuelve el dato de febrero, no el de marzo:
    el de marzo todavia no existia.
    """
    row = conn.execute(
        """SELECT obs_date, value, MAX(vintage_date) AS vintage_date
           FROM macro_observations
           WHERE series_id = ? AND vintage_date <= ? AND value IS NOT NULL
           GROUP BY obs_date
           ORDER BY obs_date DESC LIMIT 1""",
        (series_id, as_of.date().isoformat()),
    ).fetchone()
    if row is None:
        return None

    obs_date = date.fromisoformat(row["obs_date"])
    if max_staleness_days is not None and (as_of.date() - obs_date).days > max_staleness_days:
        return None

    require_visible("macro", f"{series_id}@latest", date.fromisoformat(row["vintage_date"]))
    return obs_date, float(row["value"])


def get_revision_history(conn: sqlite3.Connection, series_id: str, obs_date: date) -> list[MacroObservation]:
    """Todos los vintages de una observacion. Sirve para ver cuanto se reviso."""
    rows = conn.execute(
        """SELECT vintage_date, value FROM macro_observations
           WHERE series_id = ? AND obs_date = ? ORDER BY vintage_date""",
        (series_id, obs_date.isoformat()),
    ).fetchall()
    return [
        MacroObservation(
            series_id=series_id,
            obs_date=obs_date,
            vintage_date=date.fromisoformat(row["vintage_date"]),
            value=None if row["value"] is None else float(row["value"]),
        )
        for row in rows
    ]


def series_change_as_known_at(
    conn: sqlite3.Connection,
    series_id: str,
    as_of: datetime,
    *,
    months: int,
) -> float | None:
    """Cambio absoluto de la serie en los ultimos `months` meses, con los datos
    publicados a `as_of`. Lo usa el clasificador de regimen (§4)."""
    latest = get_latest_macro_as_known_at(conn, series_id, as_of)
    if latest is None:
        return None
    latest_date, latest_value = latest

    target = latest_date - timedelta(days=30 * months)
    row = conn.execute(
        """SELECT obs_date, value, MAX(vintage_date) AS vintage_date
           FROM macro_observations
           WHERE series_id = ? AND vintage_date <= ? AND obs_date <= ? AND value IS NOT NULL
           GROUP BY obs_date ORDER BY obs_date DESC LIMIT 1""",
        (series_id, as_of.date().isoformat(), target.isoformat()),
    ).fetchone()
    if row is None:
        return None

    require_visible("macro", f"{series_id}@-{months}m", date.fromisoformat(row["vintage_date"]))
    return latest_value - float(row["value"])


# ---------------------------------------------------------------------------
# Cargador ALFRED
# ---------------------------------------------------------------------------


def parse_alfred_response(series_id: str, payload: dict) -> list[MacroObservation]:
    """`output_type=2` devuelve una fila por observacion y columnas
    `<series>_<YYYYMMDD>` por vintage. Un '.' es dato faltante, no cero."""
    observations = payload.get("observations")
    if observations is None:
        raise MacroDataError(f"respuesta de ALFRED sin 'observations' para {series_id}: {str(payload)[:160]}")

    rows: list[MacroObservation] = []
    for record in observations:
        obs_date = date.fromisoformat(record["date"])
        for key, raw in record.items():
            if key == "date" or "_" not in key:
                continue
            stamp = key.rsplit("_", 1)[-1]
            if len(stamp) != 8 or not stamp.isdigit():
                continue
            vintage = date(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:8]))
            if vintage < obs_date:
                # ALFRED no deberia devolver esto; si pasa, el dato es inutilizable.
                continue
            text = (raw or "").strip()
            rows.append(
                MacroObservation(
                    series_id=series_id,
                    obs_date=obs_date,
                    vintage_date=vintage,
                    value=None if text in (".", "") else float(text),
                )
            )
    return rows


def fetch_alfred(
    series_id: str,
    *,
    start: date,
    end: date,
    api_key: str | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> list[MacroObservation]:
    import httpx

    key = api_key or os.environ.get("FRED_API_KEY", "")
    if not key:
        raise MacroDataError("falta FRED_API_KEY en .env: sin credencial no hay vintages")

    params = {
        "series_id": series_id,
        "api_key": key,
        "file_type": "json",
        "observation_start": start.isoformat(),
        "observation_end": end.isoformat(),
        "output_type": 2,  # todos los vintages
    }
    response = httpx.get(ALFRED_URL, params=params, timeout=timeout)
    response.raise_for_status()
    return parse_alfred_response(series_id, response.json())


def load_macro(
    conn: sqlite3.Connection,
    series: list[str],
    start: date,
    end: date,
    *,
    vintages: bool = True,
) -> "LoadReport":
    """Carga series de ALFRED. `vintages=False` no esta implementado a proposito:
    cargar la serie revisada de hoy en esta tabla contaminaria el archivo (§2.1b)."""
    from pit.prices import LoadReport

    if not vintages:
        raise MacroDataError(
            "load_macro exige --vintages: la serie revisada de hoy no sirve para analisis historico (§2.1b)"
        )

    report = LoadReport(written={}, errors={})
    for series_id in series:
        try:
            observations = fetch_alfred(series_id, start=start, end=end)
            report.written[series_id] = upsert_observations(conn, observations)
        except Exception as exc:  # noqa: BLE001 - una serie que falla no corta el resto
            report.errors[series_id] = f"{type(exc).__name__}: {exc}"
    return report


def macro_coverage(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT series_id,
                  COUNT(*) AS filas,
                  COUNT(DISTINCT obs_date) AS observaciones,
                  COUNT(DISTINCT vintage_date) AS vintages,
                  MIN(obs_date) AS desde, MAX(obs_date) AS hasta
           FROM macro_observations GROUP BY series_id ORDER BY series_id"""
    ).fetchall()
