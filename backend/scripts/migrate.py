from __future__ import annotations

import argparse
import sys

from app.db import MigrationError, apply_schema, make_engine, migration_status


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect or advance the database schema version (§7.5). --status answers "
            "'which version is this database on' without starting the API."
        )
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--status", action="store_true", help="Print applied and pending migrations.")
    group.add_argument(
        "--apply",
        action="store_true",
        help="Apply the baseline and any outstanding migrations, then print the new status.",
    )
    return parser.parse_args()


def _print_status(status: dict[str, object]) -> None:
    print(f"current version : {status['current_version'] or '(none)'}")
    print(f"latest available: {status['latest_available'] or '(none)'}")
    applied = status["applied"]
    assert isinstance(applied, list)
    print(f"applied ({len(applied)}):")
    for row in applied:
        print(f"  {row['version']}_{row['name']}  {row['applied_at']}  {row['duration_ms']}ms")
    pending = status["pending"]
    assert isinstance(pending, list)
    if pending:
        print(f"pending ({len(pending)}):")
        for name in pending:
            print(f"  {name}")
    else:
        print("pending (0): up to date")


def main() -> int:
    arguments = _arguments()
    engine = make_engine()
    try:
        if arguments.apply:
            applied = apply_schema(engine)
            print("applied now: " + (", ".join(applied) if applied else "(nothing outstanding)"))
        _print_status(migration_status(engine))
    except MigrationError as error:
        print(f"Migration history check failed: {error}", file=sys.stderr)
        return 2
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
