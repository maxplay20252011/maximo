"""Tests del clasificador de regimen (§4).

Mundos sinteticos construidos para que la respuesta correcta se conozca de
antemano. Las series ruidosas dependen del dia de la semana: el paso de recalculo
es semanal, asi que todas las fechas evaluadas caen en el mismo dia habil y el
percentil del valor corriente es estable. Sin eso el ruido haria oscilar el
regimen y el test no mediria el clasificador sino el ruido.

La verificacion que importa de verdad -- 2008-09 CRISIS, 2017 LOW, 2021 ZIRP,
2022-23 HIKING + ELEVATED -- exige datos reales y esta pendiente (§C.3).
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from classify import regime as regime_mod
from core import db as dbmod
from pit import macro as macro_mod
from pit import prices as price_mod

THRESHOLDS = regime_mod.load_thresholds("config/thresholds.yaml")
REGIMES = THRESHOLDS["regimes"]


@pytest.fixture()
def conn(tmp_path):
    connection, _ = dbmod.init_db(tmp_path / "regimes.db")
    yield connection
    connection.close()


def business_days(start: date, end: date):
    day = start
    while day <= end:
        if day.weekday() < 5:
            yield day
        day += timedelta(days=1)


def seed_world(
    conn,
    start: date,
    end: date,
    *,
    vix=lambda d: 15.0 + d.weekday(),
    dxy=lambda d: 100.0,
    dff=lambda d: 0.10,
    oas=lambda d: 4.0 + d.weekday() * 0.1,
    cpi=lambda d: 100.0,
) -> None:
    """Mundo completo: VIX, DXY (precios) y DFF, HY OAS, core CPI (macro)."""
    precios, macro = [], []
    for day in business_days(start, end):
        precios.append(price_mod.PriceRow("VIX", day, vix(day)))
        precios.append(price_mod.PriceRow("DXY", day, dxy(day)))
        macro.append(macro_mod.MacroObservation("DFF", day, day, dff(day)))
        macro.append(macro_mod.MacroObservation("BAMLH0A0HYM2", day, day, oas(day)))

    mes = date(start.year, start.month, 1)
    while mes <= end:
        macro.append(macro_mod.MacroObservation("CPILFESL", mes, mes + timedelta(days=40), cpi(mes)))
        mes = (mes + timedelta(days=32)).replace(day=1)

    price_mod.upsert_prices(conn, precios, source="test")
    macro_mod.upsert_observations(conn, macro, source="test")


# ---------------------------------------------------------------------------
# Tramos
# ---------------------------------------------------------------------------


def test_los_tramos_son_semiabiertos():
    vol = REGIMES["vol_regime"]
    assert regime_mod._bucket(0.00, vol) == "LOW"
    assert regime_mod._bucket(0.24, vol) == "LOW"
    assert regime_mod._bucket(0.25, vol) == "NORMAL"     # el limite inferior entra
    assert regime_mod._bucket(0.75, vol) == "STRESSED"
    assert regime_mod._bucket(0.95, vol) == "CRISIS"
    assert regime_mod._bucket(1.00, vol) == "CRISIS"     # el ultimo tramo cierra


def test_tramos_de_inflacion():
    infl = REGIMES["inflation_regime"]
    assert regime_mod._bucket(0.4, infl) == "DEFLATIONARY"
    assert regime_mod._bucket(2.0, infl) == "ANCHORED"
    assert regime_mod._bucket(2.5, infl) == "ELEVATED"
    assert regime_mod._bucket(6.5, infl) == "RUNAWAY"


def test_percentil_cuenta_menores_o_iguales():
    assert regime_mod._percentile_of(10, [10]) == 1.0
    assert regime_mod._percentile_of(5, [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]) == 0.5


# ---------------------------------------------------------------------------
# Dimensiones
# ---------------------------------------------------------------------------


def test_vol_regime_crisis_cuando_el_vix_esta_en_el_tope(conn):
    fin = date(2020, 3, 20)
    seed_world(conn, fin - timedelta(days=900), fin, vix=lambda d: 60.0 if d >= date(2020, 3, 1) else 15.0)
    snapshot = regime_mod.classify_at(conn, fin, THRESHOLDS)
    assert snapshot.vol_regime == "CRISIS"
    assert snapshot.vix_pctile == 1.0


def test_vol_regime_normal_en_el_medio_de_la_distribucion(conn):
    fin = date(2019, 6, 12)   # miercoles: VIX 17 sobre una muestra de 15 a 19
    seed_world(conn, fin - timedelta(days=900), fin)
    snapshot = regime_mod.classify_at(conn, fin, THRESHOLDS)
    assert snapshot.vol_regime == "NORMAL"
    assert 0.25 <= snapshot.vix_pctile < 0.75


def test_vol_regime_sin_historia_suficiente_no_se_inventa(conn):
    fin = date(2019, 6, 14)
    seed_world(conn, fin - timedelta(days=60), fin)   # ~40 observaciones
    snapshot = regime_mod.classify_at(conn, fin, THRESHOLDS)
    assert snapshot.vol_regime is None
    assert "vol_regime" in snapshot.missing
    assert not snapshot.complete


def test_rate_regime_zirp_gana_con_tasa_baja(conn):
    fin = date(2021, 6, 15)
    seed_world(conn, fin - timedelta(days=900), fin, dff=lambda d: 0.08)
    assert regime_mod.classify_at(conn, fin, THRESHOLDS).rate_regime == "ZIRP"


def test_rate_regime_hiking(conn):
    fin = date(2022, 9, 15)
    inicio_ciclo = date(2022, 3, 16)
    seed_world(
        conn, fin - timedelta(days=900), fin,
        dff=lambda d: 0.08 if d < inicio_ciclo else 0.08 + (d - inicio_ciclo).days * 0.015,
    )
    snapshot = regime_mod.classify_at(conn, fin, THRESHOLDS)
    assert snapshot.rate_regime == "HIKING"
    assert snapshot.inputs["policy_rate_change_6m"] >= 0.50


def test_rate_regime_cutting(conn):
    fin = date(2024, 12, 15)
    pico = date(2024, 6, 1)
    seed_world(
        conn, fin - timedelta(days=900), fin,
        dff=lambda d: 5.33 if d < pico else max(4.0, 5.33 - (d - pico).days * 0.005),
    )
    assert regime_mod.classify_at(conn, fin, THRESHOLDS).rate_regime == "CUTTING"


def test_rate_regime_high_stable(conn):
    fin = date(2024, 3, 15)
    seed_world(conn, fin - timedelta(days=900), fin, dff=lambda d: 5.33)
    assert regime_mod.classify_at(conn, fin, THRESHOLDS).rate_regime == "HIGH_STABLE"


def test_inflacion_yoy_se_calcula_sobre_los_vintages(conn):
    fin = date(2022, 6, 15)

    def cpi(mes: date) -> float:
        # 3.5% interanual exacto por construccion.
        return 100.0 * (1.035 ** ((mes.year - 2015) + mes.month / 12))

    seed_world(conn, fin - timedelta(days=900), fin, cpi=cpi)
    snapshot = regime_mod.classify_at(conn, fin, THRESHOLDS)
    assert snapshot.inflation_regime == "ELEVATED"
    assert snapshot.inputs["core_cpi_yoy"] == pytest.approx(3.5, abs=0.05)


def test_usd_trend(conn):
    fin = date(2022, 9, 15)
    inicio = fin - timedelta(days=900)

    seed_world(conn, inicio, fin, dxy=lambda d: 100.0 * (1.0005 ** (d - inicio).days))
    assert regime_mod.classify_at(conn, fin, THRESHOLDS).usd_trend == "STRONG"

    conn.execute("DELETE FROM prices WHERE asset='DXY'")
    seed_world(conn, inicio, fin, dxy=lambda d: 100.0 * (0.9995 ** (d - inicio).days))
    assert regime_mod.classify_at(conn, fin, THRESHOLDS).usd_trend == "WEAK"

    conn.execute("DELETE FROM prices WHERE asset='DXY'")
    seed_world(conn, inicio, fin, dxy=lambda d: 100.0)
    assert regime_mod.classify_at(conn, fin, THRESHOLDS).usd_trend == "NEUTRAL"


# ---------------------------------------------------------------------------
# Point-in-time
# ---------------------------------------------------------------------------


def test_una_revision_posterior_no_reescribe_el_regimen(conn):
    """El nucleo del asunto: clasificar el 15 de junio tiene que dar lo mismo
    mirado desde el 15 de junio que mirado desde hoy. Y mirar hoy, con la serie
    ya revisada, tiene que dar la lectura revisada."""
    fin = date(2022, 6, 15)
    seed_world(
        conn, fin - timedelta(days=900), fin,
        cpi=lambda mes: 100.0 * (1.02 ** ((mes.year - 2015) + mes.month / 12)),   # 2% -> ANCHORED
    )
    assert regime_mod.classify_at(conn, fin, THRESHOLDS).inflation_regime == "ANCHORED"

    # Revision publicada el 2022-06-20 que reescribe toda la serie a 4% YoY.
    revisados, mes = [], date(2019, 1, 1)
    while mes <= fin:
        revisados.append(
            macro_mod.MacroObservation(
                "CPILFESL", mes, date(2022, 6, 20),
                100.0 * (1.04 ** ((mes.year - 2015) + mes.month / 12)),
            )
        )
        mes = (mes + timedelta(days=32)).replace(day=1)
    macro_mod.upsert_observations(conn, revisados, source="test")

    # Mirado desde el 15 de junio la revision no existe todavia.
    assert regime_mod.classify_at(conn, fin, THRESHOLDS).inflation_regime == "ANCHORED"
    # Mirado desde el 25 de junio, si.
    posterior = regime_mod.classify_at(conn, date(2022, 6, 25), THRESHOLDS)
    assert posterior.inflation_regime == "ELEVATED"
    assert posterior.inputs["core_cpi_yoy"] == pytest.approx(4.0, abs=0.05)


# ---------------------------------------------------------------------------
# Linea de tiempo
# ---------------------------------------------------------------------------


def test_un_cambio_de_dimension_abre_un_episodio_nuevo(conn):
    inicio_datos = date(2019, 1, 1)
    fin = date(2022, 12, 31)
    salto = date(2021, 7, 1)

    def cpi(mes: date) -> float:
        tasa = 1.02 if mes < salto else 1.06
        return 100.0 * (tasa ** ((mes.year - 2015) + mes.month / 12))

    seed_world(conn, inicio_datos, fin, cpi=cpi)

    report = regime_mod.build_regimes(conn, date(2021, 1, 1), fin, THRESHOLDS)
    episodios = regime_mod.timeline(conn)

    assert report.episodios_creados == len(episodios) >= 2
    etiquetas = [row["inflation_regime"] for row in episodios]
    assert etiquetas[0] == "ANCHORED"
    assert "ELEVATED" in etiquetas or "RUNAWAY" in etiquetas

    abiertos = [row for row in episodios if row["end_date"] is None]
    assert len(abiertos) == 1

    for previo, siguiente in zip(episodios, episodios[1:]):
        assert previo["end_date"] is not None
        assert date.fromisoformat(previo["end_date"]) < date.fromisoformat(siguiente["start_date"])


def test_sin_datos_no_se_crea_ningun_episodio(conn):
    report = regime_mod.build_regimes(conn, date(2021, 1, 1), date(2021, 6, 30), THRESHOLDS)
    assert report.episodios_creados == 0
    assert report.fechas_sin_clasificar == report.fechas_evaluadas
    assert set(report.faltantes_por_dimension) == set(regime_mod.DIMENSIONS)


def test_regime_at_encuentra_el_episodio_vigente(conn):
    seed_world(conn, date(2019, 1, 1), date(2022, 12, 31))
    regime_mod.build_regimes(conn, date(2021, 1, 1), date(2022, 12, 31), THRESHOLDS)

    vigente = regime_mod.regime_at(conn, date(2022, 6, 15))
    assert vigente is not None
    assert vigente["start_date"] <= "2022-06-15"
    assert regime_mod.regime_at(conn, date(2015, 1, 1)) is None


def test_reconstruir_falla_si_hay_eventos_apuntando(conn):
    seed_world(conn, date(2019, 1, 1), date(2022, 12, 31))
    regime_mod.build_regimes(conn, date(2021, 1, 1), date(2022, 12, 31), THRESHOLDS)
    episodio = regime_mod.timeline(conn)[0]

    conn.execute(
        """INSERT INTO events_archive (event_id, occurred_at_utc, ingested_at_utc, event_type,
                                       headline, regime_id, market_state_json)
           VALUES ('e1', '2022-02-24T05:00:00Z', '2022-02-24T05:10:00Z', 'GEOPOLITICAL',
                   'test', ?, '{}')""",
        (episodio["regime_id"],),
    )
    with pytest.raises(RuntimeError, match="eventos referencian"):
        regime_mod.clear_regimes(conn)


def test_el_id_de_regimen_lleva_la_fecha_de_apertura(conn):
    seed_world(conn, date(2019, 1, 1), date(2022, 12, 31))
    regime_mod.build_regimes(conn, date(2021, 1, 1), date(2022, 12, 31), THRESHOLDS)
    for row in regime_mod.timeline(conn):
        assert row["regime_id"] == f"{row['regime_label']}@{row['start_date']}"


# ---------------------------------------------------------------------------
# Estabilidad: histeresis y duracion minima
# ---------------------------------------------------------------------------


def test_histeresis_aguanta_el_vaiven_en_el_limite():
    vol = REGIMES["vol_regime"]
    margen = REGIMES["hysteresis"]["vol_regime"]   # 0.03

    # Estando en NORMAL [0.25, 0.75): cruzar apenas no alcanza para irse.
    assert regime_mod._bucket_hysteretic(0.76, vol, "NORMAL", margen) == "NORMAL"
    assert regime_mod._bucket_hysteretic(0.77, vol, "NORMAL", margen) == "NORMAL"
    assert regime_mod._bucket_hysteretic(0.79, vol, "NORMAL", margen) == "STRESSED"

    # Y al reves: estando en STRESSED, volver apenas tampoco alcanza.
    assert regime_mod._bucket_hysteretic(0.74, vol, "STRESSED", margen) == "STRESSED"
    assert regime_mod._bucket_hysteretic(0.71, vol, "STRESSED", margen) == "NORMAL"

    # Sin regimen vigente no hay de que salir: se aplica el tramo pelado.
    assert regime_mod._bucket_hysteretic(0.76, vol, None, margen) == "STRESSED"


def test_histeresis_no_frena_un_salto_de_verdad():
    vol = REGIMES["vol_regime"]
    assert regime_mod._bucket_hysteretic(0.99, vol, "LOW", 0.03) == "CRISIS"


def test_una_excursion_corta_no_abre_episodio(conn):
    """Dos semanas de VIX alto no son un regimen nuevo."""
    seed_world(
        conn, date(2018, 1, 1), date(2021, 6, 30),
        vix=lambda d: 60.0 if date(2021, 3, 1) <= d <= date(2021, 3, 14) else 15.0 + d.weekday(),
    )
    report = regime_mod.build_regimes(conn, date(2021, 1, 6), date(2021, 6, 30), THRESHOLDS)

    episodios = regime_mod.timeline(conn)
    assert len(episodios) == 1
    assert report.cambios_descartados >= 1
    assert episodios[0]["vol_regime"] == "NORMAL"


def test_un_cambio_sostenido_si_abre_episodio_y_arranca_cuando_aparecio(conn):
    seed_world(
        conn, date(2018, 1, 1), date(2021, 6, 30),
        vix=lambda d: 60.0 if d >= date(2021, 3, 1) else 15.0 + d.weekday(),
    )
    regime_mod.build_regimes(conn, date(2021, 1, 6), date(2021, 6, 30), THRESHOLDS)

    episodios = regime_mod.timeline(conn)
    assert len(episodios) == 2
    assert episodios[0]["vol_regime"] == "NORMAL"
    assert episodios[1]["vol_regime"] == "CRISIS"
    # El episodio arranca el primer paso en que aparecio el cambio (2021-03-03),
    # no cuatro semanas despues cuando se confirmo.
    assert episodios[1]["start_date"] == "2021-03-03"
    assert episodios[0]["end_date"] == "2021-03-02"


def test_incremental_no_duplica_episodios(conn):
    seed_world(conn, date(2018, 1, 1), date(2021, 6, 30))
    regime_mod.build_regimes(conn, date(2021, 1, 6), date(2021, 3, 31), THRESHOLDS)
    antes = len(regime_mod.timeline(conn))

    abierto = regime_mod.current_regime(conn)
    regime_mod.build_regimes(conn, date.fromisoformat(abierto["start_date"]), date(2021, 6, 30), THRESHOLDS)
    assert len(regime_mod.timeline(conn)) == antes
