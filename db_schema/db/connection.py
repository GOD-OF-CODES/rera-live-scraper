import os
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
from pathlib import Path
from dotenv import load_dotenv

_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path)
else:
    load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")


def get_connection():
    """
    Open a new raw psycopg2 connection using DATABASE_URL from
    the .env file.

    Example .env entry:

        DATABASE_URL=postgresql://postgres:postgres@localhost:5432/up_rera
    """

    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL is not set. Copy .env.example to .env "
            "and fill in your real connection string."
        )

    return psycopg2.connect(DATABASE_URL)


@contextmanager
def get_cursor(commit: bool = True):
    """
    Context manager yielding a dict-returning cursor, with
    automatic commit/rollback and connection cleanup.

    Usage:

        with get_cursor() as cur:
            cur.execute("SELECT 1")
    """

    conn = get_connection()

    try:
        with conn.cursor(
            cursor_factory=psycopg2.extras.RealDictCursor
        ) as cur:

            yield cur

        if commit:
            conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()
