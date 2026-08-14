"""Las 4 guardas bloqueantes de §2.2, ejecutables como comando.

`python run.py pit verify` corre esto. Cada guarda arma sus propios datos
sinteticos en una base en memoria: el resultado no depende de que haya datos
cargados, y por eso sirve tambien como healthcheck (§C.7).

Los mismos escenarios estan en tests/test_pit.py. La duplicacion es a proposito:
si un dia alguien ablanda el modulo, tiene que romper dos veces.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Callable

from core import db as dbmod
from pit import macro as macro_mod
from pit import market_state as ms_mod
from pit import prices as price_mod
from pit.guards import LookAheadError, as_of


@dataclass(frozen=True)
class GuardResult:
    name: str
    passed: bool
    detail: str


def _fixture_db() -> sqlite3.Connection:
    conn = dbmod.connect(":memory:")
    dbmod.migrate(conn)
    return conn


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Guarda 1: precio del futuro
# ---------------------------------------------------------------------------


def guard_future_price() -> GuardResult:
    conn = _fixture_db()
    try:
        price_mod.upsert_prices(
            conn,
            [
                price_mod.PriceRow("SPY", date(2022, 2, 23), 100.0),
                price_mod.PriceRow("SPY", date(2022, 2, 24), 96.0),
                price_mod.PriceRow("SPY", date(2022, 2, 25), 98.0),
            ],
            source="fixture",
        )
        moment = _utc("2022-02-24T05:00:00Z")
        with as_of(moment):
            price_mod.get_price_as_known_at(conn, "SPY", date(2022, 2, 23), moment)  # visible
            try:
                price_mod.get_price_as_known_at(conn, "SPY", date(2022, 2, 25), moment)
            except LookAheadError:
                pass
            else:
                return GuardResult("precio futuro", False, "devolvio el cierre del 25 mirando desde el 24")

            try:
                price_mod.get_price_as_known_at(conn, "SPY", date(2022, 2, 24), moment)
            except LookAheadError:
                return GuardResult(
                    "precio futuro", True, "rechaza el cierre del dia en curso y el del dia siguiente"
                )
            return GuardResult(
                "precio futuro", False, "devolvio el cierre del mismo dia a las 05:00Z, antes de que exista"
            )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Guarda 2: vintage macro
# ---------------------------------------------------------------------------


def guard_macro_vintage() -> GuardResult:
    conn = _fixture_db()
    try:
        # Valores sinteticos: publicado 100.0, revisado despues a 101.5.
        macro_mod.upsert_observations(
            conn,
            [
                macro_mod.MacroObservation("SERIE_TEST", date(2020, 3, 1), date(2020, 4, 10), 100.0),
                macro_mod.MacroObservation("SERIE_TEST", date(2020, 3, 1), date(2020, 5, 12), 101.5),
            ],
            source="fixture",
        )
        original = _utc("2020-04-15T12:00:00Z")
        with as_of(original):
            valor = macro_mod.get_macro_as_known_at(conn, "SERIE_TEST", date(2020, 3, 1), original)
        if valor != 100.0:
            return GuardResult("vintage macro", False, f"devolvio {valor}, esperaba el vintage original 100.0")

        posterior = _utc("2020-06-01T12:00:00Z")
        with as_of(posterior):
            revisado = macro_mod.get_macro_as_known_at(conn, "SERIE_TEST", date(2020, 3, 1), posterior)
        if revisado != 101.5:
            return GuardResult("vintage macro", False, f"desde junio devolvio {revisado}, esperaba 101.5")

        antes = _utc("2020-04-01T12:00:00Z")
        with as_of(antes):
            inexistente = macro_mod.get_macro_as_known_at(conn, "SERIE_TEST", date(2020, 3, 1), antes)
        if inexistente is not None:
            return GuardResult("vintage macro", False, "devolvio un valor antes de que la serie se publicara")

        return GuardResult("vintage macro", True, "abril 100.0 / junio 101.5 / antes del release None")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Guarda 3: split anunciado despues
# ---------------------------------------------------------------------------


def guard_pre_split_price() -> GuardResult:
    conn = _fixture_db()
    try:
        price_mod.upsert_prices(conn, [price_mod.PriceRow("TEST", date(2018, 6, 1), 200.0)], source="fixture")
        price_mod.upsert_corporate_action(
            conn,
            asset="TEST",
            kind="SPLIT",
            ex_date=date(2018, 9, 3),
            announced_at=_utc("2018-08-01T20:00:00Z"),
            split_ratio=2.0,
            source="fixture",
        )
        antes = _utc("2018-07-15T12:00:00Z")
        with as_of(antes):
            crudo = price_mod.get_price_as_known_at(conn, "TEST", date(2018, 6, 1), antes)
        if crudo != 200.0:
            return GuardResult("precio pre-split", False, f"ajusto por un split no anunciado: {crudo}")

        despues = _utc("2018-10-01T12:00:00Z")
        with as_of(despues):
            ajustado = price_mod.get_price_as_known_at(conn, "TEST", date(2018, 6, 1), despues)
        if abs(ajustado - 100.0) > 1e-9:
            return GuardResult("precio pre-split", False, f"post-split devolvio {ajustado}, esperaba 100.0")

        return GuardResult("precio pre-split", True, "julio 200.0 sin ajustar / octubre 100.0 ajustado")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Guarda 4: market_state sin fechas del futuro
# ---------------------------------------------------------------------------


GUARD4_UNIVERSE: dict[str, Any] = {
    "market_state": {
        "vix": {"kind": "price", "asset": "VIX"},
        "spx_level": {"kind": "price", "asset": "SPX"},
        "us10y": {"kind": "macro", "series": "DGS10", "max_staleness_days": 7},
        "us2y": {"kind": "macro", "series": "DGS2", "max_staleness_days": 7},
    }
}


def guard_market_state_dates() -> GuardResult:
    conn = _fixture_db()
    try:
        event_day = date(2022, 2, 24)
        rows: list[price_mod.PriceRow] = []
        macro_rows: list[macro_mod.MacroObservation] = []
        for offset in range(400):
            day = date.fromordinal(event_day.toordinal() - offset)
            if day.weekday() >= 5:
                continue
            rows.append(price_mod.PriceRow("SPX", day, 4000.0 + offset))
            rows.append(price_mod.PriceRow("VIX", day, 20.0 + offset * 0.01))
            macro_rows.append(macro_mod.MacroObservation("DGS10", day, day, 2.0))
            macro_rows.append(macro_mod.MacroObservation("DGS2", day, day, 1.5))
        price_mod.upsert_prices(conn, rows, source="fixture")
        macro_mod.upsert_observations(conn, macro_rows, source="fixture")

        moment = _utc("2022-02-24T05:00:00Z")
        with as_of(moment):
            state = ms_mod.build_market_state(conn, moment, GUARD4_UNIVERSE)

        fechas = state["_meta"]["field_dates"]
        if not fechas:
            return GuardResult("fechas de market_state", False, "no se pudo poblar ningun campo")

        culpables = {campo: valor for campo, valor in fechas.items() if valor >= event_day.isoformat()}
        if culpables:
            return GuardResult("fechas de market_state", False, f"campos con fecha >= la del evento: {culpables}")

        return GuardResult(
            "fechas de market_state",
            True,
            f"{len(fechas)} campos, todos <= {max(fechas.values())} (evento {event_day.isoformat()})",
        )
    finally:
        conn.close()


GUARDS: tuple[Callable[[], GuardResult], ...] = (
    guard_future_price,
    guard_macro_vintage,
    guard_pre_split_price,
    guard_market_state_dates,
)


def run_all_guards() -> list[GuardResult]:
    results: list[GuardResult] = []
    for guard in GUARDS:
        try:
            results.append(guard())
        except Exception as exc:  # noqa: BLE001 - una guarda que explota es una guarda que falla
            results.append(GuardResult(guard.__name__, False, f"excepcion inesperada: {exc!r}"))
    return results
