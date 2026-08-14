"""Precios point-in-time (§2.1a).

Regla: `prices.close_raw` no se ajusta nunca. El ajuste se calcula al leer, con
las acciones corporativas anunciadas antes del `as_of`. Un split de 2024 no puede
tocar un precio de 2018 mirado desde 2018.

Convencion de ajuste
    precio_ajustado(d, T) = close_raw(d) / prod(split_ratio_i)
    para los splits con ex_date > d anunciados antes de T.

`get_price_as_known_at()` devuelve un precio, no un retorno total: los dividendos
no se meten en el nivel de precio. Para retornos con dividendos esta
`get_total_return_as_known_at()`, que es lo que necesita el calculo de outcomes.
"""

from __future__ import annotations

import csv
import io
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from core.clock import format_utc, now
from pit.guards import require_visible

STOOQ_CSV_URL = "https://stooq.com/q/d/l/"
DEFAULT_TIMEOUT = 30.0


class PriceDataError(RuntimeError):
    """Falta el dato de precio pedido. No se interpola ni se estima."""


@dataclass(frozen=True)
class PriceRow:
    asset: str
    price_date: date
    close_raw: float
    open_raw: float | None = None
    high_raw: float | None = None
    low_raw: float | None = None
    volume: float | None = None


# ---------------------------------------------------------------------------
# Escritura
# ---------------------------------------------------------------------------


def upsert_prices(conn: sqlite3.Connection, rows: list[PriceRow], source: str) -> int:
    """Inserta o reemplaza cierres crudos. Devuelve filas escritas."""
    fetched = format_utc(now())
    payload = [
        (
            row.asset,
            row.price_date.isoformat(),
            row.close_raw,
            row.open_raw,
            row.high_raw,
            row.low_raw,
            row.volume,
            source,
            fetched,
        )
        for row in rows
    ]
    conn.executemany(
        """INSERT OR REPLACE INTO prices
           (asset, price_date, close_raw, open_raw, high_raw, low_raw, volume, source, fetched_at_utc)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        payload,
    )
    return len(payload)


def upsert_corporate_action(
    conn: sqlite3.Connection,
    *,
    asset: str,
    kind: str,
    ex_date: date,
    announced_at: datetime | None,
    split_ratio: float | None = None,
    dividend_amount: float | None = None,
    source: str = "manual",
) -> str:
    """Si la fuente no informa fecha de anuncio se usa el ex_date: atrasa el
    ajuste respecto de la realidad, que es el lado seguro."""
    announced = announced_at or datetime.combine(ex_date, time(0, 0), tzinfo=timezone.utc)
    action_id = f"{asset}:{kind}:{ex_date.isoformat()}"
    conn.execute(
        """INSERT OR REPLACE INTO corporate_actions
           (action_id, asset, kind, ex_date, announced_at_utc, split_ratio, dividend_amount,
            source, fetched_at_utc)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            action_id,
            asset,
            kind,
            ex_date.isoformat(),
            format_utc(announced),
            split_ratio,
            dividend_amount,
            source,
            format_utc(now()),
        ),
    )
    return action_id


# ---------------------------------------------------------------------------
# Lectura point-in-time
# ---------------------------------------------------------------------------


def split_factor_as_known_at(conn: sqlite3.Connection, asset: str, price_date: date, as_of: datetime) -> float:
    """Producto de los splits con ex_date > price_date anunciados antes de as_of."""
    rows = conn.execute(
        """SELECT split_ratio FROM corporate_actions
           WHERE asset = ? AND kind = 'SPLIT' AND ex_date > ? AND announced_at_utc <= ?""",
        (asset, price_date.isoformat(), format_utc(as_of)),
    ).fetchall()
    factor = 1.0
    for row in rows:
        factor *= float(row["split_ratio"])
    return factor


def get_price_as_known_at(
    conn: sqlite3.Connection,
    asset: str,
    price_date: date,
    as_of: datetime,
) -> float:
    """Precio de `asset` en `price_date`, ajustado SOLO por eventos anunciados
    antes de `as_of`. Lanza LookAheadError si price_date > as_of."""
    require_visible("price", f"{asset}@{price_date.isoformat()}", price_date)

    row = conn.execute(
        "SELECT close_raw FROM prices WHERE asset = ? AND price_date = ?",
        (asset, price_date.isoformat()),
    ).fetchone()
    if row is None:
        raise PriceDataError(f"sin cierre cargado para {asset} en {price_date.isoformat()}")

    return float(row["close_raw"]) / split_factor_as_known_at(conn, asset, price_date, as_of)


def get_last_price_as_known_at(
    conn: sqlite3.Connection,
    asset: str,
    on_or_before: date,
    as_of: datetime,
    *,
    max_staleness_days: int = 7,
) -> tuple[date, float]:
    """Ultimo cierre disponible hasta `on_or_before` (feriados, fines de semana).

    `max_staleness_days` evita que un ticker sin datos hace meses se cuele como
    si fuera el ultimo cierre: mejor faltante explicito que un numero viejo.
    """
    require_visible("price", f"{asset}@<={on_or_before.isoformat()}", on_or_before)
    row = conn.execute(
        """SELECT price_date, close_raw FROM prices
           WHERE asset = ? AND price_date <= ?
           ORDER BY price_date DESC LIMIT 1""",
        (asset, on_or_before.isoformat()),
    ).fetchone()
    if row is None:
        raise PriceDataError(f"sin cierres de {asset} hasta {on_or_before.isoformat()}")

    found = date.fromisoformat(row["price_date"])
    if (on_or_before - found).days > max_staleness_days:
        raise PriceDataError(
            f"cierre mas reciente de {asset} es {found.isoformat()}, "
            f"{(on_or_before - found).days} dias antes de {on_or_before.isoformat()}"
        )
    return found, float(row["close_raw"]) / split_factor_as_known_at(conn, asset, found, as_of)


def get_close_series_as_known_at(
    conn: sqlite3.Connection,
    asset: str,
    start: date,
    end: date,
    as_of: datetime,
) -> list[tuple[date, float]]:
    """Serie de cierres ajustados a `as_of`, de start a end inclusive."""
    require_visible("price", f"{asset}@{start.isoformat()}..{end.isoformat()}", end)
    rows = conn.execute(
        """SELECT price_date, close_raw FROM prices
           WHERE asset = ? AND price_date BETWEEN ? AND ?
           ORDER BY price_date""",
        (asset, start.isoformat(), end.isoformat()),
    ).fetchall()

    series: list[tuple[date, float]] = []
    for row in rows:
        day = date.fromisoformat(row["price_date"])
        factor = split_factor_as_known_at(conn, asset, day, as_of)
        series.append((day, float(row["close_raw"]) / factor))
    return series


def get_return_as_known_at(
    conn: sqlite3.Connection,
    asset: str,
    start_date: date,
    end_date: date,
    as_of: datetime,
) -> float:
    """Retorno de precio entre dos cierres. Sin dividendos."""
    p0 = get_price_as_known_at(conn, asset, start_date, as_of)
    p1 = get_price_as_known_at(conn, asset, end_date, as_of)
    return p1 / p0 - 1.0


def get_total_return_as_known_at(
    conn: sqlite3.Connection,
    asset: str,
    start_date: date,
    end_date: date,
    as_of: datetime,
) -> float:
    """Retorno total: precio + dividendos con ex_date en (start, end] anunciados
    antes de as_of. Los importes se ajustan por los mismos splits que el precio."""
    p0 = get_price_as_known_at(conn, asset, start_date, as_of)
    p1 = get_price_as_known_at(conn, asset, end_date, as_of)

    rows = conn.execute(
        """SELECT ex_date, dividend_amount FROM corporate_actions
           WHERE asset = ? AND kind = 'DIVIDEND'
             AND ex_date > ? AND ex_date <= ? AND announced_at_utc <= ?""",
        (asset, start_date.isoformat(), end_date.isoformat(), format_utc(as_of)),
    ).fetchall()

    dividends = 0.0
    for row in rows:
        ex_date = date.fromisoformat(row["ex_date"])
        dividends += float(row["dividend_amount"]) / split_factor_as_known_at(conn, asset, ex_date, as_of)

    return (p1 + dividends) / p0 - 1.0


def trading_days_before(conn: sqlite3.Connection, asset: str, reference: date, count: int) -> list[date]:
    """Fechas con cierre cargado, hasta `reference` inclusive, mas recientes primero.

    El calendario sale de los datos, no de una libreria de feriados: si el mercado
    no opero, no hay fila.
    """
    rows = conn.execute(
        """SELECT price_date FROM prices
           WHERE asset = ? AND price_date <= ?
           ORDER BY price_date DESC LIMIT ?""",
        (asset, reference.isoformat(), count),
    ).fetchall()
    return [date.fromisoformat(row["price_date"]) for row in rows]


# ---------------------------------------------------------------------------
# Cargadores
# ---------------------------------------------------------------------------


def parse_stooq_csv(asset: str, text: str) -> list[PriceRow]:
    """Formato stooq: Date,Open,High,Low,Close,Volume."""
    reader = csv.DictReader(io.StringIO(text.strip()))
    if reader.fieldnames is None or "Close" not in reader.fieldnames:
        raise PriceDataError(f"respuesta de stooq sin columna Close para {asset}: {text[:120]!r}")

    rows: list[PriceRow] = []
    for record in reader:
        close = _to_float(record.get("Close"))
        if close is None or close <= 0:
            continue
        rows.append(
            PriceRow(
                asset=asset,
                price_date=date.fromisoformat(record["Date"]),
                close_raw=close,
                open_raw=_to_float(record.get("Open")),
                high_raw=_to_float(record.get("High")),
                low_raw=_to_float(record.get("Low")),
                volume=_to_float(record.get("Volume")),
            )
        )
    return rows


def fetch_stooq(symbol: str, asset: str, start: date, end: date, *, timeout: float = DEFAULT_TIMEOUT) -> list[PriceRow]:
    """Descarga EOD de stooq. Sin API key. No ajusta nada: devuelve crudo."""
    import httpx

    params = {
        "s": symbol.lower(),
        "i": "d",
        "d1": start.strftime("%Y%m%d"),
        "d2": end.strftime("%Y%m%d"),
    }
    response = httpx.get(STOOQ_CSV_URL, params=params, timeout=timeout, follow_redirects=True)
    response.raise_for_status()
    if "Exceeded the daily hits limit" in response.text:
        raise PriceDataError(f"stooq rate-limited al pedir {symbol}")
    return parse_stooq_csv(asset, response.text)


@dataclass
class LoadReport:
    """Resultado de una carga. Los errores se guardan con su motivo: decir
    'fallo' sin decir por que no sirve para nada (§15)."""

    written: dict[str, int]
    errors: dict[str, str]

    @property
    def total_rows(self) -> int:
        return sum(self.written.values())

    @property
    def ok(self) -> bool:
        return not self.errors


def load_prices(
    conn: sqlite3.Connection,
    symbols: dict[str, str],
    start: date,
    end: date,
    *,
    source: str = "stooq",
) -> LoadReport:
    """Carga cierres para {asset: simbolo_en_la_fuente}.

    Un activo que falla no aborta el resto: queda registrado con su error.
    """
    if source != "stooq":
        raise PriceDataError(f"fuente de precios no implementada: {source}")

    report = LoadReport(written={}, errors={})
    for asset, symbol in symbols.items():
        try:
            rows = fetch_stooq(symbol, asset, start, end)
            report.written[asset] = upsert_prices(conn, rows, source=source)
        except Exception as exc:  # noqa: BLE001 - se reporta por activo, no corta la carga
            report.errors[asset] = f"{type(exc).__name__}: {exc}"
    return report


def load_prices_from_csv(conn: sqlite3.Connection, asset: str, path: str, *, source: str = "csv") -> int:
    """Carga manual desde un CSV con el formato de stooq. Para entornos sin red."""
    with open(path, encoding="utf-8") as handle:
        rows = parse_stooq_csv(asset, handle.read())
    return upsert_prices(conn, rows, source=source)


def price_coverage(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT asset, COUNT(*) AS n, MIN(price_date) AS desde, MAX(price_date) AS hasta, source
           FROM prices GROUP BY asset, source ORDER BY asset"""
    ).fetchall()


def last_price_date(conn: sqlite3.Connection) -> date | None:
    row = conn.execute("SELECT MAX(price_date) AS d FROM prices").fetchone()
    return date.fromisoformat(row["d"]) if row and row["d"] else None


def _to_float(value: str | None) -> float | None:
    if value is None:
        return None
    text = value.strip()
    if text in ("", "-", "."):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def business_days_ago(reference: date, days: int) -> date:
    """Aproximacion de calendario solo para acotar consultas, no para contar
    dias de mercado: para eso esta `trading_days_before()`."""
    return reference - timedelta(days=days)
