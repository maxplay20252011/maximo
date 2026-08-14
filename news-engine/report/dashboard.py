"""Dashboard HTML (§11, §15).

Orden fijo: el scorecard va arriba, nunca escondido. Las secciones que todavia no
se pueden construir aparecen listadas como pendientes, con el numero de tarea. Un
dashboard que muestra seis paneles bonitos y omite que el motor de scoring no
existe es peor que no tener dashboard.

Sin dependencias externas: la pagina es un archivo suelto que abre con doble clic,
sin servidor, sin CDN, sin fuentes remotas.
"""

from __future__ import annotations

import html
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from core.clock import now

BASELINE_BRIER = 0.25

DISCLAIMER = (
    "Material de research generado automaticamente. No constituye asesoramiento financiero."
)

# Secciones de §11 que dependen de tareas no construidas.
PENDIENTES = [
    ("Estado narrativo", "Tarea 9", "§10"),
    ("Top 5 eventos por severidad x (1 - priced_in) x contradiccion narrativa", "Tarea 10", "§11.3"),
    ("Ficha por evento con analogos", "Tarea 5", "§7"),
    ("Mapa de exposiciones por clase de activo", "Tarea 10", "§8.4"),
    ("Calls vencidos esta semana, los errores primero", "Tareas 6 y 10", "§11.8"),
]


# ---------------------------------------------------------------------------
# Datos
# ---------------------------------------------------------------------------


def gather(conn: sqlite3.Connection, db_path: str) -> dict[str, Any]:
    return {
        "generado": now().strftime("%Y-%m-%d %H:%M UTC"),
        "db": db_path,
        "es_demo": "demo" in Path(db_path).name,
        "calibracion": _calibracion(conn),
        "limitaciones": _limitaciones(conn),
        "estado": _estado(conn, db_path),
        "regimen": _regimen(conn),
        "eventos": _eventos(conn),
        "outcomes": _outcomes(conn),
        "movimientos": _movimientos(conn),
        "candidatos": _candidatos(conn),
        "alertas": _alertas(conn),
    }


def _calibracion(conn: sqlite3.Connection) -> dict[str, Any]:
    """§9. Con cero calls evaluados esto dice 'sin datos', que es la verdad."""
    fila = conn.execute(
        """SELECT COUNT(*) AS n,
                  SUM(CASE WHEN r.hit IS NOT NULL THEN 1 ELSE 0 END) AS evaluables,
                  AVG(CAST(r.hit AS REAL)) AS hit_rate,
                  AVG(r.brier_contribution) AS brier
           FROM calls c LEFT JOIN call_results r USING(call_id)"""
    ).fetchone()

    n = fila["n"] or 0
    evaluables = fila["evaluables"] or 0
    # n_efectivo: observaciones solapadas (§9.1). Sin calls todavia es 0; cuando
    # los haya, se divide por el horizonte en dias.
    horizonte_medio = conn.execute(
        "SELECT AVG(CAST(REPLACE(horizon,'d','') AS INTEGER)) AS h FROM calls"
    ).fetchone()["h"]
    n_efectivo = int(evaluables / horizonte_medio) if evaluables and horizonte_medio else 0

    if not evaluables:
        estado = "SIN MEDIR"
    elif n_efectivo < 20:
        estado = "MUESTRA INSUFICIENTE"
    elif fila["brier"] is not None and fila["brier"] >= BASELINE_BRIER:
        estado = "SIN VALOR PREDICTIVO DEMOSTRADO"
    else:
        estado = "EN MEDICION"

    return {
        "n": n,
        "evaluables": evaluables,
        "n_efectivo": n_efectivo,
        "hit_rate": fila["hit_rate"],
        "brier": fila["brier"],
        "estado": estado,
    }


def _limitaciones(conn: sqlite3.Connection) -> list[str]:
    limitaciones = [
        "Universo restringido a ETFs de sector e indices liquidos: no hay single names historicos (§2.1c).",
        "put_call_ratio y breadth_pct_above_200dma sin fuente free: quedan nulos en todo market_state (§7.2).",
    ]
    consenso = conn.execute(
        """SELECT COUNT(*) AS total,
                  SUM(CASE WHEN surprise_direction = 'NO_CONSENSUS' THEN 1 ELSE 0 END) AS sin
           FROM events_archive"""
    ).fetchone()
    if consenso["total"]:
        pct = 100 * (consenso["sin"] or 0) / consenso["total"]
        limitaciones.append(f"Cobertura de consenso: {100 - pct:.0f}% de los eventos ({consenso['sin']} sin consenso, §5.4).")

    faltantes = conn.execute(
        "SELECT COUNT(*) AS n FROM outcomes WHERE data_quality NOT IN ('OK','NO_BENCHMARK')"
    ).fetchone()["n"]
    total_out = conn.execute("SELECT COUNT(*) AS n FROM outcomes").fetchone()["n"]
    if total_out:
        limitaciones.append(f"Outcomes sin medir: {faltantes} de {total_out} filas.")

    limitaciones.append("Ningun resultado esta verificado contra datos de mercado reales.")
    return limitaciones


def _estado(conn: sqlite3.Connection, db_path: str) -> list[dict[str, str]]:
    from core import doctor as doctor_mod

    return [
        {"nombre": c.nombre, "estado": c.estado, "detalle": c.detalle}
        for c in doctor_mod.run_all(db_path)
    ]


def _regimen(conn: sqlite3.Connection) -> dict[str, Any]:
    actual = conn.execute("SELECT * FROM regimes WHERE end_date IS NULL").fetchone()
    episodios = conn.execute(
        "SELECT * FROM regimes ORDER BY start_date DESC LIMIT 12"
    ).fetchall()
    total = conn.execute("SELECT COUNT(*) AS n FROM regimes").fetchone()["n"]
    return {
        "actual": dict(actual) if actual else None,
        "recientes": [dict(row) for row in episodios],
        "total": total,
    }


def _eventos(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    filas = conn.execute(
        """SELECT e.event_id, e.occurred_at_utc, e.event_type, e.severity, e.headline,
                  e.is_seed, e.auto_detected, r.regime_label,
                  (SELECT COUNT(*) FROM outcomes o
                    WHERE o.event_id = e.event_id AND o.data_quality IN ('OK','NO_BENCHMARK')) AS medidos,
                  (SELECT COUNT(*) FROM outcomes o WHERE o.event_id = e.event_id) AS total_outcomes
           FROM events_archive e LEFT JOIN regimes r ON e.regime_id = r.regime_id
           ORDER BY e.occurred_at_utc DESC"""
    ).fetchall()
    return [dict(row) for row in filas]


def _outcomes(conn: sqlite3.Connection) -> dict[str, int]:
    return {
        row["data_quality"]: row["n"]
        for row in conn.execute(
            "SELECT data_quality, COUNT(*) AS n FROM outcomes GROUP BY data_quality ORDER BY n DESC"
        )
    }


def _movimientos(conn: sqlite3.Connection, limite: int = 8) -> list[dict[str, Any]]:
    """Mayores movimientos a 5 dias medidos en el archivo, con su exceso.

    Se muestran los que subieron y los que bajaron. Mostrar solo una punta seria
    contar la mitad de la historia (§15).
    """
    filas = conn.execute(
        """SELECT o.event_id, o.asset, o.benchmark, o.ret_5d, o.excess_5d, e.headline, e.occurred_at_utc
           FROM outcomes o JOIN events_archive e USING(event_id)
           WHERE o.ret_5d IS NOT NULL
           ORDER BY ABS(o.ret_5d) DESC LIMIT ?""",
        (limite,),
    ).fetchall()
    return [dict(row) for row in filas]


def _candidatos(conn: sqlite3.Connection) -> dict[str, Any]:
    resumen = conn.execute(
        """SELECT COUNT(*) AS total, SUM(reviewed) AS revisados,
                  SUM(CASE WHEN promoted_event_id IS NOT NULL THEN 1 ELSE 0 END) AS promovidos
           FROM event_candidates"""
    ).fetchone()
    pendientes = conn.execute(
        "SELECT * FROM event_candidates WHERE reviewed = 0 ORDER BY trigger_date DESC LIMIT 15"
    ).fetchall()
    return {
        "total": resumen["total"] or 0,
        "revisados": resumen["revisados"] or 0,
        "promovidos": resumen["promovidos"] or 0,
        "pendientes": [dict(row) for row in pendientes],
    }


def _alertas(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """§11.6: CREDIT_EVENT o GEOPOLITICAL de severidad 5."""
    filas = conn.execute(
        """SELECT event_id, occurred_at_utc, event_type, headline FROM events_archive
           WHERE severity = 5 AND event_type IN ('CREDIT_EVENT','GEOPOLITICAL')
           ORDER BY occurred_at_utc DESC"""
    ).fetchall()
    return [dict(row) for row in filas]


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


def _e(valor: Any) -> str:
    return html.escape(str(valor if valor is not None else "-"))


def _pct(valor: float | None, decimales: int = 1) -> str:
    return "-" if valor is None else f"{valor * 100:.{decimales}f}%"


def _fecha(marca: str) -> str:
    return marca[:10] if marca else "-"


CSS = """
:root{--bg:#faf9f7;--fg:#1a1a1a;--muted:#6b6b6b;--line:#e2e0dc;--card:#fff;
--ok:#1a7f4b;--warn:#9a6700;--fail:#b42318;--pend:#0b5cad;--accent:#1a1a1a}
@media(prefers-color-scheme:dark){:root{--bg:#141413;--fg:#eeece7;--muted:#9b9791;
--line:#2c2b28;--card:#1b1a18;--ok:#4ec38a;--warn:#e0b341;--fail:#f0736a;--pend:#6bb0f5;--accent:#eeece7}}
*{box-sizing:border-box}
body{margin:0;padding:0;background:var(--bg);color:var(--fg);
font:15px/1.55 ui-sans-serif,-apple-system,"Segoe UI",system-ui,sans-serif}
.wrap{max-width:1080px;margin:0 auto;padding:32px 20px 80px}
h1{font-size:26px;margin:0 0 4px;letter-spacing:-.02em}
h2{font-size:17px;margin:40px 0 12px;letter-spacing:-.01em;
border-bottom:1px solid var(--line);padding-bottom:8px}
h3{font-size:14px;margin:20px 0 8px;color:var(--muted);font-weight:600;
text-transform:uppercase;letter-spacing:.06em}
p{margin:8px 0}
.sub{color:var(--muted);font-size:13px}
.banner{border:1px solid var(--line);border-left:3px solid var(--accent);
background:var(--card);padding:16px 18px;border-radius:6px;margin:20px 0}
.banner.demo{border-left-color:var(--warn)}
.banner strong{display:block;margin-bottom:6px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin:16px 0}
.tile{background:var(--card);border:1px solid var(--line);border-radius:6px;padding:14px 16px}
.tile .k{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}
.tile .v{font-size:22px;font-weight:600;margin-top:4px;font-variant-numeric:tabular-nums}
.tile .n{font-size:12px;color:var(--muted);margin-top:2px}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
table{width:100%;border-collapse:collapse;font-size:13.5px;min-width:520px}
th{text-align:left;font-weight:600;color:var(--muted);font-size:11px;
text-transform:uppercase;letter-spacing:.06em;padding:8px 10px;border-bottom:1px solid var(--line)}
td{padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}
tr:last-child td{border-bottom:none}
td.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.tag{display:inline-block;font-size:11px;padding:1px 7px;border-radius:20px;
border:1px solid var(--line);color:var(--muted);white-space:nowrap}
.ok{color:var(--ok)}.warn{color:var(--warn)}.fail{color:var(--fail)}.pend{color:var(--pend)}
.pos{color:var(--ok)}.neg{color:var(--fail)}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:12.5px}
.empty{color:var(--muted);font-style:italic;padding:14px 0}
ul{margin:8px 0;padding-left:20px}li{margin:4px 0}
footer{margin-top:56px;padding-top:16px;border-top:1px solid var(--line);
color:var(--muted);font-size:12px}
"""

_CLASE = {"OK": "ok", "AVISO": "warn", "FALLA": "fail", "PENDIENTE": "pend"}


def render(datos: dict[str, Any]) -> str:
    partes: list[str] = []
    a = partes.append

    a(f"<title>Motor de noticias · estado</title><style>{CSS}</style>")
    a('<div class="wrap">')
    a("<h1>Motor de mapeo noticias &rarr; exposicion de activos</h1>")
    a(f'<p class="sub">Generado {_e(datos["generado"])} · base <span class="mono">{_e(datos["db"])}</span></p>')

    if datos["es_demo"]:
        a('<div class="banner demo"><strong>DATOS SINTETICOS</strong>'
          "Esta base se genero con un paseo aleatorio de semilla fija. Los precios, los retornos y "
          "los regimenes no corresponden a ningun mercado. Sirve para ver que las piezas encajan; "
          "cualquier numero leido como informacion de mercado esta mal leido.</div>")

    # --- 1. Header de calibracion (§11) ------------------------------------
    cal = datos["calibracion"]
    hit_txt = _pct(cal["hit_rate"]) if cal["hit_rate"] is not None else "sin datos"
    brier_txt = f"{cal['brier']:.3f}" if cal["brier"] is not None else "sin datos"
    a('<div class="banner"><strong>' + _e(DISCLAIMER) + "</strong>")
    a(f'<span class="mono">Hit rate: {hit_txt} '
      f'(n={cal["n"]}, n_efectivo={cal["n_efectivo"]}) · '
      f'Brier: {brier_txt} (baseline {BASELINE_BRIER}) · '
      f'Calibracion: {_e(cal["estado"])}</span>')
    a("<h3>Limitaciones conocidas</h3><ul>")
    for limitacion in datos["limitaciones"]:
        a(f"<li>{_e(limitacion)}</li>")
    a("</ul></div>")

    # --- 2. Estado del sistema ---------------------------------------------
    a("<h2>Estado del sistema</h2>")
    a('<div class="scroll"><table><thead><tr><th>Chequeo</th><th>Estado</th><th>Detalle</th></tr></thead><tbody>')
    for check in datos["estado"]:
        clase = _CLASE.get(check["estado"], "")
        a(f'<tr><td>{_e(check["nombre"])}</td>'
          f'<td><span class="{clase}">{_e(check["estado"])}</span></td>'
          f'<td class="sub">{_e(check["detalle"])}</td></tr>')
    a("</tbody></table></div>")

    # --- 3. Regimen ---------------------------------------------------------
    reg = datos["regimen"]
    a("<h2>Regimen de mercado</h2>")
    if reg["actual"]:
        actual = reg["actual"]
        a('<div class="grid">')
        for clave, etiqueta in (
            ("rate_regime", "Tasas"), ("vol_regime", "Volatilidad"),
            ("inflation_regime", "Inflacion"), ("usd_trend", "Dolar"), ("credit_regime", "Credito"),
        ):
            a(f'<div class="tile"><div class="k">{etiqueta}</div>'
              f'<div class="v" style="font-size:17px">{_e(actual[clave])}</div></div>')
        a("</div>")
        a(f'<p class="sub">Episodio vigente desde {_e(actual["start_date"])} · '
          f'{reg["total"]} episodios en la linea de tiempo</p>')
        a('<div class="scroll"><table><thead><tr><th>Desde</th><th>Hasta</th><th>Etiqueta</th>'
          "<th>VIX pctil</th></tr></thead><tbody>")
        for row in reg["recientes"]:
            pctil = "-" if row["vix_pctile"] is None else f'{row["vix_pctile"]:.2f}'
            a(f'<tr><td class="mono">{_e(row["start_date"])}</td>'
              f'<td class="mono">{_e(row["end_date"] or "abierto")}</td>'
              f'<td class="mono">{_e(row["regime_label"])}</td>'
              f'<td class="num">{pctil}</td></tr>')
        a("</tbody></table></div>")
    else:
        a('<p class="empty">Linea de tiempo vacia. Corre: '
          '<span class="mono">python run.py regimes build --from 2007-01-01</span></p>')

    # --- 4. Alertas ---------------------------------------------------------
    a("<h2>Alertas</h2>")
    alertas = datos["alertas"]
    if alertas:
        a(f'<p class="sub">{len(alertas)} eventos de severidad 5 en credito o geopolitica (§11.6)</p>')
        a('<div class="scroll"><table><thead><tr><th>Fecha</th><th>Tipo</th><th>Titular</th></tr></thead><tbody>')
        for ev in alertas:
            a(f'<tr><td class="mono">{_e(_fecha(ev["occurred_at_utc"]))}</td>'
              f'<td><span class="tag">{_e(ev["event_type"])}</span></td>'
              f'<td>{_e(ev["headline"])}</td></tr>')
        a("</tbody></table></div>")
    else:
        a('<p class="empty">Sin alertas.</p>')

    # --- 5. Archivo de eventos ---------------------------------------------
    eventos = datos["eventos"]
    a("<h2>Archivo de eventos</h2>")
    if eventos:
        medidos = sum(1 for e in eventos if e["medidos"])
        a(f'<p class="sub">{len(eventos)} eventos · {medidos} con outcomes medidos</p>')
        a('<div class="scroll"><table><thead><tr><th>Fecha</th><th>Tipo</th><th>Sev</th>'
          "<th>Titular</th><th>Regimen</th><th>Outcomes</th></tr></thead><tbody>")
        for ev in eventos:
            marca = "semilla" if ev["is_seed"] else ("auto" if ev["auto_detected"] else "-")
            cobertura = (
                f'{ev["medidos"]}/{ev["total_outcomes"]}' if ev["total_outcomes"] else "sin calcular"
            )
            clase = "ok" if ev["medidos"] else "warn"
            a(f'<tr><td class="mono">{_e(_fecha(ev["occurred_at_utc"]))}</td>'
              f'<td><span class="tag">{_e(ev["event_type"])}</span></td>'
              f'<td class="num">{_e(ev["severity"])}</td>'
              f'<td>{_e(ev["headline"])}<br><span class="sub">{marca}</span></td>'
              f'<td class="mono sub">{_e(ev["regime_label"] or "sin regimen")}</td>'
              f'<td class="num {clase}">{cobertura}</td></tr>')
        a("</tbody></table></div>")
    else:
        a('<p class="empty">Archivo vacio. Corre: <span class="mono">python run.py seed load</span></p>')

    # --- 6. Outcomes --------------------------------------------------------
    a("<h2>Outcomes medidos</h2>")
    outcomes = datos["outcomes"]
    if outcomes:
        a('<div class="grid">')
        for calidad, n in outcomes.items():
            a(f'<div class="tile"><div class="k">{_e(calidad)}</div><div class="v">{n}</div></div>')
        a("</div>")
    movimientos = datos["movimientos"]
    if movimientos:
        a("<h3>Mayores movimientos a 5 dias, en las dos direcciones</h3>")
        a('<div class="scroll"><table><thead><tr><th>Fecha</th><th>Activo</th><th>Retorno 5d</th>'
          "<th>Exceso 5d</th><th>Evento</th></tr></thead><tbody>")
        for mov in movimientos:
            clase = "pos" if mov["ret_5d"] > 0 else "neg"
            exceso = _pct(mov["excess_5d"]) if mov["excess_5d"] is not None else "sin benchmark"
            a(f'<tr><td class="mono">{_e(_fecha(mov["occurred_at_utc"]))}</td>'
              f'<td class="mono">{_e(mov["asset"])}</td>'
              f'<td class="num {clase}">{_pct(mov["ret_5d"])}</td>'
              f'<td class="num sub">{_e(exceso)}</td>'
              f'<td class="sub">{_e(mov["headline"])}</td></tr>')
        a("</tbody></table></div>")
    elif not outcomes:
        a('<p class="empty">Sin outcomes calculados. Corre: '
          '<span class="mono">python run.py seed outcomes --all</span></p>')
    else:
        a('<p class="empty">Ninguna fila quedo medida: faltan precios cargados.</p>')

    # --- 7. Candidatos ------------------------------------------------------
    cand = datos["candidatos"]
    a("<h2>Candidatos de autodeteccion</h2>")
    if cand["total"]:
        a(f'<p class="sub">{cand["total"]} fechas dispararon un umbral · {cand["revisados"]} revisadas · '
          f'{cand["promovidos"]} promovidas a evento. Un candidato no se archiva hasta tener causa: '
          "una noticia atribuida o una revision humana (§6.2).</p>")
        a('<div class="scroll"><table><thead><tr><th>Fecha</th><th>Umbrales</th><th>Metricas</th></tr></thead><tbody>')
        for row in cand["pendientes"]:
            disparos = ", ".join(json.loads(row["triggers_json"]))
            metricas = ", ".join(f"{k}={v}" for k, v in json.loads(row["metrics_json"]).items())
            a(f'<tr><td class="mono">{_e(row["trigger_date"])}</td>'
              f'<td>{_e(disparos)}</td><td class="mono sub">{_e(metricas)}</td></tr>')
        a("</tbody></table></div>")
    else:
        a('<p class="empty">Sin candidatos. Corre: '
          '<span class="mono">python run.py seed autodetect --from 2010-01-01</span></p>')

    # --- 8. Lo que falta ----------------------------------------------------
    a("<h2>Secciones de §11 todavia no construidas</h2>")
    a('<div class="scroll"><table><thead><tr><th>Seccion</th><th>Depende de</th><th>Spec</th></tr></thead><tbody>')
    for nombre, tarea, spec in PENDIENTES:
        a(f'<tr><td>{_e(nombre)}</td><td class="pend">{_e(tarea)}</td>'
          f'<td class="mono sub">{_e(spec)}</td></tr>')
    a("</tbody></table></div>")

    a("<footer>")
    a(f"<p>{_e(DISCLAIMER)} El sistema no emite recomendaciones: mapea exposiciones y mide "
      "si sus propias lecturas valen algo.</p>")
    a("<p>Estado del proyecto: 4 de 13 tareas. Ningun resultado verificado contra datos de mercado reales.</p>")
    a("</footer></div>")
    return "\n".join(partes)


def write(conn: sqlite3.Connection, db_path: str, salida: str = "dist") -> Path:
    destino = Path(salida)
    destino.mkdir(parents=True, exist_ok=True)
    archivo = destino / "index.html"
    datos = gather(conn, db_path)
    archivo.write_text(
        "<!doctype html><html lang=\"es\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        + render(datos)
        + "</body></html>",
        encoding="utf-8",
    )
    return archivo
