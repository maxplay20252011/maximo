"""Autodeteccion de episodios historicos (§6.2).

El corpus manual queda viejo. Cuando el mercado se mueve mas alla de un umbral,
paso algo, y ese algo merece estar en el archivo.

Lo que esta capa NO hace: inventar la causa. §6.2 supone un archivo de noticias
para atribuir el movimiento a un titular; ese archivo lo produce la ingesta
(Tarea 7). Mientras no exista -- o cuando existe y no hay nada en la ventana --
la deteccion guarda un candidato con la fecha y que umbral se disparo, y ahi
queda hasta que una noticia o una persona le pongan causa.

Un candidato promovido sin causa seria un evento con titular fabricado. §14.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from core.clock import format_utc, now
from pit import macro as macro_mod
from pit import prices as price_mod
from pit.guards import as_of as as_of_ctx


@dataclass
class Candidate:
    trigger_date: date
    triggers: list[str] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)

    @property
    def candidate_id(self) -> str:
        return f"auto-{self.trigger_date.isoformat()}"


def detect(
    conn: sqlite3.Connection,
    start: date,
    end: date,
    thresholds: dict[str, Any],
) -> list[Candidate]:
    """Recorre el periodo y devuelve las fechas que dispararon algun umbral."""
    config = thresholds["autodetect"]
    candidatos: dict[date, Candidate] = {}

    def anotar(dia: date, disparo: str, metrica: str, valor: float) -> None:
        cand = candidatos.setdefault(dia, Candidate(trigger_date=dia))
        if disparo not in cand.triggers:
            cand.triggers.append(disparo)
        cand.metrics[metrica] = round(valor, 6)

    # --- movimientos de precio ---------------------------------------------
    for asset in config["indices_g10"]:
        umbral = config["spx_abs_daily_return"] if asset == "SPX" else config["g10_abs_daily_return"]
        for dia, retorno in _daily_returns(conn, asset, start, end):
            if abs(retorno) > umbral:
                anotar(dia, f"{asset}_daily_move", f"{asset.lower()}_ret_1d", retorno)

    for dia, retorno in _daily_returns(conn, "VIX", start, end):
        if retorno >= config["vix_daily_change"]:
            anotar(dia, "vix_spike", "vix_ret_1d", retorno)

    # --- movimientos de tasas y credito ------------------------------------
    for dia, cambio in _daily_changes(conn, "DGS10", start, end):
        if abs(cambio) * 100 >= config["us10y_abs_change_bp"]:
            anotar(dia, "us10y_move", "us10y_change_bp", cambio * 100)

    for dia, cambio in _daily_changes(conn, "BAMLH0A0HYM2", start, end):
        if cambio * 100 >= config["hy_oas_change_bp"]:
            anotar(dia, "hy_oas_widening", "hy_oas_change_bp", cambio * 100)

    return [candidatos[dia] for dia in sorted(candidatos)]


def _daily_returns(conn: sqlite3.Connection, asset: str, start: date, end: date) -> list[tuple[date, float]]:
    """Retornos diarios ajustados, cada uno leido con as_of en su propia fecha."""
    filas = conn.execute(
        """SELECT price_date FROM prices WHERE asset = ? AND price_date BETWEEN ? AND ?
           ORDER BY price_date""",
        (asset, (start - timedelta(days=10)).isoformat(), end.isoformat()),
    ).fetchall()
    dias = [date.fromisoformat(f["price_date"]) for f in filas]

    salida: list[tuple[date, float]] = []
    for previo, actual in zip(dias, dias[1:]):
        if actual < start:
            continue
        as_of = datetime.combine(actual, time(23, 59, 59), tzinfo=timezone.utc)
        with as_of_ctx(as_of):
            try:
                salida.append((actual, price_mod.get_return_as_known_at(conn, asset, previo, actual, as_of)))
            except price_mod.PriceDataError:
                continue
    return salida


def _daily_changes(conn: sqlite3.Connection, series_id: str, start: date, end: date) -> list[tuple[date, float]]:
    """Cambios diarios absolutos de una serie macro, con el vintage de cada dia."""
    salida: list[tuple[date, float]] = []
    dia = start
    previo_valor: float | None = None
    previo_dia: date | None = None
    while dia <= end:
        as_of = datetime.combine(dia, time(23, 59, 59), tzinfo=timezone.utc)
        with as_of_ctx(as_of):
            observacion = macro_mod.get_latest_macro_as_known_at(conn, series_id, as_of, max_staleness_days=5)
        if observacion is not None:
            obs_date, valor = observacion
            if previo_valor is not None and previo_dia is not None and obs_date > previo_dia:
                salida.append((obs_date, valor - previo_valor))
            if previo_dia is None or obs_date > previo_dia:
                previo_valor, previo_dia = valor, obs_date
        dia += timedelta(days=1)
    return [(d, c) for d, c in salida if start <= d <= end]


def persist_candidates(conn: sqlite3.Connection, candidatos: list[Candidate]) -> int:
    """Guarda candidatos nuevos. No pisa los ya revisados."""
    momento = format_utc(now())
    nuevos = 0
    for cand in candidatos:
        ya = conn.execute(
            "SELECT reviewed FROM event_candidates WHERE candidate_id = ?", (cand.candidate_id,)
        ).fetchone()
        if ya is not None:
            continue
        conn.execute(
            """INSERT INTO event_candidates
               (candidate_id, trigger_date, triggers_json, metrics_json, detected_at_utc)
               VALUES (?, ?, ?, ?, ?)""",
            (
                cand.candidate_id,
                cand.trigger_date.isoformat(),
                json.dumps(cand.triggers),
                json.dumps(cand.metrics),
                momento,
            ),
        )
        nuevos += 1
    return nuevos


def find_cause(
    conn: sqlite3.Connection,
    trigger_date: date,
    thresholds: dict[str, Any],
) -> sqlite3.Row | None:
    """Noticia candidata a explicar el movimiento: severidad >= 3 en la ventana
    de -24h, rankeada por duplicate_count y tier (§6.2).

    Devuelve None mientras no haya archivo de noticias, que es el caso hasta que
    corra la ingesta.
    """
    config = thresholds["autodetect"]
    hasta = datetime.combine(trigger_date, time(23, 59, 59), tzinfo=timezone.utc)
    desde = hasta - timedelta(hours=config["news_window_hours"])

    return conn.execute(
        """SELECT n.news_id, n.title, n.published_at_utc, n.source,
                  COUNT(d.news_id) + 1 AS duplicados
           FROM raw_news n
           LEFT JOIN raw_news d ON d.duplicate_of = n.news_id
           WHERE n.duplicate_of IS NULL
             AND n.published_at_utc BETWEEN ? AND ?
           GROUP BY n.news_id
           ORDER BY duplicados DESC, n.published_at_utc
           LIMIT 1""",
        (format_utc(desde), format_utc(hasta)),
    ).fetchone()


def promote(
    conn: sqlite3.Connection,
    candidate_id: str,
    *,
    event_type: str,
    headline: str,
    occurred_at: datetime,
    severity: int,
    universe: dict[str, Any],
    note: str = "",
) -> str:
    """Convierte un candidato revisado en evento archivado (auto_detected=1).

    Exige tipo y titular explicitos: son justo los dos campos que la deteccion
    automatica no puede saber.
    """
    from history.seed import SeedEvent, insert_event

    if not headline.strip():
        raise ValueError("un evento promovido necesita titular")

    evento = SeedEvent(
        event_id=f"auto-{occurred_at.date().isoformat()}",
        occurred_at=occurred_at,
        event_type=event_type,
        severity=severity,
        headline=headline,
        description=f"Promovido desde el candidato {candidate_id}. {note}".strip(),
        entities=[],
    )
    insert_event(conn, evento, universe)
    conn.execute(
        """UPDATE events_archive SET is_seed = 0, auto_detected = 1, source = 'autodeteccion'
           WHERE event_id = ?""",
        (evento.event_id,),
    )
    conn.execute(
        """UPDATE event_candidates SET reviewed = 1, promoted_event_id = ?, review_note = ?
           WHERE candidate_id = ?""",
        (evento.event_id, note, candidate_id),
    )
    return evento.event_id


def dismiss(conn: sqlite3.Connection, candidate_id: str, note: str) -> None:
    """Marca un candidato como revisado y descartado. La nota es obligatoria:
    un descarte sin motivo no se puede auditar despues."""
    if not note.strip():
        raise ValueError("descartar un candidato exige un motivo")
    conn.execute(
        "UPDATE event_candidates SET reviewed = 1, review_note = ? WHERE candidate_id = ?",
        (note, candidate_id),
    )


def pending(conn: sqlite3.Connection, limit: int = 20) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT * FROM event_candidates WHERE reviewed = 0
           ORDER BY trigger_date DESC LIMIT ?""",
        (limit,),
    ).fetchall()


def candidate_stats(conn: sqlite3.Connection) -> sqlite3.Row:
    return conn.execute(
        """SELECT COUNT(*) AS total,
                  SUM(reviewed) AS revisados,
                  SUM(CASE WHEN promoted_event_id IS NOT NULL THEN 1 ELSE 0 END) AS promovidos
           FROM event_candidates"""
    ).fetchone()
