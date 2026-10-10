"""Read-only access to the SQLite supplier database."""

import os
import sqlite3
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = REPO_ROOT / "data" / "suppliers.db"


def get_db_path() -> Path:
    """DB path from the DB_PATH env var (relative paths resolve against the repo root)."""
    value = os.environ.get("DB_PATH")
    if not value:
        return DEFAULT_DB_PATH
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def get_readonly_connection(db_path: str | os.PathLike[str] | None = None) -> sqlite3.Connection:
    """Open the database read-only.

    Two layers of protection: the file is opened with mode=ro (the OS-level
    handle cannot write), and PRAGMA query_only rejects any write statement.
    """
    path = Path(db_path) if db_path is not None else get_db_path()
    if not path.is_file():
        raise FileNotFoundError(
            f"Database not found at {path}. Build it with: uv run python scripts/build_db.py"
        )
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    conn.execute("PRAGMA query_only = ON")
    return conn
