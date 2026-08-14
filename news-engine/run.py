"""CLI del motor (§C.2).

Tarea 1 implementa solo el grupo `db`. El resto de los subcomandos de §C.2 se
agregan con su tarea correspondiente; no hay stubs que finjan funcionar.
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import db as dbmod  # noqa: E402

console = Console()
app = typer.Typer(add_completion=False, help="Motor de mapeo noticias -> exposicion de activos")
db_app = typer.Typer(help="Base de datos: init, migrate, status, backup, reset")
pit_app = typer.Typer(help="Point-in-time: carga de precios y macro, guardas anti-look-ahead")
regimes_app = typer.Typer(help="Regimenes de mercado (§4)")
seed_app = typer.Typer(help="Corpus semilla y outcomes (§6)")
app.add_typer(db_app, name="db")
app.add_typer(pit_app, name="pit")
app.add_typer(regimes_app, name="regimes")
app.add_typer(seed_app, name="seed")


@app.callback()
def main(
    ctx: typer.Context,
    db: str = typer.Option(None, "--db", help="Ruta de la base (default: env DB_PATH o data/news.db)"),
    config: str = typer.Option("config", "--config", help="Directorio de configuracion"),
    as_of_ts: str = typer.Option(None, "--as-of", help="Congela el reloj (ISO-8601 UTC), para debugging historico"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    ctx.obj = {"db": db, "config": config, "as_of": as_of_ts, "verbose": verbose}
    if as_of_ts:
        from datetime import timezone

        from core.clock import FrozenClock, set_clock

        moment = datetime.fromisoformat(as_of_ts.replace("Z", "+00:00")).astimezone(timezone.utc)
        set_clock(FrozenClock(moment))
        console.print(f"[yellow]reloj congelado en {as_of_ts}[/yellow]")


def _db_path(ctx: typer.Context) -> str | None:
    return (ctx.obj or {}).get("db")


def _universe_path(ctx: typer.Context) -> str:
    return str(Path((ctx.obj or {}).get("config", "config")) / "universe.yaml")


@db_app.command("init")
def db_init(ctx: typer.Context) -> None:
    """Crea la base y aplica todas las migraciones."""
    path = dbmod.resolve_db_path(_db_path(ctx))
    existed = path.exists()
    conn, applied = dbmod.init_db(path)
    try:
        if applied:
            for migration in applied:
                console.print(f"[green]aplicada[/green] {migration.label}")
        else:
            console.print("[yellow]sin migraciones pendientes[/yellow]")
        console.print(f"base {'existente' if existed else 'creada'}: {path}")
        console.print(f"version de schema: {dbmod.schema_version(conn)}")
    finally:
        conn.close()


@db_app.command("migrate")
def db_migrate(ctx: typer.Context) -> None:
    """Aplica migraciones pendientes."""
    conn = dbmod.connect(_db_path(ctx))
    try:
        applied = dbmod.migrate(conn)
        if not applied:
            console.print("[yellow]sin migraciones pendientes[/yellow]")
        for migration in applied:
            console.print(f"[green]aplicada[/green] {migration.label}")
        console.print(f"version de schema: {dbmod.schema_version(conn)}")
    finally:
        conn.close()


@db_app.command("status")
def db_status(ctx: typer.Context, deep: bool = typer.Option(False, "--deep", help="Corre integrity_check")) -> None:
    """Version de schema + conteo por tabla."""
    path = dbmod.resolve_db_path(_db_path(ctx))
    if not path.exists():
        console.print(f"[red]no existe la base:[/red] {path}  (corre: python run.py db init)")
        raise typer.Exit(code=1)

    conn = dbmod.connect(path)
    try:
        version = dbmod.schema_version(conn)
        pending = dbmod.pending_migrations(conn)
        counts = dbmod.table_counts(conn)

        console.print(f"base: {path}  ({dbmod.db_size_bytes(path) / 1024:.1f} KB)")
        console.print(f"version de schema: {version}" + (f"  [red]pendientes: {len(pending)}[/red]" if pending else ""))

        table = Table("tabla", "filas")
        for name in dbmod.DOMAIN_TABLES:
            table.add_row(name, str(counts.get(name, "[red]FALTA[/red]")))
        console.print(table)

        faltantes = [t for t in dbmod.DOMAIN_TABLES if t not in counts]
        if faltantes:
            console.print(f"[red]tablas faltantes: {', '.join(faltantes)}[/red]")
            raise typer.Exit(code=1)

        if deep:
            problems = dbmod.integrity_check(conn)
            if problems:
                for problem in problems:
                    console.print(f"[red]{problem}[/red]")
                raise typer.Exit(code=1)
            console.print("[green]integrity_check: ok[/green]")
    finally:
        conn.close()


@db_app.command("backup")
def db_backup(ctx: typer.Context, dest: str = typer.Option("data/backups", "--dest")) -> None:
    """Copia a data/backups/news_YYYYMMDD.db"""
    target = dbmod.backup(_db_path(ctx), dest)
    console.print(f"backup: {target} ({target.stat().st_size / 1024:.1f} KB)")


@db_app.command("reset")
def db_reset(ctx: typer.Context, confirm: bool = typer.Option(False, "--confirm")) -> None:
    """DESTRUCTIVO: borra y recrea la base."""
    if not confirm:
        console.print("[red]falta --confirm[/red]: el comando borra la base entera")
        raise typer.Exit(code=1)
    path = dbmod.reset(_db_path(ctx), confirm=True)
    console.print(f"base recreada vacia: {path}")


# ---------------------------------------------------------------------------
# pit (§2)
# ---------------------------------------------------------------------------


@pit_app.command("verify")
def pit_verify() -> None:
    """Corre las 4 guardas anti-look-ahead de §2.2. Exit 1 si falla alguna."""
    from pit.verify import run_all_guards

    results = run_all_guards()
    for result in results:
        mark = "[green]PASA[/green]" if result.passed else "[red]FALLA[/red]"
        console.print(f"{mark}  {result.name}: {result.detail}")

    fallidas = [r for r in results if not r.passed]
    if fallidas:
        console.print(f"\n[red]{len(fallidas)} de {len(results)} guardas fallan. Se frena todo (§0).[/red]")
        raise typer.Exit(code=1)
    console.print(f"\n[green]{len(results)}/{len(results)} guardas pasan.[/green]")


@pit_app.command("load-prices")
def pit_load_prices(
    ctx: typer.Context,
    universe: str = typer.Option(None, "--universe"),
    from_date: str = typer.Option("2007-01-01", "--from"),
    to_date: str = typer.Option("today", "--to"),
    source: str = typer.Option("stooq", "--source"),
    incremental: bool = typer.Option(False, "--incremental", help="Desde el ultimo cierre cargado"),
    only: str = typer.Option(None, "--only", help="Lista de activos separados por coma"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Muestra que pediria, sin red ni escritura"),
) -> None:
    """Carga cierres EOD crudos (§2.1a: sin ajustar, el ajuste se calcula al leer)."""
    from pit import market_state as ms_mod
    from pit import prices as price_mod

    config = ms_mod.load_universe(universe or _universe_path(ctx))
    symbols: dict[str, str] = {a: spec["simbolo"] for a, spec in config.get("assets", {}).items()}
    for entry in config.get("market_state", {}).values():
        if entry.get("kind") == "price":
            symbols[entry["asset"]] = entry["simbolo"]
    if only:
        wanted = {a.strip().upper() for a in only.split(",")}
        symbols = {a: s for a, s in symbols.items() if a.upper() in wanted}

    conn = dbmod.connect(_db_path(ctx))
    try:
        start = date.fromisoformat(from_date)
        end = date.today() if to_date == "today" else date.fromisoformat(to_date)
        if incremental:
            last = price_mod.last_price_date(conn)
            if last:
                start = last - timedelta(days=5)

        if dry_run:
            console.print(f"{len(symbols)} activos, {start} -> {end}, fuente {source}")
            for asset, symbol in sorted(symbols.items()):
                console.print(f"  {asset:6s} <- {symbol}")
            return

        report = price_mod.load_prices(conn, symbols, start, end, source=source)
        console.print(f"cargados {report.total_rows} cierres de {len(report.written)} activos")
        if report.errors:
            console.print(f"[red]sin datos ({len(report.errors)}):[/red]")
            for asset, motivo in sorted(report.errors.items()):
                console.print(f"  {asset:6s} {motivo}")
            raise typer.Exit(code=1)
    finally:
        conn.close()


@pit_app.command("load-macro")
def pit_load_macro(
    ctx: typer.Context,
    series: str = typer.Option(None, "--series", help="Lista separada por coma; default: config/universe.yaml"),
    from_date: str = typer.Option("2005-01-01", "--from"),
    to_date: str = typer.Option("today", "--to"),
    vintages: bool = typer.Option(False, "--vintages", help="Obligatorio: sin vintages no hay analisis historico"),
) -> None:
    """Carga series macro con vintages de ALFRED (§2.1b)."""
    from pit import macro as macro_mod
    from pit import market_state as ms_mod

    if not vintages:
        console.print("[red]falta --vintages[/red]: la serie revisada de hoy no sirve para historico (§2.1b)")
        raise typer.Exit(code=1)

    wanted = (
        [s.strip() for s in series.split(",")]
        if series
        else ms_mod.load_universe(_universe_path(ctx)).get("macro_series", list(macro_mod.CORE_SERIES))
    )

    conn = dbmod.connect(_db_path(ctx))
    try:
        start = date.fromisoformat(from_date)
        end = date.today() if to_date == "today" else date.fromisoformat(to_date)
        report = macro_mod.load_macro(conn, wanted, start, end, vintages=True)
        for series_id, count in sorted(report.written.items()):
            console.print(f"  {series_id:14s} {count} filas")
        for series_id, motivo in sorted(report.errors.items()):
            console.print(f"  {series_id:14s} [red]{motivo}[/red]")
        if report.errors:
            raise typer.Exit(code=1)
    finally:
        conn.close()


@pit_app.command("check")
def pit_check(
    ctx: typer.Context,
    check_date: str = typer.Option(..., "--date", help="Fecha o timestamp del corte"),
    series: str = typer.Option(None, "--series", help="Si se pasa, muestra la serie macro en vez del market_state"),
    vintage: bool = typer.Option(False, "--vintage", help="Muestra el valor tal como se publico, no el revisado"),
) -> None:
    """Sin --series: market_state de esa fecha. Con --series: valor macro."""
    from datetime import timezone

    from pit import macro as macro_mod
    from pit import market_state as ms_mod
    from pit.guards import as_of

    moment = (
        datetime.fromisoformat(check_date.replace("Z", "+00:00")).astimezone(timezone.utc)
        if len(check_date) > 10
        else datetime.combine(date.fromisoformat(check_date), datetime.min.time(), tzinfo=timezone.utc)
    )

    conn = dbmod.connect(_db_path(ctx))
    try:
        if series:
            historial = macro_mod.get_revision_history(conn, series, moment.date())
            if not historial:
                console.print(f"[yellow]sin observaciones de {series} para {moment.date()}[/yellow]")
                return
            if vintage:
                with as_of(moment):
                    valor = macro_mod.get_macro_as_known_at(conn, series, moment.date(), moment)
                console.print(f"{series} {moment.date()} tal como se publico: {valor}")
            table = Table("vintage", "valor")
            for obs in historial:
                table.add_row(obs.vintage_date.isoformat(), str(obs.value))
            console.print(table)
            console.print(f"revisiones: {len(historial) - 1}")
            return

        config = ms_mod.load_universe(_universe_path(ctx))
        with as_of(moment):
            state = ms_mod.build_market_state(conn, moment, config)
        meta = state.pop("_meta")
        table = Table("campo", "valor", "fecha del dato")
        for field, value in state.items():
            table.add_row(field, "-" if value is None else str(value), meta["field_dates"].get(field, "-"))
        console.print(table)
        console.print(f"corte: {meta['cutoff_date']} · cobertura: {meta['coverage']:.0%}")
        if meta["missing"]:
            console.print(f"[yellow]faltantes: {', '.join(meta['missing'])}[/yellow]")
    finally:
        conn.close()


@pit_app.command("coverage")
def pit_coverage(ctx: typer.Context) -> None:
    """Que hay cargado: activos, rango de fechas, series macro y vintages."""
    from pit import macro as macro_mod
    from pit import prices as price_mod

    conn = dbmod.connect(_db_path(ctx))
    try:
        precios = price_mod.price_coverage(conn)
        table = Table("activo", "cierres", "desde", "hasta", "fuente")
        for row in precios:
            table.add_row(row["asset"], str(row["n"]), row["desde"], row["hasta"], row["source"])
        console.print(table if precios else "[yellow]sin precios cargados[/yellow]")

        macro = macro_mod.macro_coverage(conn)
        table = Table("serie", "filas", "obs", "vintages", "desde", "hasta")
        for row in macro:
            table.add_row(
                row["series_id"], str(row["filas"]), str(row["observaciones"]),
                str(row["vintages"]), row["desde"], row["hasta"],
            )
        console.print(table if macro else "[yellow]sin series macro cargadas[/yellow]")
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# regimes (§4)
# ---------------------------------------------------------------------------


def _thresholds_path(ctx: typer.Context) -> str:
    return str(Path((ctx.obj or {}).get("config", "config")) / "thresholds.yaml")


@regimes_app.command("build")
def regimes_build(
    ctx: typer.Context,
    from_date: str = typer.Option("2007-01-01", "--from"),
    to_date: str = typer.Option("today", "--to"),
    incremental: bool = typer.Option(False, "--incremental", help="Desde el ultimo episodio abierto"),
    rebuild: bool = typer.Option(False, "--rebuild", help="Borra la linea de tiempo y la rehace"),
) -> None:
    """Arma la linea de tiempo de regimenes, paso semanal (§4)."""
    from classify import regime as regime_mod

    thresholds = regime_mod.load_thresholds(_thresholds_path(ctx))
    conn = dbmod.connect(_db_path(ctx))
    try:
        if rebuild:
            borrados = regime_mod.clear_regimes(conn)
            console.print(f"[yellow]borrados {borrados} episodios[/yellow]")

        start = date.fromisoformat(from_date)
        if incremental:
            abierto = regime_mod.current_regime(conn)
            if abierto:
                # Desde el inicio del episodio abierto: la ventana de confirmacion
                # no se persiste y hay que reconstruirla recorriendo de nuevo.
                start = date.fromisoformat(abierto["start_date"])
        end = date.today() if to_date == "today" else date.fromisoformat(to_date)

        report = regime_mod.build_regimes(conn, start, end, thresholds)
        console.print(
            f"{report.fechas_evaluadas} fechas evaluadas · "
            f"{report.episodios_creados} episodios · "
            f"{report.fechas_sin_clasificar} sin clasificar · "
            f"{report.cambios_descartados} cambios descartados por duracion minima"
        )
        if report.faltantes_por_dimension:
            for dim, count in sorted(report.faltantes_por_dimension.items(), key=lambda x: -x[1]):
                console.print(f"  [yellow]falta {dim}: {count} fechas[/yellow]")
        if report.episodios_creados == 0:
            console.print("[red]no se creo ningun episodio: revisa que haya precios y macro cargados[/red]")
            raise typer.Exit(code=1)
    finally:
        conn.close()


@regimes_app.command("timeline")
def regimes_timeline(ctx: typer.Context) -> None:
    """Imprime la linea de tiempo de regimenes."""
    from classify import regime as regime_mod

    conn = dbmod.connect(_db_path(ctx))
    try:
        episodios = regime_mod.timeline(conn)
        if not episodios:
            console.print("[yellow]sin regimenes construidos[/yellow]")
            return
        table = Table("desde", "hasta", "tasas", "vol", "inflacion", "usd", "credito", "vix pct")
        for row in episodios:
            table.add_row(
                row["start_date"], row["end_date"] or "abierto",
                row["rate_regime"], row["vol_regime"], row["inflation_regime"],
                row["usd_trend"], row["credit_regime"],
                "-" if row["vix_pctile"] is None else f"{row['vix_pctile']:.2f}",
            )
        console.print(table)
        console.print(f"{len(episodios)} episodios")
    finally:
        conn.close()


@regimes_app.command("current")
def regimes_current(ctx: typer.Context) -> None:
    """Regimen vigente."""
    from classify import regime as regime_mod

    conn = dbmod.connect(_db_path(ctx))
    try:
        row = regime_mod.current_regime(conn)
        if row is None:
            console.print("[yellow]sin regimen abierto[/yellow]")
            raise typer.Exit(code=1)
        console.print(f"{row['regime_label']}  (desde {row['start_date']})")
    finally:
        conn.close()


@regimes_app.command("check")
def regimes_check(
    ctx: typer.Context,
    check_date: str = typer.Option(..., "--date"),
) -> None:
    """Clasifica una fecha suelta y muestra los insumos que uso."""
    from classify import regime as regime_mod

    thresholds = regime_mod.load_thresholds(_thresholds_path(ctx))
    conn = dbmod.connect(_db_path(ctx))
    try:
        snapshot = regime_mod.classify_at(conn, date.fromisoformat(check_date), thresholds)
        console.print(f"{check_date}: {regime_mod.snapshot_to_text(snapshot)}")
        table = Table("insumo", "valor")
        for nombre, valor in snapshot.inputs.items():
            table.add_row(nombre, "-" if valor is None else str(valor))
        if snapshot.vix_pctile is not None:
            table.add_row("vix_pctile", f"{snapshot.vix_pctile:.3f}")
        if snapshot.hy_oas_pctile is not None:
            table.add_row("hy_oas_pctile", f"{snapshot.hy_oas_pctile:.3f}")
        console.print(table)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# seed (§6)
# ---------------------------------------------------------------------------


@seed_app.command("load")
def seed_load(
    ctx: typer.Context,
    file: str = typer.Option(None, "--file"),
) -> None:
    """Carga el corpus semilla con market_state y regimen de cada episodio."""
    from history import seed as seed_mod
    from pit import market_state as ms_mod

    universe = ms_mod.load_universe(_universe_path(ctx))
    conn = dbmod.connect(_db_path(ctx))
    try:
        resumen = seed_mod.load_corpus(conn, universe, path=file or seed_mod.DEFAULT_SEED_PATH)
        console.print(
            f"{resumen['cargados']} episodios ({resumen['desde']} a {resumen['hasta']}) · "
            f"cobertura media de market_state: {resumen['cobertura_market_state_promedio']:.0%}"
        )
        if resumen["sin_regimen"]:
            console.print(
                f"[yellow]{len(resumen['sin_regimen'])} sin regimen asignado[/yellow] "
                "(corre regimes build y despues seed reassign-regimes)"
            )
    finally:
        conn.close()


@seed_app.command("reassign-regimes")
def seed_reassign(ctx: typer.Context) -> None:
    """Reasigna el regimen de los eventos ya cargados."""
    from history import seed as seed_mod

    conn = dbmod.connect(_db_path(ctx))
    try:
        console.print(f"{seed_mod.reassign_regimes(conn)} eventos revisados")
    finally:
        conn.close()


@seed_app.command("outcomes")
def seed_outcomes(
    ctx: typer.Context,
    all_events: bool = typer.Option(False, "--all"),
    event_id: str = typer.Option(None, "--event-id"),
) -> None:
    """Calcula outcomes a 1, 5 y 20 sesiones contra el benchmark de cada activo."""
    from history import outcomes as out_mod
    from pit import market_state as ms_mod

    if not all_events and not event_id:
        console.print("[red]elegi --all o --event-id[/red]")
        raise typer.Exit(code=1)

    universe = ms_mod.load_universe(_universe_path(ctx))
    thresholds = _full_thresholds(ctx)
    conn = dbmod.connect(_db_path(ctx))
    try:
        resumen = out_mod.compute_all(
            conn, universe, thresholds, event_ids=[event_id] if event_id else None
        )
        total = sum(sum(c.values()) for c in resumen.values())
        console.print(f"{len(resumen)} eventos · {total} filas de outcome")
        table = Table("calidad", "filas")
        for row in out_mod.quality_summary(conn):
            table.add_row(row["data_quality"], str(row["n"]))
        console.print(table)
    finally:
        conn.close()


def _full_thresholds(ctx: typer.Context) -> dict:
    from classify import regime as regime_mod

    return regime_mod.load_thresholds(_thresholds_path(ctx))


@seed_app.command("autodetect")
def seed_autodetect(
    ctx: typer.Context,
    from_date: str = typer.Option("2010-01-01", "--from"),
    to_date: str = typer.Option("today", "--to"),
) -> None:
    """Detecta fechas con movimientos extremos y las guarda como candidatos (§6.2)."""
    from history import archive as archive_mod

    thresholds = _full_thresholds(ctx)
    conn = dbmod.connect(_db_path(ctx))
    try:
        start = date.fromisoformat(from_date)
        end = date.today() if to_date == "today" else date.fromisoformat(to_date)
        candidatos = archive_mod.detect(conn, start, end, thresholds)
        nuevos = archive_mod.persist_candidates(conn, candidatos)
        console.print(f"{len(candidatos)} fechas dispararon un umbral · {nuevos} candidatos nuevos")
        if candidatos:
            console.print("[yellow]ninguno se archiva como evento hasta que tenga causa: "
                          "una noticia atribuida o una revision humana (seed review)[/yellow]")
    finally:
        conn.close()


@seed_app.command("review")
def seed_review(
    ctx: typer.Context,
    limit: int = typer.Option(20, "--limit"),
) -> None:
    """Lista candidatos pendientes de revision humana."""
    from history import archive as archive_mod

    conn = dbmod.connect(_db_path(ctx))
    try:
        pendientes = archive_mod.pending(conn, limit)
        if not pendientes:
            console.print("[green]sin candidatos pendientes[/green]")
            return
        table = Table("fecha", "umbrales", "metricas")
        for row in pendientes:
            table.add_row(row["trigger_date"], row["triggers_json"], row["metrics_json"])
        console.print(table)
        stats = archive_mod.candidate_stats(conn)
        console.print(f"total {stats['total']} · revisados {stats['revisados'] or 0} · promovidos {stats['promovidos'] or 0}")
    finally:
        conn.close()


@seed_app.command("stats")
def seed_stats(ctx: typer.Context) -> None:
    """Cuantos episodios hay, de que tipo, en que regimen y cuales sin outcomes."""
    from history import seed as seed_mod

    conn = dbmod.connect(_db_path(ctx))
    try:
        datos = seed_mod.stats(conn)
        table = Table("tipo", "n", "severidad media")
        for row in datos["por_tipo"]:
            table.add_row(row["event_type"], str(row["n"]), str(row["sev"]))
        console.print(table)

        table = Table("regimen", "n")
        for row in datos["por_regimen"]:
            table.add_row(row["regimen"], str(row["n"]))
        console.print(table)

        faltantes = datos["sin_outcomes"]
        if faltantes:
            console.print(f"[yellow]{len(faltantes)} eventos sin outcomes calculados[/yellow]")
    finally:
        conn.close()


if __name__ == "__main__":
    app()
