"""CLI del motor (§C.2).

Tarea 1 implementa solo el grupo `db`. El resto de los subcomandos de §C.2 se
agregan con su tarea correspondiente; no hay stubs que finjan funcionar.
"""

from __future__ import annotations

import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import db as dbmod  # noqa: E402

console = Console()
app = typer.Typer(add_completion=False, help="Motor de mapeo noticias -> exposicion de activos")
db_app = typer.Typer(help="Base de datos: init, migrate, status, backup, reset")
app.add_typer(db_app, name="db")


@app.callback()
def main(
    ctx: typer.Context,
    db: str = typer.Option(None, "--db", help="Ruta de la base (default: env DB_PATH o data/news.db)"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    ctx.obj = {"db": db, "verbose": verbose}


def _db_path(ctx: typer.Context) -> str | None:
    return (ctx.obj or {}).get("db")


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


if __name__ == "__main__":
    app()
