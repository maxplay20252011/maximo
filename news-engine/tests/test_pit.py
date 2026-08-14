"""Tests de la capa point-in-time (§2.2). BLOQUEANTES.

Los 4 primeros son los del spec. Si alguno falla, no se avanza a la Tarea 3.

Todos usan datos sinteticos: valores redondos, elegidos para que el resultado
correcto sea obvio a ojo. No se testea contra datos reales de mercado a proposito
-- un test que depende de la red no es un test.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from core import db as dbmod
from pit import macro as macro_mod
from pit import market_state as ms_mod
from pit import prices as price_mod
from pit import verify as verify_mod
from pit.guards import (
    LookAheadError,
    as_of,
    clear_access_log,
    current_as_of,
    effective_as_of,
    is_visible,
    verify_no_lookahead,
    visibility_cutoff_date,
)


def utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)


@pytest.fixture()
def conn(tmp_path):
    connection, _ = dbmod.init_db(tmp_path / "pit.db")
    clear_access_log()
    yield connection
    connection.close()


# ===========================================================================
# Las 4 guardas de §2.2
# ===========================================================================


def test_guarda_1_precio_del_futuro(conn):
    price_mod.upsert_prices(
        conn,
        [
            price_mod.PriceRow("SPY", date(2022, 2, 23), 100.0),
            price_mod.PriceRow("SPY", date(2022, 2, 25), 98.0),
        ],
        source="test",
    )
    momento = utc("2022-02-24T05:00:00Z")
    with as_of(momento):
        assert price_mod.get_price_as_known_at(conn, "SPY", date(2022, 2, 23), momento) == 100.0
        with pytest.raises(LookAheadError):
            price_mod.get_price_as_known_at(conn, "SPY", date(2022, 2, 25), momento)


def test_guarda_2_vintage_macro(conn):
    macro_mod.upsert_observations(
        conn,
        [
            macro_mod.MacroObservation("SERIE_TEST", date(2020, 3, 1), date(2020, 4, 10), 100.0),
            macro_mod.MacroObservation("SERIE_TEST", date(2020, 3, 1), date(2020, 5, 12), 101.5),
        ],
        source="test",
    )
    abril = utc("2020-04-15T12:00:00Z")
    with as_of(abril):
        assert macro_mod.get_macro_as_known_at(conn, "SERIE_TEST", date(2020, 3, 1), abril) == 100.0

    junio = utc("2020-06-01T12:00:00Z")
    with as_of(junio):
        assert macro_mod.get_macro_as_known_at(conn, "SERIE_TEST", date(2020, 3, 1), junio) == 101.5


def test_guarda_3_precio_pre_split(conn):
    price_mod.upsert_prices(conn, [price_mod.PriceRow("TEST", date(2018, 6, 1), 200.0)], source="test")
    price_mod.upsert_corporate_action(
        conn,
        asset="TEST",
        kind="SPLIT",
        ex_date=date(2018, 9, 3),
        announced_at=utc("2018-08-01T20:00:00Z"),
        split_ratio=2.0,
        source="test",
    )
    antes = utc("2018-07-15T12:00:00Z")
    with as_of(antes):
        assert price_mod.get_price_as_known_at(conn, "TEST", date(2018, 6, 1), antes) == 200.0

    despues = utc("2018-10-01T12:00:00Z")
    with as_of(despues):
        assert price_mod.get_price_as_known_at(conn, "TEST", date(2018, 6, 1), despues) == pytest.approx(100.0)


def test_guarda_4_market_state_sin_fechas_del_futuro(conn):
    evento = date(2022, 2, 24)
    filas, macro_filas = [], []
    for offset in range(400):
        dia = date.fromordinal(evento.toordinal() - offset)
        if dia.weekday() >= 5:
            continue
        filas.append(price_mod.PriceRow("SPX", dia, 4000.0 + offset))
        filas.append(price_mod.PriceRow("VIX", dia, 20.0 + offset * 0.01))
        macro_filas.append(macro_mod.MacroObservation("DGS10", dia, dia, 2.0))
        macro_filas.append(macro_mod.MacroObservation("DGS2", dia, dia, 1.5))
    price_mod.upsert_prices(conn, filas, source="test")
    macro_mod.upsert_observations(conn, macro_filas, source="test")

    momento = utc("2022-02-24T05:00:00Z")
    with as_of(momento):
        state = ms_mod.build_market_state(conn, momento, verify_mod.GUARD4_UNIVERSE)

    fechas = state["_meta"]["field_dates"]
    assert fechas, "el market_state quedo vacio: el test no probaria nada"
    assert all(fecha < evento.isoformat() for fecha in fechas.values()), fechas
    assert state["curve_2s10s"] == pytest.approx(0.5)
    assert not verify_no_lookahead()


def test_las_cuatro_guardas_como_comando():
    resultados = verify_mod.run_all_guards()
    assert len(resultados) == 4
    fallidas = [r for r in resultados if not r.passed]
    assert not fallidas, [(r.name, r.detail) for r in fallidas]


# ===========================================================================
# Contexto as_of
# ===========================================================================


def test_as_of_congela_el_reloj():
    from core.clock import now

    momento = utc("2015-08-11T03:00:00Z")
    with as_of(momento):
        assert now() == momento
        assert current_as_of() == momento
    assert current_as_of() is None


def test_as_of_anidado_solo_puede_achicar():
    externo = utc("2020-03-23T12:00:00Z")
    with as_of(externo):
        with as_of(utc("2020-03-01T12:00:00Z")):
            assert current_as_of() == utc("2020-03-01T12:00:00Z")
        assert current_as_of() == externo
        with pytest.raises(LookAheadError):
            with as_of(utc("2020-06-01T12:00:00Z")):
                pass


def test_sin_as_of_el_limite_es_el_reloj():
    from core.clock import FrozenClock, set_clock

    anterior = set_clock(FrozenClock(utc("2026-08-14T00:00:00Z")))
    try:
        assert effective_as_of() == utc("2026-08-14T00:00:00Z")
        assert is_visible(date(2026, 8, 12))
        assert not is_visible(date(2026, 8, 20))
    finally:
        set_clock(anterior)


def test_cierre_diario_visible_recien_al_cerrar_el_dia():
    with as_of(utc("2022-02-24T05:00:00Z")):
        assert visibility_cutoff_date() == date(2022, 2, 23)
    with as_of(utc("2022-02-24T23:59:59Z")):
        assert visibility_cutoff_date() == date(2022, 2, 24)


def test_el_log_de_accesos_registra_y_detecta():
    clear_access_log()
    momento = utc("2022-02-24T05:00:00Z")
    with as_of(momento):
        assert is_visible(date(2022, 2, 20))
        with pytest.raises(LookAheadError):
            from pit.guards import require_visible

            require_visible("price", "SPY@2022-03-01", date(2022, 3, 1))
    sospechosos = verify_no_lookahead()
    assert len(sospechosos) == 1
    assert sospechosos[0].label == "SPY@2022-03-01"


# ===========================================================================
# Precios
# ===========================================================================


def test_serie_de_cierres_se_ajusta_entera_o_no_se_ajusta(conn):
    price_mod.upsert_prices(
        conn,
        [
            price_mod.PriceRow("TEST", date(2018, 6, 1), 200.0),
            price_mod.PriceRow("TEST", date(2018, 6, 4), 210.0),
            price_mod.PriceRow("TEST", date(2018, 9, 4), 105.0),
        ],
        source="test",
    )
    price_mod.upsert_corporate_action(
        conn, asset="TEST", kind="SPLIT", ex_date=date(2018, 9, 3),
        announced_at=utc("2018-08-01T20:00:00Z"), split_ratio=2.0, source="test",
    )
    despues = utc("2018-10-01T12:00:00Z")
    with as_of(despues):
        serie = dict(price_mod.get_close_series_as_known_at(conn, "TEST", date(2018, 6, 1), date(2018, 9, 4), despues))
    assert serie[date(2018, 6, 1)] == pytest.approx(100.0)
    assert serie[date(2018, 6, 4)] == pytest.approx(105.0)
    assert serie[date(2018, 9, 4)] == pytest.approx(105.0)  # posterior al split: sin ajustar


def test_retorno_cruzando_un_split_no_inventa_una_caida_del_50(conn):
    price_mod.upsert_prices(
        conn,
        [
            price_mod.PriceRow("TEST", date(2018, 8, 31), 200.0),
            price_mod.PriceRow("TEST", date(2018, 9, 4), 102.0),
        ],
        source="test",
    )
    price_mod.upsert_corporate_action(
        conn, asset="TEST", kind="SPLIT", ex_date=date(2018, 9, 3),
        announced_at=utc("2018-08-01T20:00:00Z"), split_ratio=2.0, source="test",
    )
    despues = utc("2018-10-01T12:00:00Z")
    with as_of(despues):
        retorno = price_mod.get_return_as_known_at(conn, "TEST", date(2018, 8, 31), date(2018, 9, 4), despues)
    assert retorno == pytest.approx(0.02)


def test_retorno_total_suma_dividendos_anunciados(conn):
    price_mod.upsert_prices(
        conn,
        [price_mod.PriceRow("DIV", date(2022, 1, 3), 100.0), price_mod.PriceRow("DIV", date(2022, 2, 1), 100.0)],
        source="test",
    )
    price_mod.upsert_corporate_action(
        conn, asset="DIV", kind="DIVIDEND", ex_date=date(2022, 1, 20),
        announced_at=utc("2022-01-05T12:00:00Z"), dividend_amount=1.0, source="test",
    )
    despues = utc("2022-03-01T12:00:00Z")
    with as_of(despues):
        assert price_mod.get_return_as_known_at(conn, "DIV", date(2022, 1, 3), date(2022, 2, 1), despues) == 0.0
        total = price_mod.get_total_return_as_known_at(conn, "DIV", date(2022, 1, 3), date(2022, 2, 1), despues)
    assert total == pytest.approx(0.01)


def test_precio_faltante_falla_en_vez_de_interpolar(conn):
    momento = utc("2022-03-01T12:00:00Z")
    with as_of(momento):
        with pytest.raises(price_mod.PriceDataError):
            price_mod.get_price_as_known_at(conn, "NO_EXISTE", date(2022, 2, 1), momento)


def test_ultimo_cierre_no_devuelve_un_precio_rancio(conn):
    price_mod.upsert_prices(conn, [price_mod.PriceRow("VIEJO", date(2021, 1, 4), 50.0)], source="test")
    momento = utc("2022-02-24T05:00:00Z")
    with as_of(momento):
        with pytest.raises(price_mod.PriceDataError):
            price_mod.get_last_price_as_known_at(conn, "VIEJO", date(2022, 2, 23), momento)


def test_parser_de_stooq():
    csv_text = (
        "Date,Open,High,Low,Close,Volume\n"
        "2022-02-23,437.0,438.1,429.0,429.57,120000000\n"
        "2022-02-24,411.0,428.7,410.6,428.30,180000000\n"
    )
    filas = price_mod.parse_stooq_csv("SPY", csv_text)
    assert len(filas) == 2
    assert filas[0].close_raw == 429.57
    assert filas[1].price_date == date(2022, 2, 24)


def test_parser_de_stooq_rechaza_respuesta_de_error():
    with pytest.raises(price_mod.PriceDataError):
        price_mod.parse_stooq_csv("SPY", "No data")


# ===========================================================================
# Macro
# ===========================================================================


def test_ultima_observacion_publicada_no_es_la_del_mes_en_curso(conn):
    macro_mod.upsert_observations(
        conn,
        [
            macro_mod.MacroObservation("CPI_TEST", date(2020, 2, 1), date(2020, 3, 11), 258.0),
            macro_mod.MacroObservation("CPI_TEST", date(2020, 3, 1), date(2020, 4, 10), 258.1),
        ],
        source="test",
    )
    momento = utc("2020-03-23T12:00:00Z")
    with as_of(momento):
        resultado = macro_mod.get_latest_macro_as_known_at(conn, "CPI_TEST", momento)
    assert resultado == (date(2020, 2, 1), 258.0)


def test_ultima_observacion_usa_el_vintage_vigente_no_el_revisado(conn):
    macro_mod.upsert_observations(
        conn,
        [
            macro_mod.MacroObservation("CPI_TEST", date(2020, 2, 1), date(2020, 3, 11), 258.0),
            macro_mod.MacroObservation("CPI_TEST", date(2020, 2, 1), date(2021, 2, 10), 259.9),
        ],
        source="test",
    )
    momento = utc("2020-03-23T12:00:00Z")
    with as_of(momento):
        assert macro_mod.get_latest_macro_as_known_at(conn, "CPI_TEST", momento) == (date(2020, 2, 1), 258.0)

    mas_tarde = utc("2021-06-01T12:00:00Z")
    with as_of(mas_tarde):
        assert macro_mod.get_latest_macro_as_known_at(conn, "CPI_TEST", mas_tarde) == (date(2020, 2, 1), 259.9)


def test_historial_de_revisiones(conn):
    macro_mod.upsert_observations(
        conn,
        [
            macro_mod.MacroObservation("PAYEMS_TEST", date(2020, 3, 1), date(2020, 4, 3), -701.0),
            macro_mod.MacroObservation("PAYEMS_TEST", date(2020, 3, 1), date(2020, 5, 8), -881.0),
            macro_mod.MacroObservation("PAYEMS_TEST", date(2020, 3, 1), date(2020, 6, 5), -1373.0),
        ],
        source="test",
    )
    historial = macro_mod.get_revision_history(conn, "PAYEMS_TEST", date(2020, 3, 1))
    assert [obs.value for obs in historial] == [-701.0, -881.0, -1373.0]

    abril = utc("2020-04-15T12:00:00Z")
    with as_of(abril):
        assert macro_mod.get_macro_as_known_at(conn, "PAYEMS_TEST", date(2020, 3, 1), abril) == -701.0


def test_dato_faltante_es_none_no_cero(conn):
    macro_mod.upsert_observations(
        conn, [macro_mod.MacroObservation("SERIE_TEST", date(2020, 3, 1), date(2020, 4, 10), None)], source="test"
    )
    momento = utc("2020-05-01T12:00:00Z")
    with as_of(momento):
        assert macro_mod.get_macro_as_known_at(conn, "SERIE_TEST", date(2020, 3, 1), momento) is None


def test_parser_de_alfred_all_vintages():
    payload = {
        "observations": [
            {"date": "2020-03-01", "CPIAUCSL_20200410": "258.115", "CPIAUCSL_20200512": "258.678"},
            {"date": "2020-04-01", "CPIAUCSL_20200410": ".", "CPIAUCSL_20200512": "256.389"},
        ]
    }
    filas = macro_mod.parse_alfred_response("CPIAUCSL", payload)
    assert len(filas) == 4
    faltante = [f for f in filas if f.obs_date == date(2020, 4, 1) and f.vintage_date == date(2020, 4, 10)][0]
    assert faltante.value is None


def test_load_macro_sin_vintages_es_rechazado(conn):
    with pytest.raises(macro_mod.MacroDataError, match="vintages"):
        macro_mod.load_macro(conn, ["CPIAUCSL"], date(2020, 1, 1), date(2020, 12, 31), vintages=False)


def test_vintage_anterior_a_la_observacion_es_rechazado(conn):
    import sqlite3

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """INSERT INTO macro_observations (series_id, obs_date, vintage_date, value, source, fetched_at_utc)
               VALUES ('X', '2020-03-01', '2020-02-01', 1.0, 'test', '2026-08-14T00:00:00Z')"""
        )


# ===========================================================================
# market_state
# ===========================================================================


def test_market_state_declara_lo_que_le_falta(conn):
    momento = utc("2022-02-24T05:00:00Z")
    with as_of(momento):
        state = ms_mod.build_market_state(conn, momento, ms_mod.load_universe("config/universe.yaml"))

    assert state["put_call_ratio"] is None
    assert "put_call_ratio" in state["_meta"]["missing"]
    assert "breadth_pct_above_200dma" in state["_meta"]["missing"]
    assert state["_meta"]["coverage"] == 0.0  # base vacia: no hay nada cargado, y se dice
