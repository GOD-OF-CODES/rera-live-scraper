"""
Applies ../schema.sql to the database configured in .env
(DATABASE_URL).

NOTE: schema.sql uses plain CREATE TABLE (no IF NOT EXISTS),
matching the approved design document exactly. That means this
script is meant to be run ONCE against a fresh, empty database.
Running it twice against the same database will fail with
"relation already exists" errors - which is intentional, so you
don't silently run it against a database that already has data.

If you need to re-apply the schema during development, drop and
recreate the database first, e.g.:

    dropdb up_rera && createdb up_rera

Run from the db_schema project root:

    python -m db.init_db
"""

from pathlib import Path

from db.connection import get_connection

SCHEMA_FILE = Path(__file__).parent.parent / "schema.sql"


def init_db():

    print("Applying schema from:", SCHEMA_FILE)

    sql = SCHEMA_FILE.read_text(encoding="utf-8")

    conn = get_connection()

    try:
        with conn.cursor() as cur:
            cur.execute(sql)

        conn.commit()

        print("Schema applied successfully.")

    except Exception as error:
        conn.rollback()

        print("Failed to apply schema:")
        print(f"{type(error).__name__}: {error}")
        print(
            "\nIf this is 'relation already exists', the schema "
            "was likely already applied. Drop and recreate the "
            "database if you need a clean re-apply."
        )

        raise

    finally:
        conn.close()


if __name__ == "__main__":
    init_db()
