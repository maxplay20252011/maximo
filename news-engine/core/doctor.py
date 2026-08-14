"""Diagnostico del sistema (§C.7).

Responde una sola pregunta: que anda y que no. Cada chequeo devuelve OK, AVISO,
FALLA o PENDIENTE, y el detalle dice que hacer.

PENDIENTE no es una falla: marca una pieza que todavia no se construyo. Un
sistema a medio hacer que reporta todo verde miente igual que uno roto.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from core import db as dbmod
from core.clock import now

OK, AVISO, FALLA, PENDIENTE = "OK", "AVISO", "FALLA", "PENDIENTE"

FUENTES = {
    "stooq": "https://stooq.com",
    "alfred": "https://api.stlouisfed.org",
    "gdelt": "https://api.gdeltproject.org",
    "edgar": "https://www.sec.gov",
}


@dataclass(frozen=True)
class Check:
    nombre: str
    estado: str
    detalle: str

    @property
    def bloqueante(self) -> bool:
        return self.estado == FALLA


def run_all(db_path: str | Path | None = None, *, red: bool = False) -> list[Check]:
    checks: list[Check] = [_credenciales()]
    path = dbmod.resolve_db_path(db_path)

    if not path.exists():
        checks.append(Check("base de datos", FALLA, f"no existe {path}. Corre: python run.py db init"))
        return checks

    conn = dbmod.connect(path)
    try:
        checks.extend(
            [
                _schema(conn, path),
                _guardas(),
                _precios(conn),
                _macro(conn),
                _regimenes(conn),
                _corpus(conn),
                _outcomes(conn),
                _noticias(conn),
                _calls_huerfanos(conn),
                _integridad(conn),
                _disco(path),
            ]
        )
        if red:
            checks.extend(_conectividad())
    finally:
        conn.close()
    return checks


# ---------------------------------------------------------------------------


def _credenciales() -> Check:
    faltantes = [k for k in ("FRED_API_KEY",) if not os.environ.get(k)]
    opcionales = [k for k in ("FINNHUB_API_KEY", "ANTHROPIC_API_KEY") if not os.environ.get(k)]
    if faltantes:
        return Check("credenciales", AVISO, f"falta {', '.join(faltantes)} en .env: sin eso no hay vintages de ALFRED")
    if opcionales:
        return Check("credenciales", OK, f"FRED presente; faltan las de tareas posteriores: {', '.join(opcionales)}")
    return Check("credenciales", OK, "todas presentes")


def _schema(conn: sqlite3.Connection, path: Path) -> Check:
    version = dbmod.schema_version(conn)
    pendientes = dbmod.pending_migrations(conn)
    if pendientes:
        return Check("schema", FALLA, f"version {version}, {len(pendientes)} migraciones sin aplicar. Corre: db migrate")
    faltan = [t for t in dbmod.DOMAIN_TABLES if t not in dbmod.table_names(conn)]
    if faltan:
        return Check("schema", FALLA, f"faltan tablas: {', '.join(faltan)}")
    return Check("schema", OK, f"version {version}, {len(dbmod.DOMAIN_TABLES)} tablas de dominio")


def _guardas() -> Check:
    from pit.verify import run_all_guards

    resultados = run_all_guards()
    fallidas = [r for r in resultados if not r.passed]
    if fallidas:
        return Check("guardas anti-look-ahead", FALLA, f"fallan {len(fallidas)}/{len(resultados)}: {fallidas[0].detail}")
    return Check("guardas anti-look-ahead", OK, f"{len(resultados)}/{len(resultados)} pasan")


def _precios(conn: sqlite3.Connection) -> Check:
    fila = conn.execute(
        "SELECT COUNT(*) AS n, COUNT(DISTINCT asset) AS activos, MAX(price_date) AS ultimo FROM prices"
    ).fetchone()
    if not fila["n"]:
        return Check("precios", PENDIENTE, "sin cierres cargados. Corre: pit load-prices --from 2005-01-01")

    ultimo = date.fromisoformat(fila["ultimo"])
    atraso = (now().date() - ultimo).days
    detalle = f"{fila['n']} cierres, {fila['activos']} activos, ultimo {fila['ultimo']}"
    if atraso > 5:
        return Check("precios", AVISO, f"{detalle} ({atraso} dias de atraso). Corre: pit load-prices --incremental")
    return Check("precios", OK, detalle)


def _macro(conn: sqlite3.Connection) -> Check:
    fila = conn.execute(
        "SELECT COUNT(*) AS n, COUNT(DISTINCT series_id) AS series FROM macro_observations"
    ).fetchone()
    if not fila["n"]:
        return Check("macro", PENDIENTE, "sin series cargadas. Corre: pit load-macro --vintages --from 2005-01-01")
    return Check("macro", OK, f"{fila['n']} observaciones, {fila['series']} series con vintages")


def _regimenes(conn: sqlite3.Connection) -> Check:
    fila = conn.execute(
        "SELECT COUNT(*) AS n, SUM(CASE WHEN end_date IS NULL THEN 1 ELSE 0 END) AS abiertos FROM regimes"
    ).fetchone()
    if not fila["n"]:
        return Check("regimenes", PENDIENTE, "linea de tiempo vacia. Corre: regimes build --from 2007-01-01")
    if (fila["abiertos"] or 0) != 1:
        return Check("regimenes", FALLA, f"{fila['abiertos']} episodios abiertos; tiene que haber exactamente uno")
    return Check("regimenes", OK, f"{fila['n']} episodios, uno abierto")


def _corpus(conn: sqlite3.Connection) -> Check:
    fila = conn.execute(
        """SELECT COUNT(*) AS n,
                  SUM(CASE WHEN regime_id IS NULL THEN 1 ELSE 0 END) AS sin_regimen
           FROM events_archive"""
    ).fetchone()
    if not fila["n"]:
        return Check("corpus", PENDIENTE, "archivo vacio. Corre: seed load")
    if fila["sin_regimen"]:
        return Check("corpus", AVISO, f"{fila['n']} eventos, {fila['sin_regimen']} sin regimen. Corre: seed reassign-regimes")
    return Check("corpus", OK, f"{fila['n']} eventos, todos con regimen")


def _outcomes(conn: sqlite3.Connection) -> Check:
    filas = conn.execute(
        "SELECT data_quality, COUNT(*) AS n FROM outcomes GROUP BY data_quality"
    ).fetchall()
    if not filas:
        return Check("outcomes", PENDIENTE, "sin outcomes calculados. Corre: seed outcomes --all")
    conteo = {f["data_quality"]: f["n"] for f in filas}
    total = sum(conteo.values())
    utiles = conteo.get("OK", 0) + conteo.get("NO_BENCHMARK", 0)
    if utiles == 0:
        return Check("outcomes", AVISO, f"{total} filas, ninguna medida: falta cargar precios")
    return Check("outcomes", OK, f"{utiles}/{total} filas medidas · " + ", ".join(f"{k} {v}" for k, v in sorted(conteo.items())))


def _noticias(conn: sqlite3.Connection) -> Check:
    fila = conn.execute("SELECT COUNT(*) AS n, MAX(fetched_at_utc) AS ultima FROM raw_news").fetchone()
    if not fila["n"]:
        return Check("ingesta de noticias", PENDIENTE, "sin conectores todavia (Tarea 7)")

    ultima = datetime.fromisoformat(fila["ultima"].replace("Z", "+00:00"))
    horas = (now() - ultima).total_seconds() / 3600
    if horas > 2:
        return Check("ingesta de noticias", AVISO, f"ultima ingesta hace {horas:.1f} horas")
    return Check("ingesta de noticias", OK, f"{fila['n']} noticias, ultima hace {horas:.1f} horas")


def _calls_huerfanos(conn: sqlite3.Connection) -> Check:
    total = conn.execute("SELECT COUNT(*) AS n FROM calls").fetchone()["n"]
    if not total:
        return Check("calls", PENDIENTE, "sin scoring todavia (Tarea 10)")

    limite = (now() - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    huerfanos = conn.execute(
        """SELECT COUNT(*) AS n FROM calls c LEFT JOIN call_results r USING(call_id)
           WHERE r.call_id IS NULL AND c.evaluate_after < ?""",
        (limite,),
    ).fetchone()["n"]
    if huerfanos:
        return Check("calls", AVISO, f"{huerfanos} vencidos hace mas de 7 dias sin evaluar. Corre: evaluate --due")
    return Check("calls", OK, f"{total} calls, ninguno vencido sin evaluar")


def _integridad(conn: sqlite3.Connection) -> Check:
    problemas = dbmod.integrity_check(conn)
    if problemas:
        return Check("integridad", FALLA, f"{len(problemas)} problemas: {problemas[0]}")
    return Check("integridad", OK, "integrity_check y foreign_key_check limpios")


def _disco(path: Path) -> Check:
    libre_gb = dbmod.free_disk_bytes(path) / 1e9
    tamanio_gb = dbmod.db_size_bytes(path) / 1e9
    if libre_gb < 1:
        return Check("disco", FALLA, f"{libre_gb:.2f} GB libres")
    if tamanio_gb > 5:
        return Check("disco", AVISO, f"la base pesa {tamanio_gb:.1f} GB: hora de archivar (§C.7)")
    return Check("disco", OK, f"base {tamanio_gb * 1000:.1f} MB, {libre_gb:.1f} GB libres")


def _conectividad() -> list[Check]:
    import httpx

    salida: list[Check] = []
    for nombre, url in FUENTES.items():
        try:
            respuesta = httpx.head(url, timeout=10.0, follow_redirects=True)
            estado = OK if respuesta.status_code < 500 else AVISO
            salida.append(Check(f"red: {nombre}", estado, f"HTTP {respuesta.status_code}"))
        except Exception as exc:  # noqa: BLE001
            salida.append(Check(f"red: {nombre}", AVISO, f"{type(exc).__name__}: {str(exc)[:70]}"))
    return salida


def healthcheck(db_path: str | Path | None = None) -> list[Check]:
    """Subconjunto para el cron: solo lo que tiene que estar fresco (§C.6)."""
    interesan = {"schema", "guardas anti-look-ahead", "precios", "ingesta de noticias", "calls", "integridad", "disco"}
    return [c for c in run_all(db_path) if c.nombre in interesan]
