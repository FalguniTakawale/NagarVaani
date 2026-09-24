"""
Create the NagarVaani database schema.

    python setup_db.py

Reads DATABASE_URL from .env. Works for SQLite (creates the file) and
PostgreSQL (connects and creates every table). Safe to re-run: existing
tables are left alone, and the one column added after v1 (users.is_email_verified)
is back-filled onto an existing users table if it's missing.
"""

import asyncio
import re
import sys

from sqlalchemy import inspect, text

EXPECTED_TABLES = [
    "users", "complaints", "votes", "comments",
    "linked_areas", "status_log", "email_verifications", "districts",
]

# Columns added after the first schema went live. create_all() never ALTERs an
# existing table, so these are applied by hand.
# (table, column, DDL type+default, SQL to run once right after adding)
ADDED_COLUMNS = [
    # Accounts that existed before email verification was introduced are
    # grandfathered in — otherwise the migration would lock everyone out.
    ("users", "is_email_verified", "BOOLEAN NOT NULL DEFAULT FALSE",
     "UPDATE users SET is_email_verified = TRUE"),
]


def _mask(url: str) -> str:
    return re.sub(r"://([^:/@]+):([^@]+)@", r"://\1:****@", url)


def _explain(err: Exception, url: str, is_sqlite: bool) -> str:
    msg = str(err)
    if is_sqlite:
        return (
            f"{msg}\n\nHow to fix: the SQLite path in DATABASE_URL must be writable.\n"
            f"  URL: {url}\n"
            "  A relative path like sqlite+aiosqlite:///./nagarvaani.db is created next to this script.\n"
            "  Check the directory exists and you have write permission."
        )
    hints = [
        "How to fix (PostgreSQL):",
        "  1. Is Postgres running?          brew services start postgresql@16   (mac)",
        "                                    sudo service postgresql start       (linux)",
        "  2. Does the database exist?       createdb nagarvaani",
        "  3. Is DATABASE_URL right?         postgresql+asyncpg://USER:PASS@HOST:5432/nagarvaani",
        "     (postgres:// and postgresql:// are rewritten to asyncpg automatically)",
        "  4. No Postgres at all? Use SQLite: DATABASE_URL=sqlite+aiosqlite:///./nagarvaani.db",
    ]
    lower = msg.lower()
    if "password authentication failed" in lower:
        hints.insert(1, "  → The password in DATABASE_URL is wrong.")
    elif "does not exist" in lower and "database" in lower:
        hints.insert(1, "  → The database hasn't been created yet: run `createdb nagarvaani`.")
    elif "connection refused" in lower or "connect call failed" in lower:
        hints.insert(1, "  → Nothing is listening on that host/port — Postgres is probably not running.")
    elif "asyncpg" in lower and "no module" in lower:
        hints.insert(1, "  → Driver missing: pip install asyncpg")
    return f"{msg}\n\n" + "\n".join(hints)


async def main() -> int:
    # Import lazily so a bad DATABASE_URL fails inside our try/except, not at import.
    try:
        from app.config import get_settings
        from app.database import engine, create_tables
        import app.models.models  # noqa: F401 — registers every table on Base.metadata
    except Exception as e:  # pragma: no cover
        print(f"✗ Could not load app settings: {e}")
        print("  Run this from the Backend/ directory with the venv activated, and make sure .env exists.")
        return 1

    settings = get_settings()
    url = settings.database_url
    is_sqlite = url.startswith("sqlite")
    print(f"Database: {'SQLite' if is_sqlite else 'PostgreSQL'}  ({_mask(url)})")

    try:
        await create_tables()

        async with engine.begin() as conn:
            def _inspect(sync_conn):
                insp = inspect(sync_conn)
                return {
                    t: {c["name"] for c in insp.get_columns(t)}
                    for t in insp.get_table_names()
                }
            schema = await conn.run_sync(_inspect)

            for table, column, ddl, backfill in ADDED_COLUMNS:
                if table in schema and column not in schema[table]:
                    await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
                    if backfill:
                        await conn.execute(text(backfill))
                    print(f"  + migrated: added {table}.{column} (existing rows back-filled)")

        async with engine.begin() as conn:
            tables = await conn.run_sync(lambda c: inspect(c).get_table_names())
    except Exception as e:
        print("✗ Database setup failed:")
        print(_explain(e, _mask(url), is_sqlite))
        return 1
    finally:
        await engine.dispose()

    present = [t for t in EXPECTED_TABLES if t in tables]
    missing = [t for t in EXPECTED_TABLES if t not in tables]
    if not is_sqlite:
        for t in sorted(tables):
            print(f"  table: {t}")
    print(f"✓ {len(present)} tables created: {', '.join(present)}")
    if missing:
        print(f"✗ expected but missing: {', '.join(missing)}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
