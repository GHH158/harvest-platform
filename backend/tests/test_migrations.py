import os
import re
import uuid
from pathlib import Path

import pytest
from app.config import Settings
from app.db import (
    MIGRATIONS_DIR,
    Migration,
    MigrationError,
    _verify_history,
    apply_schema,
    discover_migrations,
    make_engine,
    migration_status,
    pending_migrations,
)
from sqlalchemy import text


def _write(directory: Path, name: str, sql: str) -> None:
    (directory / name).write_text(sql, encoding="utf-8")


def test_migrations_are_ordered_by_numeric_prefix(tmp_path: Path) -> None:
    _write(tmp_path, "0010_ten.sql", "SELECT 10;")
    _write(tmp_path, "0002_two.sql", "SELECT 2;")
    _write(tmp_path, "0001_one.sql", "SELECT 1;")

    assert [m.version for m in discover_migrations(tmp_path)] == ["0001", "0002", "0010"]


def test_unparseable_filename_is_rejected_rather_than_skipped(tmp_path: Path) -> None:
    _write(tmp_path, "0001_fine.sql", "SELECT 1;")
    _write(tmp_path, "add_column.sql", "SELECT 2;")

    with pytest.raises(MigrationError, match="NNNN_snake_case"):
        discover_migrations(tmp_path)


def test_duplicate_version_is_rejected(tmp_path: Path) -> None:
    _write(tmp_path, "0001_first.sql", "SELECT 1;")
    _write(tmp_path, "0001_second.sql", "SELECT 2;")

    with pytest.raises(MigrationError, match="重复"):
        discover_migrations(tmp_path)


def test_missing_directory_is_not_an_error(tmp_path: Path) -> None:
    assert discover_migrations(tmp_path / "absent") == []


def test_edited_applied_migration_fails_verification() -> None:
    migration = Migration(version="0001", name="one", sql="SELECT 1;")

    _verify_history({"0001": migration.checksum}, [migration])

    edited = Migration(version="0001", name="one", sql="SELECT 2;")
    with pytest.raises(MigrationError, match="内容已被改动"):
        _verify_history({"0001": migration.checksum}, [edited])


def test_deleted_applied_migration_fails_verification() -> None:
    with pytest.raises(MigrationError, match="已没有这个文件"):
        _verify_history({"0001": "whatever"}, [])


def test_shipped_migrations_parse_and_are_contiguous() -> None:
    migrations = discover_migrations(MIGRATIONS_DIR)

    assert [m.version for m in migrations] == [
        f"{index:04d}" for index in range(1, len(migrations) + 1)
    ]
    assert all(m.sql.strip() for m in migrations)


def test_baseline_holds_no_statement_that_can_change_a_row_twice() -> None:
    """§7.5: anything whose second run could touch a row belongs in migrations/.

    Dollar-quoted bodies are stripped first: DML inside a trigger function or a DO
    block is a definition, not a statement the baseline executes against rows.

    Exactly one statement is exempt, and it is listed here rather than pattern-matched
    so that adding another one has to be a deliberate edit to this test.
    """

    exempt = {
        # Must precede fk_chat_message_session, and that constraint's ON DELETE
        # CASCADE is what makes it unable to match a row on any later run.
        "INSERT INTO chat_session (id, topic)",
    }
    baseline = (MIGRATIONS_DIR.parent / "schema.sql").read_text(encoding="utf-8")
    executed = re.sub(r"\$\$.*?\$\$", " ", baseline, flags=re.DOTALL)
    offending = [
        line.strip()
        for line in executed.splitlines()
        if line.strip().upper().startswith(("INSERT ", "UPDATE ", "DELETE "))
        and line.strip() not in exempt
    ]

    assert offending == []


# --- integration -------------------------------------------------------------


def _integration_engine():
    database_url = os.getenv("HARVEST_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("requires HARVEST_TEST_DATABASE_URL")
    return make_engine(Settings(database_url=database_url))


@pytest.mark.integration
def test_apply_schema_is_idempotent_and_records_versions() -> None:
    """Must hold whether or not this database has been migrated before.

    Asserting that the *first* call does work would only pass against a virgin
    database, which is exactly the assumption that hid a second-run failure.
    """

    engine = _integration_engine()

    apply_schema(engine)
    again = apply_schema(engine)

    assert again == [], "a second run must not re-apply anything"

    status = migration_status(engine)
    assert status["up_to_date"] is True
    assert status["pending"] == []
    assert status["current_version"] == status["latest_available"]
    assert len(status["applied"]) == len(discover_migrations(MIGRATIONS_DIR))


@pytest.mark.integration
def test_failing_migration_leaves_neither_change_nor_bookkeeping(tmp_path: Path) -> None:
    engine = _integration_engine()
    apply_schema(engine)
    table = f"migration_probe_{uuid.uuid4().hex[:8]}"

    _write(
        tmp_path,
        "0001_creates_then_fails.sql",
        f"CREATE TABLE {table} (id INT); SELECT * FROM a_table_that_does_not_exist;",
    )

    with pytest.raises(Exception):
        apply_schema(engine, tmp_path)

    with engine.begin() as connection:
        assert connection.execute(
            text("SELECT to_regclass(:name)"), {"name": f"public.{table}"}
        ).scalar() is None
        recorded = connection.execute(
            text("SELECT count(*) FROM schema_migration WHERE version = '0001' AND name = 'creates_then_fails'")
        ).scalar()
    assert recorded == 0


@pytest.mark.integration
def test_pending_migrations_reports_only_unapplied_work() -> None:
    engine = _integration_engine()
    apply_schema(engine)

    assert pending_migrations(engine) == []
