"""Tests del corpus semilla, los outcomes y la autodeteccion (§6).

Los outcomes se prueban contra series construidas para que el retorno correcto se
sepa de antemano: precios que suben un 1% por sesion dan un 5d de 1.01^5 - 1
exacto. Si el modulo devuelve otra cosa, esta mal el modulo.
"""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta, timezone

import pytest
import yaml

from classify.event_types import EVENT_TYPE_NAMES
from core import db as dbmod
from history import archive as archive_mod
from history import outcomes as out_mod
from history import seed as seed_mod
from pit import prices as price_mod

UNIVERSE = yaml.safe_load(open("config/universe.yaml", encoding="utf-8"))
THRESHOLDS = yaml.safe_load(open("config/thresholds.yaml", encoding="utf-8"))


@pytest.fixture()
def conn(tmp_path):
    connection, _ = dbmod.init_db(tmp_path / "seed.db")
    yield connection
    connection.close()


def business_days(start: date, end: date):
    day = start
    while day <= end:
        if day.weekday() < 5:
            yield day
        day += timedelta(days=1)


def seed_prices(conn, assets: dict, start: date, end: date) -> None:
    """assets: {ticker: funcion(indice_de_sesion) -> precio}"""
    filas = []
    for asset, funcion in assets.items():
        for indice, dia in enumerate(business_days(start, end)):
            filas.append(price_mod.PriceRow(asset, dia, funcion(indice)))
    price_mod.upsert_prices(conn, filas, source="test")


def insert_evento(conn, event_id="test-evento", cuando="2022-02-24T03:00:00Z", tipo="GEOPOLITICAL"):
    conn.execute(
        """INSERT INTO events_archive (event_id, occurred_at_utc, ingested_at_utc, event_type,
                                       headline, severity, market_state_json, is_seed)
           VALUES (?, ?, ?, ?, 'titular de prueba', 5, '{}', 1)""",
        (event_id, cuando, cuando, tipo),
    )


# ---------------------------------------------------------------------------
# El archivo semilla
# ---------------------------------------------------------------------------


def test_el_corpus_tiene_los_episodios_de_la_seccion_6():
    eventos = seed_mod.load_seed_file()
    assert len(eventos) == 26
    ids = {e.event_id for e in eventos}
    for esperado in ("lehman-2008", "ukraine-invasion-2022", "svb-2023", "flash-crash-2010"):
        assert esperado in ids


def test_todos_los_episodios_usan_clases_validas_y_severidad_en_rango():
    for evento in seed_mod.load_seed_file():
        assert evento.event_type in EVENT_TYPE_NAMES
        assert 1 <= evento.severity <= 5
        assert evento.headline.strip()
        assert evento.occurred_at.tzinfo is not None


def test_los_episodios_estan_en_orden_cronologico_razonable():
    eventos = seed_mod.load_seed_file()
    assert min(e.occurred_at for e in eventos).year == 2008
    assert max(e.occurred_at for e in eventos).year >= 2024


def test_id_repetido_es_error(tmp_path):
    archivo = tmp_path / "malo.yaml"
    archivo.write_text(
        yaml.safe_dump(
            {
                "eventos": [
                    {"id": "x", "fecha": "2020-01-01", "hora_utc": "12:00", "tipo": "MACRO_DATA",
                     "severidad": 3, "titular": "a"},
                    {"id": "x", "fecha": "2020-01-02", "hora_utc": "12:00", "tipo": "MACRO_DATA",
                     "severidad": 3, "titular": "b"},
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(seed_mod.SeedError, match="repetido"):
        seed_mod.load_seed_file(str(archivo))


def test_clase_invalida_en_el_archivo_es_error(tmp_path):
    archivo = tmp_path / "malo.yaml"
    archivo.write_text(
        yaml.safe_dump(
            {"eventos": [{"id": "x", "fecha": "2020-01-01", "hora_utc": "12:00",
                          "tipo": "NOTICIA_FUERTE", "severidad": 3, "titular": "a"}]}
        ),
        encoding="utf-8",
    )
    with pytest.raises(seed_mod.SeedError, match="clase de evento"):
        seed_mod.load_seed_file(str(archivo))


# ---------------------------------------------------------------------------
# Carga
# ---------------------------------------------------------------------------


def test_carga_del_corpus_sin_precios_deja_todo_declarado(conn):
    resumen = seed_mod.load_corpus(conn, UNIVERSE)
    assert resumen["cargados"] == 26
    assert resumen["cobertura_market_state_promedio"] == 0.0
    assert len(resumen["sin_regimen"]) == 26

    fila = conn.execute(
        "SELECT * FROM events_archive WHERE event_id = 'lehman-2008'"
    ).fetchone()
    assert fila["is_seed"] == 1
    assert fila["lag_minutes"] is None            # no medido, no cero
    assert fila["occurred_at_utc"] == fila["ingested_at_utc"]
    assert fila["surprise_direction"] == "NO_CONSENSUS"
    estado = json.loads(fila["market_state_json"])
    assert estado["_meta"]["coverage"] == 0.0
    assert estado["vix"] is None


def test_la_carga_es_idempotente(conn):
    seed_mod.load_corpus(conn, UNIVERSE)
    seed_mod.load_corpus(conn, UNIVERSE)
    assert conn.execute("SELECT COUNT(*) AS n FROM events_archive").fetchone()["n"] == 26


def test_el_market_state_del_evento_no_mira_el_dia_del_evento(conn):
    seed_prices(conn, {"SPX": lambda i: 4000.0 + i, "VIX": lambda i: 20.0}, date(2021, 1, 1), date(2022, 3, 31))
    seed_mod.load_corpus(conn, UNIVERSE)

    fila = conn.execute(
        "SELECT market_state_json FROM events_archive WHERE event_id = 'ukraine-invasion-2022'"
    ).fetchone()
    fechas = json.loads(fila["market_state_json"])["_meta"]["field_dates"]
    assert fechas
    assert all(fecha < "2022-02-24" for fecha in fechas.values()), fechas


# ---------------------------------------------------------------------------
# Outcomes
# ---------------------------------------------------------------------------


def test_retornos_exactos_sobre_una_serie_conocida(conn):
    # +1% por sesion, todos los dias.
    seed_prices(conn, {"XLE": lambda i: 100.0 * (1.01 ** i), "SPY": lambda i: 100.0},
                date(2022, 1, 3), date(2022, 6, 30))
    insert_evento(conn, cuando="2022-02-24T03:00:00Z")

    filas = out_mod.compute_event_outcomes(conn, "test-evento", UNIVERSE, THRESHOLDS, assets=["XLE"])
    fila = filas[0]

    assert fila.ret_1d == pytest.approx(0.01, abs=1e-6)
    assert fila.ret_5d == pytest.approx(1.01 ** 5 - 1, abs=1e-6)
    assert fila.ret_20d == pytest.approx(1.01 ** 20 - 1, abs=1e-6)
    assert fila.data_quality == "OK"
    # El benchmark quedo plano: el exceso es todo el retorno.
    assert fila.excess_5d == pytest.approx(fila.ret_5d, abs=1e-6)
    assert fila.benchmark == "SPY"


def test_el_exceso_descuenta_el_benchmark(conn):
    seed_prices(conn, {"XLE": lambda i: 100.0 * (1.01 ** i), "SPY": lambda i: 100.0 * (1.01 ** i)},
                date(2022, 1, 3), date(2022, 6, 30))
    insert_evento(conn)

    fila = out_mod.compute_event_outcomes(conn, "test-evento", UNIVERSE, THRESHOLDS, assets=["XLE"])[0]
    assert fila.ret_5d > 0.04
    assert fila.excess_5d == pytest.approx(0.0, abs=1e-9)   # se movio igual que el indice


def test_evento_posterior_al_cierre_arranca_del_cierre_del_mismo_dia(conn):
    """Un evento a las 22:00Z del jueves se mide desde el cierre del jueves.
    Uno a las 03:00Z, desde el cierre del miercoles."""
    seed_prices(conn, {"XLE": lambda i: 100.0 + i, "SPY": lambda i: 100.0},
                date(2022, 1, 3), date(2022, 6, 30))

    insert_evento(conn, event_id="temprano", cuando="2022-02-24T03:00:00Z")
    insert_evento(conn, event_id="tarde", cuando="2022-02-24T22:00:00Z")

    temprano = out_mod.compute_event_outcomes(conn, "temprano", UNIVERSE, THRESHOLDS, assets=["XLE"])[0]
    tarde = out_mod.compute_event_outcomes(conn, "tarde", UNIVERSE, THRESHOLDS, assets=["XLE"])[0]

    # La serie sube 1 punto por sesion desde 100 el 2022-01-03.
    # temprano: t0 = 02-23; tarde: t0 = 02-24. Un dia de diferencia en la base.
    assert temprano.ret_1d != tarde.ret_1d
    assert temprano.ret_1d == pytest.approx(1 / 137, abs=1e-6)
    assert tarde.ret_1d == pytest.approx(1 / 138, abs=1e-6)


def test_drawdown_es_negativo_y_mide_pico_a_valle(conn):
    def zigzag(i: int) -> float:
        # sube hasta la sesion 40, despues cae y se estabiliza
        return 100.0 + i if i <= 40 else max(112.0, 140.0 - (i - 40) * 2)

    seed_prices(conn, {"XLE": zigzag, "SPY": lambda i: 100.0}, date(2022, 1, 3), date(2022, 6, 30))
    insert_evento(conn, cuando="2022-02-24T03:00:00Z")

    fila = out_mod.compute_event_outcomes(conn, "test-evento", UNIVERSE, THRESHOLDS, assets=["XLE"])[0]
    assert fila.max_drawdown_20d is not None
    assert fila.max_drawdown_20d <= 0


def test_vol_ratio_detecta_el_salto_de_volatilidad(conn):
    def calmo_luego_agitado(i: int) -> float:
        if i <= 36:
            return 100.0 + (i % 2) * 0.1          # casi plano
        return 100.0 + (i % 2) * 8.0              # zigzag violento

    seed_prices(conn, {"XLE": calmo_luego_agitado, "SPY": lambda i: 100.0},
                date(2022, 1, 3), date(2022, 6, 30))
    insert_evento(conn, cuando="2022-02-24T03:00:00Z")

    fila = out_mod.compute_event_outcomes(conn, "test-evento", UNIVERSE, THRESHOLDS, assets=["XLE"])[0]
    assert fila.vol_realized_5d > 0
    assert fila.vol_ratio_vs_prior > 3


def test_sin_precios_el_outcome_queda_declarado_faltante(conn):
    insert_evento(conn)
    filas = out_mod.compute_event_outcomes(conn, "test-evento", UNIVERSE, THRESHOLDS, assets=["XLE"])
    fila = filas[0]
    assert fila.data_quality == "MISSING"
    assert fila.ret_5d is None
    assert fila.ret_1d is None


def test_ventana_incompleta_se_marca_parcial(conn):
    # Solo 6 sesiones despues del evento: alcanza para 1d y 5d, no para 20d.
    seed_prices(conn, {"XLE": lambda i: 100.0 + i, "SPY": lambda i: 100.0},
                date(2022, 1, 3), date(2022, 3, 3))
    insert_evento(conn, cuando="2022-02-24T03:00:00Z")

    fila = out_mod.compute_event_outcomes(conn, "test-evento", UNIVERSE, THRESHOLDS, assets=["XLE"])[0]
    assert fila.ret_1d is not None
    assert fila.ret_5d is not None
    assert fila.ret_20d is None
    assert fila.data_quality == "PARTIAL"


def test_activo_sin_benchmark_no_reporta_exceso(conn):
    seed_prices(conn, {"GLD": lambda i: 100.0 + i}, date(2022, 1, 3), date(2022, 6, 30))
    insert_evento(conn)

    fila = out_mod.compute_event_outcomes(conn, "test-evento", UNIVERSE, THRESHOLDS, assets=["GLD"])[0]
    assert fila.benchmark is None
    assert fila.excess_5d is None
    assert fila.ret_5d is not None
    assert fila.data_quality == "NO_BENCHMARK"


def test_persistir_respeta_las_constraints_del_schema(conn):
    seed_prices(conn, {"XLE": lambda i: 100.0 + i, "SPY": lambda i: 100.0}, date(2022, 1, 3), date(2022, 6, 30))
    insert_evento(conn)
    filas = out_mod.compute_event_outcomes(conn, "test-evento", UNIVERSE, THRESHOLDS, assets=["XLE", "GLD"])
    out_mod.persist(conn, filas)

    guardado = conn.execute("SELECT * FROM outcomes WHERE asset = 'XLE'").fetchone()
    assert guardado["benchmark"] == "SPY"
    assert guardado["data_quality"] == "OK"
    assert conn.execute("SELECT COUNT(*) AS n FROM outcomes").fetchone()["n"] == 2


def test_recalcular_reemplaza_en_vez_de_duplicar(conn):
    seed_prices(conn, {"XLE": lambda i: 100.0 + i, "SPY": lambda i: 100.0}, date(2022, 1, 3), date(2022, 6, 30))
    insert_evento(conn)
    for _ in range(3):
        out_mod.persist(conn, out_mod.compute_event_outcomes(conn, "test-evento", UNIVERSE, THRESHOLDS, assets=["XLE"]))
    assert conn.execute("SELECT COUNT(*) AS n FROM outcomes").fetchone()["n"] == 1


# ---------------------------------------------------------------------------
# Autodeteccion
# ---------------------------------------------------------------------------


def test_detecta_el_dia_del_derrumbe_y_no_los_tranquilos(conn):
    def spx(i: int) -> float:
        return 4000.0 if i < 30 else (4000.0 * 0.95 if i == 30 else 3800.0)

    seed_prices(conn, {"SPX": spx}, date(2022, 1, 3), date(2022, 3, 31))
    candidatos = archive_mod.detect(conn, date(2022, 1, 3), date(2022, 3, 31), THRESHOLDS)

    assert len(candidatos) == 1
    assert "SPX_daily_move" in candidatos[0].triggers
    assert candidatos[0].metrics["spx_ret_1d"] < -0.025


def test_un_candidato_no_es_un_evento(conn):
    def spx(i: int) -> float:
        return 4000.0 if i < 30 else 3800.0

    seed_prices(conn, {"SPX": spx}, date(2022, 1, 3), date(2022, 3, 31))
    candidatos = archive_mod.detect(conn, date(2022, 1, 3), date(2022, 3, 31), THRESHOLDS)
    archive_mod.persist_candidates(conn, candidatos)

    assert conn.execute("SELECT COUNT(*) AS n FROM event_candidates").fetchone()["n"] == 1
    assert conn.execute("SELECT COUNT(*) AS n FROM events_archive").fetchone()["n"] == 0
    assert archive_mod.find_cause(conn, candidatos[0].trigger_date, THRESHOLDS) is None


def test_persistir_candidatos_es_idempotente(conn):
    def spx(i: int) -> float:
        return 4000.0 if i < 30 else 3800.0

    seed_prices(conn, {"SPX": spx}, date(2022, 1, 3), date(2022, 3, 31))
    candidatos = archive_mod.detect(conn, date(2022, 1, 3), date(2022, 3, 31), THRESHOLDS)
    assert archive_mod.persist_candidates(conn, candidatos) == 1
    assert archive_mod.persist_candidates(conn, candidatos) == 0


def test_promover_exige_titular_y_deja_rastro(conn):
    def spx(i: int) -> float:
        return 4000.0 if i < 30 else 3800.0

    seed_prices(conn, {"SPX": spx}, date(2022, 1, 3), date(2022, 3, 31))
    candidatos = archive_mod.detect(conn, date(2022, 1, 3), date(2022, 3, 31), THRESHOLDS)
    archive_mod.persist_candidates(conn, candidatos)
    cand = candidatos[0]
    cuando = datetime.combine(cand.trigger_date, time(14, 0), tzinfo=timezone.utc)

    with pytest.raises(ValueError, match="titular"):
        archive_mod.promote(conn, cand.candidate_id, event_type="MACRO_DATA", headline="   ",
                            occurred_at=cuando, severity=4, universe=UNIVERSE)

    event_id = archive_mod.promote(
        conn, cand.candidate_id, event_type="MACRO_DATA",
        headline="Dato de inflacion muy por encima del consenso",
        occurred_at=cuando, severity=4, universe=UNIVERSE, note="revisado a mano",
    )
    fila = conn.execute("SELECT * FROM events_archive WHERE event_id = ?", (event_id,)).fetchone()
    assert fila["auto_detected"] == 1
    assert fila["is_seed"] == 0

    candidato = conn.execute(
        "SELECT * FROM event_candidates WHERE candidate_id = ?", (cand.candidate_id,)
    ).fetchone()
    assert candidato["reviewed"] == 1
    assert candidato["promoted_event_id"] == event_id


def test_descartar_exige_motivo(conn):
    conn.execute(
        """INSERT INTO event_candidates (candidate_id, trigger_date, triggers_json, metrics_json, detected_at_utc)
           VALUES ('auto-2022-03-01', '2022-03-01', '[]', '{}', '2026-08-14T00:00:00Z')"""
    )
    with pytest.raises(ValueError, match="motivo"):
        archive_mod.dismiss(conn, "auto-2022-03-01", "  ")

    archive_mod.dismiss(conn, "auto-2022-03-01", "movimiento tecnico, sin noticia atras")
    assert archive_mod.pending(conn) == []


def test_reassign_regimes_cuenta_solo_lo_que_cambia(conn):
    conn.execute(
        """INSERT INTO regimes (regime_id, regime_label, start_date, end_date, rate_regime,
                                vol_regime, inflation_regime, usd_trend, credit_regime)
           VALUES ('R@2022-01-01', 'R', '2022-01-01', NULL, 'HIKING', 'NORMAL', 'ELEVATED', 'STRONG', 'NORMAL')"""
    )
    insert_evento(conn, event_id="e1", cuando="2022-02-24T03:00:00Z")
    insert_evento(conn, event_id="e2", cuando="2019-01-02T03:00:00Z")   # anterior al regimen

    assert seed_mod.reassign_regimes(conn) == 1     # solo e1 tiene regimen vigente
    assert seed_mod.reassign_regimes(conn) == 0     # ya asignado, nada que cambiar
    assert conn.execute("SELECT regime_id FROM events_archive WHERE event_id='e1'").fetchone()[0] == "R@2022-01-01"
    assert conn.execute("SELECT regime_id FROM events_archive WHERE event_id='e2'").fetchone()[0] is None
