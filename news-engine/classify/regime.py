"""Clasificador de regimen (§4).

Cinco dimensiones, umbrales fijos en config/thresholds.yaml. Sin criterio: la
funcion no decide nada que no este escrito en el archivo de umbrales.

Todo se lee point-in-time. El regimen de una fecha se clasifica con lo que se
sabia esa fecha: el CPI de marzo 2020 clasificado desde abril usa el vintage de
abril, no el revisado de 2021. Una revision posterior no puede reescribir la
historia de regimenes.

Una dimension sin datos suficientes queda en None y la fecha entera no se
clasifica. Preferible a un regimen inventado sobre cuatro dimensiones y media.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

import yaml

from core.clock import format_utc
from pit import macro as macro_mod
from pit import prices as price_mod
from pit.guards import as_of as as_of_ctx

DEFAULT_THRESHOLDS_PATH = "config/thresholds.yaml"

DIMENSIONS = ("rate_regime", "vol_regime", "inflation_regime", "usd_trend", "credit_regime")


def load_thresholds(path: str = DEFAULT_THRESHOLDS_PATH) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle)["regimes"]


@dataclass(frozen=True)
class RegimeSnapshot:
    """Clasificacion de una fecha. `label` es la concatenacion de las 5 etiquetas."""

    as_of_date: date
    rate_regime: str | None
    vol_regime: str | None
    inflation_regime: str | None
    usd_trend: str | None
    credit_regime: str | None
    vix_pctile: float | None = None
    hy_oas_pctile: float | None = None
    inputs: dict[str, float | None] = None  # type: ignore[assignment]
    missing: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        return not self.missing

    @property
    def label(self) -> str:
        return "-".join(str(getattr(self, dim)) for dim in DIMENSIONS)

    def regime_id(self, start: date) -> str:
        """Etiqueta + fecha de apertura.

        §4 define el id como la concatenacion de las cinco etiquetas. Como clave
        primaria eso colisiona: la misma combinacion vuelve a ocurrir aniós
        despues y seria un segundo episodio con el mismo id. El sufijo con la
        fecha de apertura los separa; `regime_label` guarda la concatenacion
        pura, que es la que compara el matcher (§7.1).
        """
        return f"{self.label}@{start.isoformat()}"


# ---------------------------------------------------------------------------
# Clasificacion de una fecha
# ---------------------------------------------------------------------------


def classify_at(
    conn: sqlite3.Connection,
    when: date,
    thresholds: dict[str, Any],
    previous: dict[str, str | None] | None = None,
) -> RegimeSnapshot:
    """Clasifica `when` usando solo datos publicos a esa fecha.

    `previous` son las etiquetas vigentes en el paso anterior. Con eso se aplica
    la histeresis: para abandonar un tramo hay que cruzar su limite por el margen
    de config. Sin `previous` no hay histeresis, que es lo correcto para una
    clasificacion suelta: no hay tramo vigente del que salir.
    """
    moment = datetime.combine(when, time(23, 59, 59), tzinfo=timezone.utc)
    inputs: dict[str, float | None] = {}
    anterior = previous or {}

    with as_of_ctx(moment):
        vol_label, vix_pctile, vix_level = _vol_regime(conn, when, moment, thresholds, anterior.get("vol_regime"))
        credit_label, oas_pctile, oas_level = _credit_regime(conn, when, moment, thresholds, anterior.get("credit_regime"))
        rate_label, policy_rate, rate_change = _rate_regime(conn, moment, thresholds, anterior.get("rate_regime"))
        infl_label, core_yoy = _inflation_regime(conn, moment, thresholds, anterior.get("inflation_regime"))
        usd_label, dxy_return = _usd_trend(conn, when, moment, thresholds, anterior.get("usd_trend"))

    inputs.update(
        {
            "vix": vix_level,
            "hy_oas": oas_level,
            "policy_rate": policy_rate,
            "policy_rate_change_6m": rate_change,
            "core_cpi_yoy": core_yoy,
            "dxy_60d_return": dxy_return,
        }
    )

    snapshot = RegimeSnapshot(
        as_of_date=when,
        rate_regime=rate_label,
        vol_regime=vol_label,
        inflation_regime=infl_label,
        usd_trend=usd_label,
        credit_regime=credit_label,
        vix_pctile=vix_pctile,
        hy_oas_pctile=oas_pctile,
        inputs=inputs,
    )
    faltantes = tuple(dim for dim in DIMENSIONS if getattr(snapshot, dim) is None)
    return replace(snapshot, missing=faltantes)


def _margin(thresholds: dict[str, Any], dimension: str) -> float:
    return float(thresholds.get("hysteresis", {}).get(dimension, 0.0))


def _vol_regime(
    conn: sqlite3.Connection, when: date, moment: datetime, thresholds: dict[str, Any], previous: str | None
) -> tuple[str | None, float | None, float | None]:
    config = thresholds["vol_regime"]
    pctile, level = _price_percentile(conn, config["serie"], when, moment, thresholds)
    if pctile is None:
        return None, None, level
    label = _bucket_hysteretic(pctile, config, previous, _margin(thresholds, "vol_regime"))
    return label, round(pctile, 4), level


def _credit_regime(
    conn: sqlite3.Connection, when: date, moment: datetime, thresholds: dict[str, Any], previous: str | None
) -> tuple[str | None, float | None, float | None]:
    config = thresholds["credit_regime"]
    window_start = when - timedelta(days=thresholds["percentile_window_days"])
    serie = macro_mod.get_series_window_as_known_at(conn, config["serie"], window_start, when, moment)
    if len(serie) < thresholds["percentile_min_observations"]:
        return None, None, serie[-1][1] if serie else None

    level = serie[-1][1]
    pctile = _percentile_of(level, [value for _, value in serie])
    label = _bucket_hysteretic(pctile, config, previous, _margin(thresholds, "credit_regime"))
    return label, round(pctile, 4), level


def _rate_regime(
    conn: sqlite3.Connection, moment: datetime, thresholds: dict[str, Any], previous: str | None
) -> tuple[str | None, float | None, float | None]:
    config = thresholds["rate_regime"]
    latest = macro_mod.get_latest_macro_as_known_at(conn, config["serie"], moment, max_staleness_days=60)
    if latest is None:
        return None, None, None
    _, policy_rate = latest

    change = macro_mod.series_change_as_known_at(conn, config["serie"], moment, months=config["meses"])
    if change is None:
        return None, policy_rate, None

    margen = _margin(thresholds, "rate_regime")
    techo_zirp = config["ZIRP"]["policy_rate_max"]
    piso_hiking = config["HIKING"]["change_6m_min"]
    techo_cutting = config["CUTTING"]["change_6m_max"]

    # Histeresis: quedarse en el tramo vigente mientras no se cruce con margen.
    if previous == "ZIRP" and policy_rate <= techo_zirp + margen:
        return "ZIRP", policy_rate, round(change, 4)
    if previous == "HIKING" and change >= piso_hiking - margen and policy_rate > techo_zirp:
        return "HIKING", policy_rate, round(change, 4)
    if previous == "CUTTING" and change <= techo_cutting + margen and policy_rate > techo_zirp:
        return "CUTTING", policy_rate, round(change, 4)

    # Orden de §4: ZIRP primero.
    if policy_rate <= techo_zirp:
        return "ZIRP", policy_rate, round(change, 4)
    if change >= piso_hiking:
        return "HIKING", policy_rate, round(change, 4)
    if change <= techo_cutting:
        return "CUTTING", policy_rate, round(change, 4)
    return "HIGH_STABLE", policy_rate, round(change, 4)


def _inflation_regime(
    conn: sqlite3.Connection, moment: datetime, thresholds: dict[str, Any], previous: str | None
) -> tuple[str | None, float | None]:
    config = thresholds["inflation_regime"]
    yoy = _yoy_as_known_at(conn, config["serie"], moment)
    if yoy is None:
        return None, None
    label = _bucket_hysteretic(yoy, config, previous, _margin(thresholds, "inflation_regime"))
    return label, round(yoy, 4)


def _usd_trend(
    conn: sqlite3.Connection, when: date, moment: datetime, thresholds: dict[str, Any], previous: str | None
) -> tuple[str | None, float | None]:
    config = thresholds["usd_trend"]
    sesiones = config["sesiones"]
    dias = price_mod.trading_days_before(conn, config["serie"], when, sesiones + 1)
    if len(dias) < sesiones + 1:
        return None, None
    try:
        retorno = price_mod.get_return_as_known_at(conn, config["serie"], dias[-1], dias[0], moment)
    except price_mod.PriceDataError:
        return None, None

    margen = _margin(thresholds, "usd_trend")
    piso_strong = config["STRONG"]["min"]
    techo_weak = config["WEAK"]["max"]

    if previous == "STRONG" and retorno >= piso_strong - margen:
        return "STRONG", round(retorno, 4)
    if previous == "WEAK" and retorno <= techo_weak + margen:
        return "WEAK", round(retorno, 4)
    if previous == "NEUTRAL" and techo_weak - margen < retorno < piso_strong + margen:
        return "NEUTRAL", round(retorno, 4)

    if retorno >= piso_strong:
        return "STRONG", round(retorno, 4)
    if retorno <= techo_weak:
        return "WEAK", round(retorno, 4)
    return "NEUTRAL", round(retorno, 4)


# ---------------------------------------------------------------------------
# Construccion de la linea de tiempo
# ---------------------------------------------------------------------------


@dataclass
class BuildReport:
    episodios_creados: int = 0
    fechas_evaluadas: int = 0
    fechas_sin_clasificar: int = 0
    cambios_descartados: int = 0
    faltantes_por_dimension: dict[str, int] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.faltantes_por_dimension is None:
            self.faltantes_por_dimension = {}


@dataclass
class _Pending:
    """Cambio de etiqueta esperando confirmacion."""

    label: str
    first_seen: date
    snapshot: RegimeSnapshot
    steps: int = 1


def _labels_of(snapshot: RegimeSnapshot) -> dict[str, str | None]:
    return {dim: getattr(snapshot, dim) for dim in DIMENSIONS}


def _labels_of_row(row: sqlite3.Row) -> dict[str, str | None]:
    return {dim: row[dim] for dim in DIMENSIONS}


def build_regimes(
    conn: sqlite3.Connection,
    start: date,
    end: date,
    thresholds: dict[str, Any],
) -> BuildReport:
    """Recorre el periodo con el paso de §4 y arma los episodios.

    Un cambio de etiqueta no abre un episodio en el acto: tiene que sostenerse
    `min_episode_steps` pasos consecutivos. Si vuelve antes, no existio. Cuando
    se confirma, el episodio arranca la fecha en que el cambio aparecio, no la
    fecha en que se confirmo -- si no, la linea de tiempo quedaria corrida un mes.

    Reanudable: parte del ultimo episodio abierto que haya en la base. La ventana
    de confirmacion no se persiste, asi que un `--incremental` debe re-recorrer
    desde el inicio del episodio abierto, que es lo que hace el CLI.
    """
    report = BuildReport()
    step = timedelta(days=thresholds["step_days"])
    min_steps = int(thresholds.get("min_episode_steps", 1))

    abierto = conn.execute("SELECT * FROM regimes WHERE end_date IS NULL").fetchone()
    label_actual = abierto["regime_label"] if abierto else None
    id_actual = abierto["regime_id"] if abierto else None
    # Ancla de la histeresis: el regimen vigente. Para salir de el hay que cruzar
    # con margen; un vaiven de un paso no alcanza.
    anclaje = _labels_of_row(abierto) if abierto else None
    pendiente: _Pending | None = None

    when = start
    while when <= end:
        report.fechas_evaluadas += 1
        snapshot = classify_at(conn, when, thresholds, previous=anclaje)

        if not snapshot.complete:
            report.fechas_sin_clasificar += 1
            for dim in snapshot.missing:
                report.faltantes_por_dimension[dim] = report.faltantes_por_dimension.get(dim, 0) + 1
            when += step
            continue

        if label_actual is None:
            # Primer episodio: no hay nada de lo que dudar.
            id_actual = _insert_regime(conn, snapshot, when)
            label_actual = snapshot.label
            anclaje = _labels_of(snapshot)
            report.episodios_creados += 1
        elif snapshot.label == label_actual:
            if pendiente is not None:
                report.cambios_descartados += 1
            pendiente = None
        else:
            if pendiente is not None and pendiente.label == snapshot.label:
                pendiente.steps += 1
            else:
                if pendiente is not None:
                    report.cambios_descartados += 1
                pendiente = _Pending(label=snapshot.label, first_seen=when, snapshot=snapshot)

            if pendiente.steps >= min_steps:
                conn.execute(
                    "UPDATE regimes SET end_date = ? WHERE regime_id = ?",
                    ((pendiente.first_seen - timedelta(days=1)).isoformat(), id_actual),
                )
                id_actual = _insert_regime(conn, pendiente.snapshot, pendiente.first_seen)
                label_actual = pendiente.label
                anclaje = _labels_of(pendiente.snapshot)
                pendiente = None
                report.episodios_creados += 1

        when += step

    if pendiente is not None:
        report.cambios_descartados += 1

    return report


def _insert_regime(conn: sqlite3.Connection, snapshot: RegimeSnapshot, start: date) -> str:
    regime_id = snapshot.regime_id(start)
    conn.execute(
        """INSERT INTO regimes (regime_id, regime_label, start_date, end_date, rate_regime,
                                vol_regime, inflation_regime, usd_trend, credit_regime,
                                vix_pctile, hy_oas_pctile)
           VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?)""",
        (
            regime_id,
            snapshot.label,
            start.isoformat(),
            snapshot.rate_regime,
            snapshot.vol_regime,
            snapshot.inflation_regime,
            snapshot.usd_trend,
            snapshot.credit_regime,
            snapshot.vix_pctile,
            snapshot.hy_oas_pctile,
        ),
    )
    return regime_id


def regime_at(conn: sqlite3.Connection, when: date) -> sqlite3.Row | None:
    """Episodio vigente en una fecha. Es lo que asigna `events_archive.regime_id`."""
    return conn.execute(
        """SELECT * FROM regimes
           WHERE start_date <= ? AND (end_date IS NULL OR end_date >= ?)""",
        (when.isoformat(), when.isoformat()),
    ).fetchone()


def current_regime(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM regimes WHERE end_date IS NULL").fetchone()


def timeline(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM regimes ORDER BY start_date").fetchall()


def clear_regimes(conn: sqlite3.Connection) -> int:
    """Borra la linea de tiempo. Falla si hay eventos apuntando a un regimen:
    el FK es RESTRICT y esta bien que lo sea."""
    referencias = conn.execute(
        "SELECT COUNT(*) AS n FROM events_archive WHERE regime_id IS NOT NULL"
    ).fetchone()["n"]
    if referencias:
        raise RuntimeError(
            f"{referencias} eventos referencian regimenes. Reasignalos antes de reconstruir la linea de tiempo."
        )
    borrados = conn.execute("SELECT COUNT(*) AS n FROM regimes").fetchone()["n"]
    conn.execute("DELETE FROM regimes")
    return borrados


# ---------------------------------------------------------------------------
# Auxiliares numericos
# ---------------------------------------------------------------------------


def _bucket(value: float, config: dict[str, Any]) -> str | None:
    """Ubica un valor en los tramos [lo, hi) del config. El ultimo tramo cierra."""
    tramos = [(k, v) for k, v in config.items() if isinstance(v, list) and len(v) == 2]
    tramos.sort(key=lambda item: item[1][0])
    for index, (label, (lo, hi)) in enumerate(tramos):
        ultimo = index == len(tramos) - 1
        if lo <= value < hi or (ultimo and value == hi):
            return label
    return None


def _bucket_hysteretic(
    value: float, config: dict[str, Any], previous: str | None, margin: float
) -> str | None:
    """Como `_bucket`, pero para salir del tramo vigente hay que cruzar su limite
    por `margin`. Entrar no pide margen: la histeresis frena el vaiven, no la
    entrada a un regimen nuevo.
    """
    candidato = _bucket(value, config)
    if previous is None or margin <= 0 or candidato == previous:
        return candidato

    tramo = config.get(previous)
    if not isinstance(tramo, list) or len(tramo) != 2:
        return candidato   # el tramo anterior ya no existe en la config

    lo, hi = tramo
    if lo - margin <= value < hi + margin:
        return previous
    return candidato


def _percentile_of(value: float, sample: list[float]) -> float:
    """Fraccion de la muestra menor o igual al valor. 0.0 a 1.0."""
    if not sample:
        raise ValueError("muestra vacia")
    return sum(1 for x in sample if x <= value) / len(sample)


def _price_percentile(
    conn: sqlite3.Connection,
    asset: str,
    when: date,
    moment: datetime,
    thresholds: dict[str, Any],
) -> tuple[float | None, float | None]:
    window_start = when - timedelta(days=thresholds["percentile_window_days"])
    serie = price_mod.get_close_series_as_known_at(conn, asset, window_start, when, moment)
    if not serie:
        return None, None
    level = serie[-1][1]
    if len(serie) < thresholds["percentile_min_observations"]:
        return None, level
    return _percentile_of(level, [value for _, value in serie]), level


def _yoy_as_known_at(conn: sqlite3.Connection, series_id: str, moment: datetime) -> float | None:
    """Variacion interanual en porcentaje, con los vintages vigentes a `moment`."""
    latest = macro_mod.get_latest_macro_as_known_at(conn, series_id, moment, max_staleness_days=80)
    if latest is None:
        return None
    obs_date, value = latest

    try:
        hace_un_anio = date(obs_date.year - 1, obs_date.month, obs_date.day)
    except ValueError:  # 29 de febrero
        hace_un_anio = date(obs_date.year - 1, obs_date.month, 28)
    previo = conn.execute(
        """SELECT obs_date, value, MAX(vintage_date) AS vintage_date
           FROM macro_observations
           WHERE series_id = ? AND vintage_date <= ? AND obs_date <= ? AND value IS NOT NULL
           GROUP BY obs_date ORDER BY obs_date DESC LIMIT 1""",
        (series_id, moment.date().isoformat(), hace_un_anio.isoformat()),
    ).fetchone()
    if previo is None or not previo["value"]:
        return None

    base_date = date.fromisoformat(previo["obs_date"])
    if abs((hace_un_anio - base_date).days) > 45:
        return None  # el punto de comparacion esta demasiado lejos de 12 meses

    return (value / float(previo["value"]) - 1.0) * 100.0


def snapshot_to_text(snapshot: RegimeSnapshot) -> str:
    if snapshot.complete:
        return snapshot.label
    return f"SIN CLASIFICAR (falta: {', '.join(snapshot.missing)})"


def format_moment(when: date) -> str:
    return format_utc(datetime.combine(when, time(23, 59, 59), tzinfo=timezone.utc))
