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
    close_reason TEXT,
    decision_snapshot TEXT
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
    filled_at TEXT,
    decision_snapshot TEXT
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

CREATE TABLE IF NOT EXISTS account_ledger (
    ledger_id TEXT PRIMARY KEY,
    position_id TEXT NOT NULL UNIQUE,
    cycle_id TEXT,
    realized_pnl TEXT NOT NULL,
    equity_before TEXT NOT NULL,
    equity_after TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (position_id) REFERENCES positions(position_id)
);

CREATE TABLE IF NOT EXISTS trade_journal (
    position_id TEXT PRIMARY KEY,
    cycle_id TEXT,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    entry_price TEXT NOT NULL,
    exit_price TEXT NOT NULL,
    stop_loss TEXT NOT NULL,
    take_profit TEXT,
    total_amount TEXT NOT NULL,
    quantity TEXT NOT NULL,
    leverage TEXT NOT NULL,
    realized_pnl TEXT NOT NULL,
    opened_at TEXT NOT NULL,
    closed_at TEXT NOT NULL,
    close_reason TEXT NOT NULL,
    decision_snapshot TEXT
);

CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_fills_order_id ON fills(order_id);
CREATE INDEX IF NOT EXISTS idx_fills_filled_at ON fills(filled_at);
CREATE INDEX IF NOT EXISTS idx_pending_orders_status ON pending_orders(status);
CREATE INDEX IF NOT EXISTS idx_account_ledger_created_at ON account_ledger(created_at);
CREATE INDEX IF NOT EXISTS idx_trade_journal_closed_at ON trade_journal(closed_at);
CREATE INDEX IF NOT EXISTS idx_trade_journal_symbol ON trade_journal(symbol);
"""


def _ensure_column(
    connection: sqlite3.Connection, table: str, column: str, declaration: str
) -> None:
    columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")


def connect(path: str | Path) -> sqlite3.Connection:
    """Open SQLite and apply backward-compatible schema migrations."""
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA foreign_keys = ON")
    connection.executescript(SCHEMA)
    _ensure_column(connection, "positions", "take_profit", "TEXT")
    _ensure_column(connection, "positions", "decision_snapshot", "TEXT")
    _ensure_column(connection, "orders", "decision_snapshot", "TEXT")
    _ensure_column(connection, "trade_journal", "decision_snapshot", "TEXT")
    connection.commit()
    return connection
