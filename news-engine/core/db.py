"""Conexion a SQLite y runner de migraciones (Tarea 1).

Sin ORM. SQL a mano. Todo lo que toca la base pasa por aca.

Las migraciones son archivos `NNN_nombre.sql` en `core/migrations/`, aplicados en
orden de version, uno por transaccion, con checksum registrado. Si un archivo ya
aplicado cambia, `migrate()` falla en vez de aplicar el cambio a medias.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from core.clock import format_utc, now

DEFAULT_DB_PATH = Path("data/news.db")
MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
MIGRATION_FILENAME_RE = re.compile(r"^(\d{3})_([a-z0-9_]+)\.sql$")

# Directiva opcional en las primeras lineas de una migracion que reconstruye
# tablas referenciadas por otras.
FK_OFF_DIRECTIVE = "-- pragma: foreign_keys=off"

# Las 8 tablas de dominio de §3. `schema_migrations` es infraestructura del runner.
DOMAIN_TABLES = (
    "events_archive",
    "raw_news",
    "outcomes",
    "regimes",
    "calls",
    "call_results",
    "narrative_state",
    "runs",
)


class MigrationError(RuntimeError):
    """Falla estructural de migraciones: hueco de version, duplicado o checksum."""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    path: Path
    sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()

    @property
    def label(self) -> str:
        return f"{self.version:03d}_{self.name}"


# ---------------------------------------------------------------------------
# Conexion
# ---------------------------------------------------------------------------


def resolve_db_path(db_path: str | Path | None = None) -> Path:
    """Precedencia: argumento explicito > env DB_PATH > data/news.db."""
    if db_path is not None:
        return Path(db_path)
    return Path(os.environ.get("DB_PATH", DEFAULT_DB_PATH))


def connect(db_path: str | Path | None = None, *, create_parents: bool = True) -> sqlite3.Connection:
    """Abre la base con los PRAGMA que el sistema da por sentados.

    - foreign_keys=ON: SQLite no valida FK por defecto. Sin esto, la mitad de las
      constraints del schema son decorativas.
    - journal_mode=WAL: el cron de §C.6 corre ingest, classify y score solapados.
    - busy_timeout: en vez de 'database is locked' inmediato.
    """
    path = resolve_db_path(db_path)
    if create_parents and str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    if str(path) != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


# ---------------------------------------------------------------------------
# Migraciones
# ---------------------------------------------------------------------------


def _ensure_migrations_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version        INTEGER PRIMARY KEY,
            name           TEXT NOT NULL,
            checksum       TEXT NOT NULL,
            applied_at_utc TEXT NOT NULL
        )
        """
    )


def discover_migrations(migrations_dir: Path = MIGRATIONS_DIR) -> list[Migration]:
    """Lee los .sql del directorio. Falla ante versiones duplicadas o huecos:
    una secuencia con huecos significa que falta un archivo, no que se saltea."""
    found: dict[int, Migration] = {}
    for path in sorted(migrations_dir.glob("*.sql")):
        match = MIGRATION_FILENAME_RE.match(path.name)
        if not match:
            raise MigrationError(f"nombre de migracion invalido: {path.name} (esperado NNN_nombre.sql)")
        version = int(match.group(1))
        if version in found:
            raise MigrationError(f"version {version:03d} duplicada: {found[version].path.name} y {path.name}")
        found[version] = Migration(
            version=version,
            name=match.group(2),
            path=path,
            sql=path.read_text(encoding="utf-8"),
        )

    migrations = [found[v] for v in sorted(found)]
    for expected, migration in enumerate(migrations, start=1):
        if migration.version != expected:
            raise MigrationError(
                f"hueco en la secuencia de migraciones: se esperaba {expected:03d}, hay {migration.version:03d}"
            )
    return migrations


def applied_migrations(conn: sqlite3.Connection) -> dict[int, sqlite3.Row]:
    _ensure_migrations_table(conn)
    rows = conn.execute("SELECT version, name, checksum, applied_at_utc FROM schema_migrations").fetchall()
    return {row["version"]: row for row in rows}


def schema_version(conn: sqlite3.Connection) -> int:
    """0 = base vacia."""
    applied = applied_migrations(conn)
    return max(applied) if applied else 0


def _split_statements(sql: str) -> list[str]:
    """Parte un script en sentencias usando el parser de sqlite3, no un split(';')."""
    statements: list[str] = []
    buffer = ""
    for line in sql.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            statement = buffer.strip()
            if statement:
                statements.append(statement)
            buffer = ""
    leftover = [ln for ln in buffer.splitlines() if ln.strip() and not ln.strip().startswith("--")]
    if leftover:
        raise MigrationError(f"sentencia SQL incompleta al final del script: {leftover[0][:60]!r}")
    return statements


def verify_checksums(conn: sqlite3.Connection, migrations: list[Migration] | None = None) -> None:
    """Falla si una migracion ya aplicada fue editada despues."""
    migrations = discover_migrations() if migrations is None else migrations
    applied = applied_migrations(conn)
    by_version = {m.version: m for m in migrations}
    for version, row in sorted(applied.items()):
        migration = by_version.get(version)
        if migration is None:
            raise MigrationError(
                f"la base tiene aplicada la migracion {version:03d} ({row['name']}) pero el archivo no existe"
            )
        if migration.checksum != row["checksum"]:
            raise MigrationError(
                f"checksum distinto en {migration.label}: el archivo cambio despues de aplicarse. "
                "Escribi una migracion nueva en vez de editar una aplicada."
            )


def pending_migrations(conn: sqlite3.Connection, migrations: list[Migration] | None = None) -> list[Migration]:
    migrations = discover_migrations() if migrations is None else migrations
    verify_checksums(conn, migrations)
    applied = applied_migrations(conn)
    return [m for m in migrations if m.version not in applied]


def migrate(conn: sqlite3.Connection, migrations: list[Migration] | None = None) -> list[Migration]:
    """Aplica las pendientes en orden. Devuelve las aplicadas en esta corrida."""
    migrations = discover_migrations() if migrations is None else migrations
    pending = pending_migrations(conn, migrations)

    applied_now: list[Migration] = []
    for migration in pending:
        statements = _split_statements(migration.sql)
        # Reconstruir una tabla con hijos que la referencian exige apagar las FK
        # (procedimiento documentado de SQLite). El PRAGMA no funciona adentro de
        # una transaccion, por eso la directiva va en el archivo y se maneja aca.
        fk_off = FK_OFF_DIRECTIVE in "\n".join(migration.sql.splitlines()[:5])
        if fk_off:
            conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("BEGIN")
        try:
            for statement in statements:
                conn.execute(statement)
            if fk_off:
                huerfanas = conn.execute("PRAGMA foreign_key_check").fetchall()
                if huerfanas:
                    raise MigrationError(
                        f"{migration.label} dejo {len(huerfanas)} filas huerfanas: {huerfanas[:3]}"
                    )
            conn.execute(
                "INSERT INTO schema_migrations (version, name, checksum, applied_at_utc) VALUES (?, ?, ?, ?)",
                (migration.version, migration.name, migration.checksum, format_utc(now())),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        finally:
            if fk_off:
                conn.execute("PRAGMA foreign_keys = ON")
        applied_now.append(migration)
    return applied_now


def init_db(db_path: str | Path | None = None) -> tuple[sqlite3.Connection, list[Migration]]:
    """Crea la base si no existe y la deja al dia."""
    conn = connect(db_path)
    _ensure_migrations_table(conn)
    return conn, migrate(conn)


# ---------------------------------------------------------------------------
# Estado y operacion
# ---------------------------------------------------------------------------


def table_names(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [row["name"] for row in rows]


def index_names(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [row["name"] for row in rows]


def table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in table_names(conn):
        counts[table] = conn.execute(f'SELECT COUNT(*) AS n FROM "{table}"').fetchone()["n"]
    return counts


def integrity_check(conn: sqlite3.Connection) -> list[str]:
    """Devuelve problemas encontrados. Lista vacia = base sana."""
    problems = [row[0] for row in conn.execute("PRAGMA integrity_check").fetchall() if row[0] != "ok"]
    for row in conn.execute("PRAGMA foreign_key_check").fetchall():
        problems.append(f"FK huerfana en {row[0]} (rowid {row[1]}) -> {row[2]}")
    return problems


def backup(db_path: str | Path | None = None, dest_dir: str | Path = "data/backups") -> Path:
    """Copia consistente con la API de backup de SQLite (§C.4). No corta escrituras."""
    source_path = resolve_db_path(db_path)
    if not source_path.exists():
        raise FileNotFoundError(f"no existe la base: {source_path}")

    dest_root = Path(dest_dir)
    dest_root.mkdir(parents=True, exist_ok=True)
    stamp = now().strftime("%Y%m%d")
    dest = dest_root / f"news_{stamp}.db"

    source = connect(source_path)
    target = sqlite3.connect(str(dest))
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    return dest


def reset(db_path: str | Path | None = None, *, confirm: bool = False) -> Path:
    """DESTRUCTIVO: borra el archivo y lo recrea vacio y migrado."""
    if not confirm:
        raise RuntimeError("reset exige confirm=True")
    path = resolve_db_path(db_path)
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(str(path) + suffix)
        if candidate.exists():
            candidate.unlink()
    conn, _ = init_db(path)
    conn.close()
    return path


def db_size_bytes(db_path: str | Path | None = None) -> int:
    path = resolve_db_path(db_path)
    total = 0
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(str(path) + suffix)
        if candidate.exists():
            total += candidate.stat().st_size
    return total


def free_disk_bytes(db_path: str | Path | None = None) -> int:
    path = resolve_db_path(db_path)
    target = path.parent if path.parent.exists() else Path(".")
    return shutil.disk_usage(target).free
