"""Carga del corpus semilla (§6.1).

Los 26 episodios de config/seed_events.yaml entran al archivo con la foto del
mercado previa al evento y el regimen vigente en esa fecha, ambos calculados
point-in-time.

Sobre dos campos que podrian mentir:

- `ingested_at_utc` se iguala a `occurred_at_utc`. Poner la fecha de carga real
  haria que cada episodio semilla figure con quince anios de latencia.
- `lag_minutes` queda en NULL. Un episodio semilla no se ingirio de un feed, asi
  que no tiene latencia medida. NULL es "no medido", que es la verdad; cero seria
  afirmar que llego instantaneo.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Any

import yaml

from classify import regime as regime_mod
from classify.event_types import EVENT_TYPE_NAMES
from pit import market_state as ms_mod
from pit.guards import as_of as as_of_ctx

DEFAULT_SEED_PATH = "config/seed_events.yaml"


@dataclass(frozen=True)
class SeedEvent:
    event_id: str
    occurred_at: datetime
    event_type: str
    severity: int
    headline: str
    description: str
    entities: list[str]
    post_cierre: bool = False


class SeedError(ValueError):
    """El archivo semilla tiene un episodio mal formado."""


def load_seed_file(path: str = DEFAULT_SEED_PATH) -> list[SeedEvent]:
    with open(path, encoding="utf-8") as handle:
        crudo = yaml.safe_load(handle)

    eventos: list[SeedEvent] = []
    vistos: set[str] = set()
    for entrada in crudo.get("eventos", []):
        event_id = entrada["id"]
        if event_id in vistos:
            raise SeedError(f"id repetido en el corpus semilla: {event_id}")
        vistos.add(event_id)

        tipo = entrada["tipo"]
        if tipo not in EVENT_TYPE_NAMES:
            raise SeedError(f"{event_id}: clase de evento desconocida {tipo}")
        severidad = int(entrada["severidad"])
        if not 1 <= severidad <= 5:
            raise SeedError(f"{event_id}: severidad {severidad} fuera de 1-5")

        hora, minuto = (int(p) for p in str(entrada["hora_utc"]).split(":"))
        fecha = entrada["fecha"]
        if isinstance(fecha, str):
            fecha = date.fromisoformat(fecha)

        eventos.append(
            SeedEvent(
                event_id=event_id,
                occurred_at=datetime.combine(fecha, time(hora, minuto), tzinfo=timezone.utc),
                event_type=tipo,
                severity=severidad,
                headline=entrada["titular"],
                description=entrada.get("descripcion", ""),
                entities=list(entrada.get("entidades", [])),
                post_cierre=bool(entrada.get("post_cierre", False)),
            )
        )
    return eventos


def insert_event(
    conn: sqlite3.Connection,
    evento: SeedEvent,
    universe: dict[str, Any],
) -> dict[str, Any]:
    """Inserta un episodio con su market_state y su regimen. Devuelve el _meta
    del market_state, que dice cuanta cobertura de datos hubo."""
    with as_of_ctx(evento.occurred_at):
        estado = ms_mod.build_market_state(conn, evento.occurred_at, universe)

    regimen = regime_mod.regime_at(conn, evento.occurred_at.date())
    marca = evento.occurred_at.strftime("%Y-%m-%dT%H:%M:%SZ")

    conn.execute(
        """INSERT OR REPLACE INTO events_archive
           (event_id, occurred_at_utc, ingested_at_utc, lag_minutes, event_type, headline,
            description, entities_json, severity, surprise_direction, regime_id,
            market_state_json, source, source_tier, duplicate_count, is_seed, auto_detected)
           VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?, 'NO_CONSENSUS', ?, ?, 'corpus_semilla', 'TIER1', 1, 1, 0)""",
        (
            evento.event_id,
            marca,
            marca,
            evento.event_type,
            evento.headline,
            evento.description,
            json.dumps(evento.entities, ensure_ascii=False),
            evento.severity,
            regimen["regime_id"] if regimen else None,
            json.dumps(estado, ensure_ascii=False),
        ),
    )
    return estado["_meta"]


def load_corpus(
    conn: sqlite3.Connection,
    universe: dict[str, Any],
    *,
    path: str = DEFAULT_SEED_PATH,
) -> dict[str, Any]:
    """Carga el corpus entero. Devuelve un resumen con la cobertura real."""
    eventos = load_seed_file(path)
    sin_regimen: list[str] = []
    cobertura: list[float] = []

    for evento in eventos:
        meta = insert_event(conn, evento, universe)
        cobertura.append(meta["coverage"])
        if regime_mod.regime_at(conn, evento.occurred_at.date()) is None:
            sin_regimen.append(evento.event_id)

    return {
        "cargados": len(eventos),
        "sin_regimen": sin_regimen,
        "cobertura_market_state_promedio": round(sum(cobertura) / len(cobertura), 3) if cobertura else 0.0,
        "desde": min(e.occurred_at for e in eventos).date().isoformat() if eventos else None,
        "hasta": max(e.occurred_at for e in eventos).date().isoformat() if eventos else None,
    }


def reassign_regimes(conn: sqlite3.Connection) -> int:
    """Reasigna `regime_id` a los eventos ya cargados. Se corre despues de
    construir la linea de tiempo, cuando el corpus se cargo antes que ella."""
    actualizados = 0
    for row in conn.execute("SELECT event_id, occurred_at_utc FROM events_archive").fetchall():
        cuando = datetime.fromisoformat(row["occurred_at_utc"].replace("Z", "+00:00")).date()
        regimen = regime_mod.regime_at(conn, cuando)
        if regimen is None:
            continue
        cursor = conn.execute(
            "UPDATE events_archive SET regime_id = ? WHERE event_id = ? AND (regime_id IS NULL OR regime_id <> ?)",
            (regimen["regime_id"], row["event_id"], regimen["regime_id"]),
        )
        actualizados += cursor.rowcount
    return actualizados


def stats(conn: sqlite3.Connection) -> dict[str, list[sqlite3.Row]]:
    return {
        "por_tipo": conn.execute(
            """SELECT event_type, COUNT(*) AS n, ROUND(AVG(severity), 1) AS sev
               FROM events_archive GROUP BY event_type ORDER BY n DESC"""
        ).fetchall(),
        "por_origen": conn.execute(
            """SELECT is_seed, auto_detected, COUNT(*) AS n
               FROM events_archive GROUP BY is_seed, auto_detected"""
        ).fetchall(),
        "por_regimen": conn.execute(
            """SELECT COALESCE(r.regime_label, 'SIN REGIMEN') AS regimen, COUNT(*) AS n
               FROM events_archive e LEFT JOIN regimes r ON e.regime_id = r.regime_id
               GROUP BY regimen ORDER BY n DESC"""
        ).fetchall(),
        "sin_outcomes": conn.execute(
            """SELECT e.event_id FROM events_archive e
               LEFT JOIN outcomes o ON o.event_id = e.event_id
               WHERE o.event_id IS NULL ORDER BY e.occurred_at_utc"""
        ).fetchall(),
    }
