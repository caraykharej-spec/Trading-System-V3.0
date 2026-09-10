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

CREATE TABLE IF NOT EXISTS cycle_audits (
    cycle_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    monitored_positions INTEGER NOT NULL DEFAULT 0,
    stopped_positions INTEGER NOT NULL DEFAULT 0,
    filled_orders INTEGER NOT NULL DEFAULT 0,
    notes TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    order_type TEXT NOT NULL,
    quantity TEXT NOT NULL,
    requested_price TEXT,
    stop_loss TEXT NOT NULL,
    take_profit TEXT,
    leverage TEXT NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING',
    filled_price TEXT,
    reason TEXT,
    filled_at TEXT
);

CREATE TABLE IF NOT EXISTS fills (
    fill_id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity TEXT NOT NULL,
    price TEXT NOT NULL,
    commission TEXT NOT NULL DEFAULT '0',
    filled_at TEXT NOT NULL,
    FOREIGN KEY (order_id) REFERENCES orders(order_id)
);

CREATE TABLE IF NOT EXISTS pending_orders (
    order_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    accepted_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    cancel_reason TEXT,
    rejection_reason TEXT,
    FOREIGN KEY (order_id) REFERENCES orders(order_id)
);

CREATE TABLE IF NOT EXISTS account_state (
    account_id TEXT PRIMARY KEY,
    equity TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_fills_order_id ON fills(order_id);
CREATE INDEX IF NOT EXISTS idx_fills_filled_at ON fills(filled_at);
CREATE INDEX IF NOT EXISTS idx_pending_orders_status ON pending_orders(status);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    """Open SQLite and ensure all current persistence tables exist."""
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
