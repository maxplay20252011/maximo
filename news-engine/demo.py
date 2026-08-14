"""Modo demo: la cadena completa sobre datos INVENTADOS.

Para que sirve: ver que las piezas encajan sin depender de la red ni de una API
key. Carga -> regimenes -> corpus -> outcomes -> autodeteccion, de punta a punta.

Para que NO sirve: para mirar los numeros. Los precios son un paseo aleatorio con
semilla fija. Cualquier retorno que salga de aca es ruido de un generador, no
mercado. Si algun dia una salida de este modulo termina en un reporte, el reporte
esta roto.

Escribe siempre en una base aparte (data/demo.db). No toca el archivo real.
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from typing import Any

from classify import regime as regime_mod
from core import db as dbmod
from history import archive as archive_mod
from history import outcomes as out_mod
from history import seed as seed_mod
from pit import macro as macro_mod
from pit import prices as price_mod

DEMO_DB = "data/demo.db"
AVISO = "DATOS SINTETICOS: precios generados con un paseo aleatorio. Los numeros no significan nada."


def _business_days(start: date, end: date) -> list[date]:
    dias, day = [], start
    while day <= end:
        if day.weekday() < 5:
            dias.append(day)
        day += timedelta(days=1)
    return dias


def build(
    universe: dict[str, Any],
    thresholds: dict[str, Any],
    *,
    db_path: str = DEMO_DB,
    desde: date = date(2005, 1, 3),
    hasta: date = date(2025, 12, 31),
    on_progress=lambda _: None,
) -> dict[str, Any]:
    conn, _ = dbmod.init_db(db_path)
    try:
        for tabla in ("outcomes", "event_candidates", "events_archive", "regimes", "prices", "macro_observations"):
            conn.execute(f"DELETE FROM {tabla}")

        on_progress("generando precios y macro sinteticos")
        activos = list(universe["assets"]) + [
            e["asset"] for e in universe["market_state"].values() if e.get("kind") == "price"
        ]
        dias = _business_days(desde, hasta)

        filas = []
        for activo in activos:
            rnd = random.Random(activo)
            precio = 100.0
            vol = 0.06 if activo == "VIX" else 0.011
            for dia in dias:
                precio = max(precio * (1 + rnd.gauss(0.0003, vol)), 1.0)
                filas.append(price_mod.PriceRow(activo, dia, precio))
        price_mod.upsert_prices(conn, filas, source="demo")

        inicio_ciclo = date(2022, 3, 16)
        macro = []
        for dia in dias:
            tasa = 0.1 if dia < inicio_ciclo else min(5.33, 0.1 + (dia - inicio_ciclo).days * 0.012)
            macro.append(macro_mod.MacroObservation("DFF", dia, dia, tasa))
            macro.append(macro_mod.MacroObservation("BAMLH0A0HYM2", dia, dia, 4.0 + dia.weekday() * 0.1))
            macro.append(macro_mod.MacroObservation("DGS10", dia, dia, 2.5))
            macro.append(macro_mod.MacroObservation("DGS2", dia, dia, 1.8))
        mes = date(desde.year, desde.month, 1)
        while mes <= hasta:
            macro.append(
                macro_mod.MacroObservation(
                    "CPILFESL", mes, mes + timedelta(days=40),
                    100.0 * (1.023 ** ((mes.year - desde.year) + mes.month / 12)),
                )
            )
            mes = (mes + timedelta(days=32)).replace(day=1)
        macro_mod.upsert_observations(conn, macro, source="demo")

        on_progress("construyendo regimenes")
        regimenes = regime_mod.build_regimes(conn, date(2007, 1, 3), hasta, thresholds)

        on_progress("cargando corpus semilla")
        corpus = seed_mod.load_corpus(conn, universe)
        seed_mod.reassign_regimes(conn)

        on_progress("calculando outcomes")
        out_mod.compute_all(conn, universe, thresholds)
        calidad = {row["data_quality"]: row["n"] for row in out_mod.quality_summary(conn)}

        on_progress("autodetectando episodios")
        candidatos = archive_mod.detect(conn, date(2010, 1, 1), hasta, thresholds)
        archive_mod.persist_candidates(conn, candidatos)

        return {
            "db": db_path,
            "cierres": len(filas),
            "observaciones_macro": len(macro),
            "episodios_regimen": regimenes.episodios_creados,
            "cambios_descartados": regimenes.cambios_descartados,
            "eventos": corpus["cargados"],
            "cobertura_market_state": corpus["cobertura_market_state_promedio"],
            "outcomes": calidad,
            "candidatos": len(candidatos),
        }
    finally:
        conn.close()
