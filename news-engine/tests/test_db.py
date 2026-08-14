"""Tests de la Tarea 1: schema, constraints y runner de migraciones.

No testean SQLite: testean que las constraints que el spec da por sentadas esten
realmente activas. Una FK sin `PRAGMA foreign_keys=ON` o un CHECK mal escrito
pasan desapercibidos hasta que corrompen el archivo historico.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from core import db as dbmod
from core.clock import FrozenClock, format_utc, set_clock

TS = "2022-02-24T05:00:00Z"
TS_LATER = "2022-03-01T05:00:00Z"


@pytest.fixture()
def conn(tmp_path):
    connection, _ = dbmod.init_db(tmp_path / "test.db")
    yield connection
    connection.close()


def insert_regime(conn, regime_id="NORMAL-HIKING-ELEVATED", start="2022-01-01", end=None):
    conn.execute(
        """INSERT INTO regimes (regime_id, regime_label, start_date, end_date, rate_regime,
                                vol_regime, inflation_regime, usd_trend, credit_regime)
           VALUES (?, ?, ?, ?, 'HIKING', 'NORMAL', 'ELEVATED', 'STRONG', 'NORMAL')""",
        (regime_id, regime_id, start, end),
    )
    return regime_id


def insert_event(conn, event_id="ukraine-2022", occurred=TS, severity=5, regime_id=None):
    conn.execute(
        """INSERT INTO events_archive (event_id, occurred_at_utc, ingested_at_utc, event_type,
                                       headline, severity, regime_id, market_state_json, is_seed)
           VALUES (?, ?, ?, 'GEOPOLITICAL', 'Invasion rusa de Ucrania', ?, ?, '{"vix": 30.3}', 1)""",
        (event_id, occurred, occurred, severity, regime_id),
    )
    return event_id


def insert_call(conn, call_id="c1", event_id="ukraine-2022", **overrides):
    fields = {
        "asset": "BNO",
        "direction_bias": "UP",
        "probability": 0.62,
        "horizon": "5d",
        "magnitude_low": 0.021,
        "magnitude_high": 0.084,
        "confidence": "MEDIUM",
        "n_analogs": 4,
        "directional_agreement": 0.75,
        "regime_match_quality": "PARTIAL",
        "counterargument": "La OPEP puede compensar el faltante con capacidad ociosa saudita.",
        "invalidation_condition": "Brent cierra debajo de 88 USD dos dias seguidos.",
        "created_at_utc": TS,
        "evaluate_after": TS_LATER,
    }
    fields.update(overrides)
    columns = ", ".join(["call_id", "event_id", *fields])
    placeholders = ", ".join(["?"] * (len(fields) + 2))
    conn.execute(
        f"INSERT INTO calls ({columns}) VALUES ({placeholders})",
        (call_id, event_id, *fields.values()),
    )
    return call_id


# --------------------------------------------------------------------------
# Estructura
# --------------------------------------------------------------------------


def test_init_crea_las_ocho_tablas_de_dominio(conn):
    tables = set(dbmod.table_names(conn))
    assert set(dbmod.DOMAIN_TABLES) <= tables
    assert "schema_migrations" in tables
    assert len(dbmod.DOMAIN_TABLES) == 8


def test_indices_del_spec_presentes(conn):
    expected = {
        "idx_ev_type_date", "idx_ev_regime", "idx_ev_sev", "idx_ev_occurred",
        "idx_news_hash", "idx_news_pub", "idx_news_event", "idx_news_dup", "idx_news_unclassified",
        "idx_outcomes_asset", "idx_calls_eval", "idx_calls_event",
        "idx_regimes_span", "idx_regimes_single_open", "idx_runs_stage",
    }
    assert expected <= set(dbmod.index_names(conn))


def test_version_de_schema_y_migracion_idempotente(conn):
    assert dbmod.schema_version(conn) == len(dbmod.discover_migrations())
    assert dbmod.migrate(conn) == []
    assert dbmod.pending_migrations(conn) == []


def test_checksum_detecta_migracion_editada(conn, tmp_path):
    original = dbmod.discover_migrations()
    mutada = [
        dbmod.Migration(m.version, m.name, m.path, m.sql + "\n-- editada despues de aplicar\n")
        for m in original
    ]
    with pytest.raises(dbmod.MigrationError, match="checksum"):
        dbmod.verify_checksums(conn, mutada)


def test_hueco_de_version_falla(tmp_path):
    (tmp_path / "001_a.sql").write_text("CREATE TABLE a (x INTEGER);", encoding="utf-8")
    (tmp_path / "003_c.sql").write_text("CREATE TABLE c (x INTEGER);", encoding="utf-8")
    with pytest.raises(dbmod.MigrationError, match="hueco"):
        dbmod.discover_migrations(tmp_path)


def test_foreign_keys_activas(conn):
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO outcomes (event_id, asset, ret_5d) VALUES ('no-existe', 'SPY', 0.01)"
        )


# --------------------------------------------------------------------------
# Constraints de dominio
# --------------------------------------------------------------------------


def test_severidad_fuera_de_rango_rechazada(conn):
    with pytest.raises(sqlite3.IntegrityError):
        insert_event(conn, event_id="malo", severity=6)


def test_timestamp_no_utc_rechazado(conn):
    with pytest.raises(sqlite3.IntegrityError):
        insert_event(conn, event_id="naive", occurred="2022-02-24 05:00:00")
    with pytest.raises(sqlite3.IntegrityError):
        insert_event(conn, event_id="local", occurred="2022-02-24T05:00:00-03:00")


def test_market_state_json_invalido_rechazado(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """INSERT INTO events_archive (event_id, occurred_at_utc, ingested_at_utc, event_type,
                                           headline, market_state_json)
               VALUES ('x', ?, ?, 'MACRO_DATA', 'test', 'no soy json')""",
            (TS, TS),
        )


def test_un_solo_regimen_abierto(conn):
    insert_regime(conn, "r1", start="2022-01-01", end=None)
    with pytest.raises(sqlite3.IntegrityError):
        insert_regime(conn, "r2", start="2022-06-01", end=None)
    insert_regime(conn, "r3", start="2022-06-01", end="2022-12-31")


def test_etiqueta_de_regimen_invalida_rechazada(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """INSERT INTO regimes (regime_id, regime_label, start_date, rate_regime, vol_regime,
                                    inflation_regime, usd_trend, credit_regime)
               VALUES ('x', 'x', '2022-01-01', 'HIKING', 'PANICO', 'ELEVATED', 'STRONG', 'NORMAL')"""
        )


def test_call_direccion_y_horizonte_acotados(conn):
    insert_event(conn)
    with pytest.raises(sqlite3.IntegrityError):
        insert_call(conn, call_id="c-dir", direction_bias="SIDEWAYS")
    with pytest.raises(sqlite3.IntegrityError):
        insert_call(conn, call_id="c-hz", horizon="3d")
    with pytest.raises(sqlite3.IntegrityError):
        insert_call(conn, call_id="c-prob", probability=1.4)


def test_magnitud_es_rango_no_punto(conn):
    insert_event(conn)
    with pytest.raises(sqlite3.IntegrityError):
        insert_call(conn, call_id="c-mag", magnitude_low=0.05, magnitude_high=0.05)


def test_contraargumento_vacio_rechazado(conn):
    insert_event(conn)
    with pytest.raises(sqlite3.IntegrityError):
        insert_call(conn, call_id="c-ca", counterargument="   ")


def test_forced_fuerza_confidence_low(conn):
    insert_event(conn)
    with pytest.raises(sqlite3.IntegrityError):
        insert_call(conn, call_id="c-forced", regime_match_quality="FORCED", confidence="HIGH")
    insert_call(conn, call_id="c-forced-ok", regime_match_quality="FORCED", confidence="LOW")


def test_evaluate_after_posterior_a_created_at(conn):
    insert_event(conn)
    with pytest.raises(sqlite3.IntegrityError):
        insert_call(conn, call_id="c-time", created_at_utc=TS_LATER, evaluate_after=TS)


def test_un_resultado_por_call_y_hit_nulo_permitido(conn):
    insert_event(conn)
    insert_call(conn)
    conn.execute(
        "INSERT INTO call_results (call_id, realized_return, hit, evaluated_at) VALUES ('c1', 0.002, NULL, ?)",
        (TS_LATER,),
    )
    assert conn.execute("SELECT hit FROM call_results WHERE call_id='c1'").fetchone()["hit"] is None
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO call_results (call_id, hit) VALUES ('c1', 1)")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO call_results (call_id, hit) VALUES ('c1', 2)")


def test_outcomes_pk_compuesta_y_cascade(conn):
    insert_event(conn)
    conn.execute("INSERT INTO outcomes (event_id, asset, ret_5d) VALUES ('ukraine-2022', 'BNO', 0.082)")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO outcomes (event_id, asset, ret_5d) VALUES ('ukraine-2022', 'BNO', 0.09)")
    conn.execute("INSERT INTO outcomes (event_id, asset, ret_5d) VALUES ('ukraine-2022', 'XLE', 0.061)")
    conn.execute("DELETE FROM events_archive WHERE event_id='ukraine-2022'")
    assert conn.execute("SELECT COUNT(*) AS n FROM outcomes").fetchone()["n"] == 0


def test_evento_con_calls_no_se_borra(conn):
    insert_event(conn)
    insert_call(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM events_archive WHERE event_id='ukraine-2022'")


def test_drawdown_positivo_rechazado(conn):
    insert_event(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO outcomes (event_id, asset, max_drawdown_20d) VALUES ('ukraine-2022', 'SPY', 0.12)"
        )


def test_narrative_state_es_append_only_monotonico(conn):
    for i in range(3):
        conn.execute(
            "INSERT INTO narrative_state (created_at, dominant_narrative) VALUES (?, ?)",
            (TS, f"narrativa {i}"),
        )
    versions = [row["version"] for row in conn.execute("SELECT version FROM narrative_state ORDER BY version")]
    assert versions == [1, 2, 3]
    conn.execute("DELETE FROM narrative_state WHERE version=3")
    conn.execute("INSERT INTO narrative_state (created_at, dominant_narrative) VALUES (?, 'nueva')", (TS,))
    assert conn.execute("SELECT MAX(version) AS v FROM narrative_state").fetchone()["v"] == 4


def test_run_fallido_exige_error(conn):
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO runs (run_id, stage, started_at, status) VALUES ('r1', 'ingest', ?, 'FAILED')",
            (TS,),
        )
    conn.execute(
        "INSERT INTO runs (run_id, stage, started_at, status, error) VALUES ('r1', 'ingest', ?, 'FAILED', 'timeout')",
        (TS,),
    )


def test_noticia_no_puede_ser_duplicado_de_si_misma(conn):
    conn.execute(
        "INSERT INTO raw_news (news_id, fetched_at_utc, title) VALUES ('n1', ?, 'titulo')",
        (TS,),
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE raw_news SET duplicate_of='n1' WHERE news_id='n1'")


# --------------------------------------------------------------------------
# Operacion
# --------------------------------------------------------------------------


def test_backup_es_legible_y_completo(tmp_path):
    db_path = tmp_path / "news.db"
    conn, _ = dbmod.init_db(db_path)
    insert_event(conn)
    conn.close()

    previous = set_clock(FrozenClock(datetime(2026, 8, 14, 4, 0, tzinfo=timezone.utc)))
    try:
        dest = dbmod.backup(db_path, tmp_path / "backups")
    finally:
        set_clock(previous)

    assert dest.name == "news_20260814.db"
    copy = dbmod.connect(dest)
    try:
        assert copy.execute("SELECT COUNT(*) AS n FROM events_archive").fetchone()["n"] == 1
        assert dbmod.schema_version(copy) == len(dbmod.discover_migrations())
    finally:
        copy.close()


def test_reset_exige_confirmacion(tmp_path):
    db_path = tmp_path / "news.db"
    conn, _ = dbmod.init_db(db_path)
    insert_event(conn)
    conn.close()

    with pytest.raises(RuntimeError):
        dbmod.reset(db_path, confirm=False)

    dbmod.reset(db_path, confirm=True)
    conn = dbmod.connect(db_path)
    try:
        assert conn.execute("SELECT COUNT(*) AS n FROM events_archive").fetchone()["n"] == 0
        assert dbmod.schema_version(conn) == len(dbmod.discover_migrations())
    finally:
        conn.close()


def test_integrity_check_limpio(conn):
    insert_event(conn)
    assert dbmod.integrity_check(conn) == []


def test_clock_rechaza_timestamps_naive():
    with pytest.raises(ValueError):
        format_utc(datetime(2022, 2, 24, 5, 0))
    assert format_utc(datetime(2022, 2, 24, 5, 0, tzinfo=timezone.utc)) == TS
