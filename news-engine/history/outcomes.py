"""Outcomes medidos de cada evento (§6.3).

Que hizo cada activo despues del evento, a 1, 5 y 20 sesiones, contra su
benchmark. El exceso importa mas que el retorno crudo: si XLE sube 3% y el SPX
subio 3%, la noticia energetica no explico nada.

Punto de partida (t0): el ultimo cierre anterior al evento segun la hora del
evento y el cierre de la sesion. Un evento posterior al cierre de D se mide desde
el cierre de D; uno anterior, desde el de D-1.

Todo se lee con `as_of` al final de la ventana, no con la fecha de hoy. Los
outcomes son hechos ya materializados: lo que hay que evitar es medirlos antes de
que existan, y eso lo garantiza que la ventana este completa.

Sin benchmark no hay exceso. Sin precios no hay outcome: la fila se guarda con
data_quality y los campos en NULL, nunca con un cero que despues promedia.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from statistics import pstdev
from typing import Any

from core.clock import format_utc, now
from pit import prices as price_mod
from pit.guards import as_of as as_of_ctx


@dataclass
class OutcomeRow:
    event_id: str
    asset: str
    benchmark: str | None
    ret_1d: float | None = None
    ret_5d: float | None = None
    ret_20d: float | None = None
    excess_1d: float | None = None
    excess_5d: float | None = None
    excess_20d: float | None = None
    max_drawdown_20d: float | None = None
    vol_realized_5d: float | None = None
    vol_ratio_vs_prior: float | None = None
    data_quality: str = "MISSING"


def _session_close(universe: dict[str, Any]) -> time:
    texto = universe.get("sesiones", {}).get("cierre_utc_default", "21:00")
    hora, minuto = (int(part) for part in texto.split(":"))
    return time(hora, minuto)


def _returns(serie: list[float]) -> list[float]:
    return [serie[i] / serie[i - 1] - 1.0 for i in range(1, len(serie))]


def compute_event_outcomes(
    conn: sqlite3.Connection,
    event_id: str,
    universe: dict[str, Any],
    thresholds: dict[str, Any],
    *,
    assets: list[str] | None = None,
) -> list[OutcomeRow]:
    """Calcula los outcomes de un evento para todo el universo."""
    evento = conn.execute(
        "SELECT event_id, occurred_at_utc FROM events_archive WHERE event_id = ?", (event_id,)
    ).fetchone()
    if evento is None:
        raise KeyError(f"evento inexistente: {event_id}")

    momento = datetime.fromisoformat(evento["occurred_at_utc"].replace("Z", "+00:00"))
    cierre = _session_close(universe)
    config = thresholds["outcomes"]
    horizontes = config["horizontes_sesiones"]
    universo: dict[str, dict[str, Any]] = universe.get("assets", {})
    elegidos = assets if assets is not None else list(universo)

    filas: list[OutcomeRow] = []
    for asset in elegidos:
        spec = universo.get(asset, {})
        filas.append(
            _compute_one(conn, event_id, asset, spec.get("benchmark"), momento, cierre, horizontes, config)
        )
    return filas


def _compute_one(
    conn: sqlite3.Connection,
    event_id: str,
    asset: str,
    benchmark: str | None,
    momento: datetime,
    cierre: time,
    horizontes: list[int],
    config: dict[str, Any],
) -> OutcomeRow:
    fila = OutcomeRow(event_id=event_id, asset=asset, benchmark=benchmark)

    t0 = price_mod.last_session_before(conn, asset, momento, session_close=cierre)
    if t0 is None:
        return fila
    if (momento.date() - t0).days > config["max_dias_hasta_t0"]:
        fila.data_quality = "STALE"
        return fila

    maximo = max(horizontes)
    posteriores = price_mod.trading_days_after(conn, asset, t0, maximo)
    if not posteriores:
        fila.data_quality = "MISSING"
        return fila

    # as_of al final de la ventana disponible: todo lo que se lee ya ocurrio.
    ultimo = posteriores[-1]
    as_of = datetime.combine(ultimo + timedelta(days=1), time(23, 59, 59), tzinfo=timezone.utc)

    with as_of_ctx(as_of):
        try:
            serie = [price_mod.get_price_as_known_at(conn, asset, t0, as_of)]
            for dia in posteriores:
                serie.append(price_mod.get_price_as_known_at(conn, asset, dia, as_of))
        except price_mod.PriceDataError:
            fila.data_quality = "MISSING"
            return fila

        for h in horizontes:
            if len(posteriores) >= h:
                setattr(fila, f"ret_{h}d", round(serie[h] / serie[0] - 1.0, 6))

        ventana = serie[: min(len(serie), maximo + 1)]
        pico = ventana[0]
        peor = 0.0
        for valor in ventana:
            pico = max(pico, valor)
            peor = min(peor, valor / pico - 1.0)
        fila.max_drawdown_20d = round(peor, 6)

        if len(serie) >= 6:
            fila.vol_realized_5d = round(pstdev(_returns(serie[:6])), 6)
            previos = price_mod.trading_days_before(
                conn, asset, t0, config["ventana_vol_previa_sesiones"] + 1
            )
            if len(previos) >= 3:
                base = [price_mod.get_price_as_known_at(conn, asset, dia, as_of) for dia in reversed(previos)]
                vol_previa = pstdev(_returns(base))
                if vol_previa > 0:
                    fila.vol_ratio_vs_prior = round(fila.vol_realized_5d / vol_previa, 4)

        if benchmark:
            for h in horizontes:
                propio = getattr(fila, f"ret_{h}d")
                if propio is None:
                    continue
                referencia = _benchmark_return(conn, benchmark, t0, h, as_of)
                if referencia is not None:
                    setattr(fila, f"excess_{h}d", round(propio - referencia, 6))

    completos = sum(1 for h in horizontes if getattr(fila, f"ret_{h}d") is not None)
    if completos == len(horizontes):
        fila.data_quality = "OK" if benchmark else "NO_BENCHMARK"
    elif completos:
        fila.data_quality = "PARTIAL"
    else:
        fila.data_quality = "MISSING"
    return fila


def _benchmark_return(
    conn: sqlite3.Connection, benchmark: str, t0: date, sesiones: int, as_of: datetime
) -> float | None:
    """El benchmark se mide sobre SU propio calendario, anclado al mismo t0."""
    dias = price_mod.trading_days_after(conn, benchmark, t0, sesiones)
    if len(dias) < sesiones:
        return None
    try:
        return price_mod.get_return_as_known_at(conn, benchmark, t0, dias[-1], as_of)
    except price_mod.PriceDataError:
        return None


def persist(conn: sqlite3.Connection, filas: list[OutcomeRow]) -> int:
    momento = format_utc(now())
    conn.executemany(
        """INSERT OR REPLACE INTO outcomes
           (event_id, asset, benchmark, ret_1d, ret_5d, ret_20d,
            excess_1d, excess_5d, excess_20d, max_drawdown_20d,
            vol_realized_5d, vol_ratio_vs_prior, computed_at, data_quality)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            (
                f.event_id, f.asset, f.benchmark, f.ret_1d, f.ret_5d, f.ret_20d,
                f.excess_1d, f.excess_5d, f.excess_20d, f.max_drawdown_20d,
                f.vol_realized_5d, f.vol_ratio_vs_prior, momento, f.data_quality,
            )
            for f in filas
        ],
    )
    return len(filas)


def compute_all(
    conn: sqlite3.Connection,
    universe: dict[str, Any],
    thresholds: dict[str, Any],
    *,
    event_ids: list[str] | None = None,
) -> dict[str, dict[str, int]]:
    """Calcula y persiste outcomes. Devuelve el conteo por calidad y por evento."""
    if event_ids is None:
        event_ids = [
            row["event_id"]
            for row in conn.execute("SELECT event_id FROM events_archive ORDER BY occurred_at_utc")
        ]

    resumen: dict[str, dict[str, int]] = {}
    for event_id in event_ids:
        filas = compute_event_outcomes(conn, event_id, universe, thresholds)
        persist(conn, filas)
        conteo: dict[str, int] = {}
        for fila in filas:
            conteo[fila.data_quality] = conteo.get(fila.data_quality, 0) + 1
        resumen[event_id] = conteo
    return resumen


def quality_summary(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT data_quality, COUNT(*) AS n FROM outcomes GROUP BY data_quality ORDER BY n DESC"
    ).fetchall()
