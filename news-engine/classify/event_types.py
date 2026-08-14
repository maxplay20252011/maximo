"""Taxonomia de eventos: las 11 clases de §5.2.

§5.2 habla de "las 11 clases de evento" pero no las enumera. Estas son, derivadas
de los cinco grupos del corpus semilla (§6.1) y de las clases que el spec nombra
sueltas: MACRO_DATA (§10), CREDIT_EVENT y GEOPOLITICAL (§11).

La lista vive en dos lugares que tienen que coincidir: aca y en el CHECK de
`events_archive.event_type`. Hay un test que lo verifica. Cambiar la taxonomia
exige una migracion, y esta bien que sea asi: el archivo historico entero se
indexa por esta columna y el matcher hace match duro de tipo, sin excepcion
(§7.1). Una clase renombrada parte el archivo en dos.
"""

from __future__ import annotations

EVENT_TYPES: dict[str, str] = {
    "MACRO_DATA": "Release de dato macro: CPI, payrolls, PBI, PMI, confianza.",
    "MONETARY_POLICY": "Decision o comunicacion de un banco central: tasa, QE/QT, forward guidance, actas.",
    "CREDIT_EVENT": "Default, quiebra, rescate, corrida bancaria, stress de financiamiento.",
    "GEOPOLITICAL": "Conflicto armado, sanciones, elecciones, referendos, tension entre estados.",
    "COMMODITY_SUPPLY": "Shock de oferta o demanda de una commodity: OPEP, embargo, squeeze, corte de produccion.",
    "MARKET_STRUCTURE": "Falla o dislocacion del mercado mismo: flash crash, desarme de carry, squeeze de posicionamiento, iliquidez.",
    "FX_REGIME": "Devaluacion, intervencion cambiaria, cambio de regimen monetario o de banda.",
    "REGULATORY_FISCAL": "Regulacion, politica fiscal, presupuesto, impuestos, rating soberano.",
    "CORPORATE_EARNINGS": "Resultados trimestrales y guidance de una empresa cotizante.",
    "CORPORATE_ACTION": "M&A, spin-off, emision, recompra, cambio de management.",
    "DISASTER_HEALTH": "Catastrofe natural, accidente industrial, pandemia, emergencia sanitaria.",
}

EVENT_TYPE_NAMES: tuple[str, ...] = tuple(EVENT_TYPES)

# Valores enumerados del resto de las columnas de texto libre del schema.
SURPRISE_DIRECTIONS: tuple[str, ...] = ("ABOVE", "BELOW", "INLINE", "NO_CONSENSUS")
SOURCE_TIERS: tuple[str, ...] = ("TIER1", "TIER2", "TIER3")
NARRATIVE_ALIGNMENTS: tuple[str, ...] = ("CONFIRMS", "CONTRADICTS", "NEUTRAL")
DATA_QUALITY: tuple[str, ...] = ("OK", "PARTIAL", "STALE", "NO_BENCHMARK", "MISSING")
RUN_STATUSES: tuple[str, ...] = ("RUNNING", "OK", "FAILED", "PARTIAL")


def describe(event_type: str) -> str:
    if event_type not in EVENT_TYPES:
        raise KeyError(f"clase de evento desconocida: {event_type}. Las validas son {EVENT_TYPE_NAMES}")
    return EVENT_TYPES[event_type]
