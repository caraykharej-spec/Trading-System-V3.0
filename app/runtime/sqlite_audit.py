from __future__ import annotations

import sqlite3

from .audit import AuditStatus, CycleAudit, CycleAuditRepository


class SQLiteCycleAuditRepository(CycleAuditRepository):
    """SQLite-backed cycle audit log for restart/recovery inspection."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS cycle_audits (
                cycle_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                monitored_positions INTEGER NOT NULL DEFAULT 0,
                stopped_positions INTEGER NOT NULL DEFAULT 0,
                filled_orders INTEGER NOT NULL DEFAULT 0,
                notes TEXT NOT NULL DEFAULT ''
            )"""
        )
        self.connection.commit()

    def save(self, audit: CycleAudit) -> None:
        self.connection.execute(
            """INSERT OR REPLACE INTO cycle_audits (
                cycle_id, status, started_at, finished_at,
                monitored_positions, stopped_positions, filled_orders, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                audit.cycle_id,
                audit.status.value,
                audit.started_at.isoformat(),
                audit.finished_at.isoformat() if audit.finished_at else None,
                audit.monitored_positions,
                audit.stopped_positions,
                audit.filled_orders,
                "\n".join(audit.notes),
            ),
        )
        self.connection.commit()

    def get(self, cycle_id: str) -> CycleAudit | None:
        row = self.connection.execute(
            "SELECT cycle_id, status, started_at, finished_at, monitored_positions, "
            "stopped_positions, filled_orders, notes FROM cycle_audits WHERE cycle_id = ?",
            (cycle_id,),
        ).fetchone()
        return self._from_row(row) if row else None

    def latest(self) -> CycleAudit | None:
        row = self.connection.execute(
            "SELECT cycle_id, status, started_at, finished_at, monitored_positions, "
            "stopped_positions, filled_orders, notes FROM cycle_audits "
            "ORDER BY started_at DESC, cycle_id DESC LIMIT 1"
        ).fetchone()
        return self._from_row(row) if row else None

    @staticmethod
    def _from_row(row: tuple[object, ...]) -> CycleAudit:
        cycle_id, status, started_at, finished_at, monitored, stopped, filled, notes = row
        return CycleAudit(
            cycle_id=str(cycle_id),
            status=AuditStatus(str(status)),
            started_at=__import__("datetime").datetime.fromisoformat(str(started_at)),
            finished_at=(__import__("datetime").datetime.fromisoformat(str(finished_at)) if finished_at else None),
            monitored_positions=int(monitored),
            stopped_positions=int(stopped),
            filled_orders=int(filled),
            notes=tuple(str(notes).split("\n")) if notes else (),
        )
