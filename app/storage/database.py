import sqlite3
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS positions (
    position_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    entry_price TEXT NOT NULL,
    stop_loss TEXT NOT NULL,
    total_amount TEXT NOT NULL,
    quantity TEXT NOT NULL,
    leverage TEXT NOT NULL,
    take_profit TEXT,
    status TEXT NOT NULL,
    opened_at TEXT NOT NULL,
    closed_at TEXT,
    exit_price TEXT,
    realized_pnl TEXT,
    close_reason TEXT
);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    """Open SQLite and ensure the current position schema exists."""
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(SCHEMA)

    columns = {row[1] for row in connection.execute("PRAGMA table_info(positions)")}
    if "take_profit" not in columns:
        connection.execute("ALTER TABLE positions ADD COLUMN take_profit TEXT")
    connection.commit()
    return connection
