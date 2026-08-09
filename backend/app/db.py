from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Connection, Engine, create_engine, text

from .config import ROOT_DIR, Settings, get_settings

BASELINE_PATH = ROOT_DIR / "backend" / "app" / "schema.sql"
MIGRATIONS_DIR = ROOT_DIR / "backend" / "app" / "migrations"
MIGRATION_FILENAME = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")

# The runner owns this table rather than schema.sql: it has to be able to read the
# applied set before deciding whether the baseline is even allowed to run again.
SCHEMA_MIGRATION_DDL = """
CREATE TABLE IF NOT EXISTS schema_migration (
    version     TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    checksum    TEXT NOT NULL,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    duration_ms INTEGER NOT NULL
);
"""


class MigrationError(RuntimeError):
    """The migration directory and the database no longer describe the same history."""


@dataclass(frozen=True)
class Migration:
    version: str
    name: str
    sql: str

    @property
    def checksum(self) -> str:
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()


def make_engine(settings: Settings | None = None) -> Engine:
    active_settings = settings or get_settings()
    return create_engine(active_settings.database_url, pool_pre_ping=True)


def discover_migrations(directory: Path | None = None) -> list[Migration]:
    """Read `NNNN_name.sql` files in version order.

    Ordering is by the numeric prefix, not by filesystem order. Anything that does
    not match the contract in §7.5 is a hard error: a file silently ignored here
    would look applied to whoever added it.
    """

    source = directory or MIGRATIONS_DIR
    if not source.is_dir():
        return []
    migrations: dict[str, Migration] = {}
    for path in sorted(source.iterdir()):
        if path.name.startswith(".") or path.is_dir():
            continue
        match = MIGRATION_FILENAME.match(path.name)
        if match is None:
            raise MigrationError(
                f"迁移文件名不符合 NNNN_snake_case.sql 约定（§7.5）：{path.name}"
            )
        version, name = match.group(1), match.group(2)
        if version in migrations:
            raise MigrationError(f"迁移序号 {version} 重复，无法确定执行顺序。")
        migrations[version] = Migration(
            version=version, name=name, sql=path.read_text(encoding="utf-8")
        )
    return [migrations[version] for version in sorted(migrations)]


def _ensure_migration_table(connection: Connection) -> None:
    connection.exec_driver_sql(SCHEMA_MIGRATION_DDL)


def _applied_checksums(connection: Connection) -> dict[str, str]:
    rows = connection.execute(text("SELECT version, checksum FROM schema_migration")).all()
    return {str(row[0]): str(row[1]) for row in rows}


def _verify_history(applied: dict[str, str], migrations: list[Migration]) -> None:
    """A migration that already ran is a fact; the file must still match it.

    Editing or deleting applied migrations is the failure this guards: the database
    would keep the old effect while the directory advertises a new one, and nothing
    downstream could tell.
    """

    by_version = {migration.version: migration for migration in migrations}
    for version, checksum in sorted(applied.items()):
        migration = by_version.get(version)
        if migration is None:
            raise MigrationError(
                f"数据库记录已应用迁移 {version}，但目录中已没有这个文件；"
                "历史迁移不得删除或改名。"
            )
        if migration.checksum != checksum:
            raise MigrationError(
                f"迁移 {version}_{migration.name}.sql 的内容已被改动，"
                "但它在本库上已经执行过；历史迁移一旦应用即为既成事实，"
                "需要修正请追加一个新的迁移。"
            )


def pending_migrations(engine: Engine, directory: Path | None = None) -> list[Migration]:
    migrations = discover_migrations(directory)
    with engine.begin() as connection:
        _ensure_migration_table(connection)
        applied = _applied_checksums(connection)
    _verify_history(applied, migrations)
    return [migration for migration in migrations if migration.version not in applied]


def apply_pending_migrations(engine: Engine, directory: Path | None = None) -> list[str]:
    """Apply outstanding migrations in order, each in its own transaction.

    The bookkeeping row is written inside the same transaction as the migration
    body, so a failure leaves neither the change nor a claim that it happened.
    """

    applied_now: list[str] = []
    for migration in pending_migrations(engine, directory):
        started = time.perf_counter()
        with engine.begin() as connection:
            connection.exec_driver_sql(migration.sql)
            connection.execute(
                text(
                    """INSERT INTO schema_migration (version, name, checksum, duration_ms)
                       VALUES (:version, :name, :checksum, :duration_ms)"""
                ),
                {
                    "version": migration.version,
                    "name": migration.name,
                    "checksum": migration.checksum,
                    "duration_ms": int((time.perf_counter() - started) * 1000),
                },
            )
        applied_now.append(f"{migration.version}_{migration.name}")
    return applied_now


def migration_status(engine: Engine, directory: Path | None = None) -> dict[str, object]:
    migrations = discover_migrations(directory)
    with engine.begin() as connection:
        _ensure_migration_table(connection)
        applied = _applied_checksums(connection)
        rows = connection.execute(
            text(
                """SELECT version, name, applied_at, duration_ms
                   FROM schema_migration ORDER BY version"""
            )
        ).mappings().all()
    _verify_history(applied, migrations)
    outstanding = [m for m in migrations if m.version not in applied]
    return {
        "current_version": max(applied) if applied else None,
        "latest_available": migrations[-1].version if migrations else None,
        "applied": [
            {
                "version": str(row["version"]),
                "name": str(row["name"]),
                "applied_at": row["applied_at"].isoformat(),
                "duration_ms": int(row["duration_ms"]),
            }
            for row in rows
        ],
        "pending": [f"{m.version}_{m.name}" for m in outstanding],
        "up_to_date": not outstanding,
    }


def apply_baseline(engine: Engine) -> None:
    """Bring any database up to the idempotent baseline (§7.5).

    schema.sql must stay re-runnable and must not contain statements that can
    change an existing row on a second run; those belong in migrations/.
    """

    with engine.begin() as connection:
        connection.exec_driver_sql(BASELINE_PATH.read_text(encoding="utf-8"))


def apply_schema(engine: Engine, directory: Path | None = None) -> list[str]:
    """Baseline, then outstanding migrations — the fixed startup order of §7.5.

    Returns the migrations applied by this call so callers can log a real change
    instead of asserting readiness they did not verify.
    """

    apply_baseline(engine)
    return apply_pending_migrations(engine, directory)


def main() -> None:
    applied = apply_schema(make_engine())
    if applied:
        print("Applied migrations: " + ", ".join(applied))
    print("Harvest schema is ready.")


if __name__ == "__main__":
    main()
