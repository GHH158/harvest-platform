from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine

from .config import ROOT_DIR, Settings, get_settings


def make_engine(settings: Settings | None = None) -> Engine:
    active_settings = settings or get_settings()
    return create_engine(active_settings.database_url, pool_pre_ping=True)


def apply_schema(engine: Engine) -> None:
    schema_path = Path(ROOT_DIR / "backend" / "app" / "schema.sql")
    with engine.begin() as connection:
        connection.exec_driver_sql(schema_path.read_text(encoding="utf-8"))


def main() -> None:
    apply_schema(make_engine())
    print("Harvest schema is ready.")


if __name__ == "__main__":
    main()
