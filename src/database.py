"""Persistencia SQLite y control de duplicados."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from src.models import Business, Lead, LeadStatus

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    place_id      TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    phone         TEXT NOT NULL,
    rating        REAL,
    review_count  INTEGER,
    address       TEXT,
    preview_url   TEXT,
    status        TEXT NOT NULL DEFAULT 'PENDING'
                  CHECK (status IN ('PENDING','GENERATED','SENT','REJECTED')),
    contacted_at  DATETIME,
    -- columnas auxiliares
    phone_digits  TEXT,
    payload_json  TEXT,
    attempts      INTEGER NOT NULL DEFAULT 0,
    last_error    TEXT,
    created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status);
CREATE INDEX IF NOT EXISTS idx_leads_phone  ON leads(phone_digits);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class LeadRepository:
    def __init__(self, path: Path) -> None:
        self.path = path
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # --- escritura ---------------------------------------------------------
    def insert_if_new(self, biz: Business) -> bool:
        """Inserta el lead si su place_id no existe. Devuelve True si es nuevo."""
        with self._conn() as c:
            cur = c.execute(
                """INSERT OR IGNORE INTO leads
                   (place_id, name, phone, rating, review_count, address, phone_digits, payload_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    biz.place_id, biz.name, biz.phone, biz.rating, biz.review_count,
                    biz.address, biz.phone_digits, biz.model_dump_json(),
                ),
            )
            return cur.rowcount == 1

    def mark_generated(self, place_id: str, preview_url: str) -> None:
        self._update(place_id, status=LeadStatus.GENERATED, preview_url=preview_url, last_error=None)

    def mark_sent(self, place_id: str) -> None:
        self._update(place_id, status=LeadStatus.SENT, contacted_at=_now(), last_error=None)

    def mark_rejected(self, place_id: str, reason: str) -> None:
        self._update(place_id, status=LeadStatus.REJECTED, last_error=reason)

    def record_failure(self, place_id: str, error: str, max_attempts: int) -> LeadStatus:
        """Incrementa intentos; tras ``max_attempts`` fallos el lead pasa a REJECTED."""
        with self._conn() as c:
            c.execute(
                "UPDATE leads SET attempts = attempts + 1, last_error = ?, updated_at = ? WHERE place_id = ?",
                (error[:1000], _now(), place_id),
            )
            row = c.execute("SELECT attempts, status FROM leads WHERE place_id = ?", (place_id,)).fetchone()
            if row and row["attempts"] >= max_attempts:
                c.execute("UPDATE leads SET status = 'REJECTED' WHERE place_id = ?", (place_id,))
                return LeadStatus.REJECTED
            return LeadStatus(row["status"]) if row else LeadStatus.PENDING

    def _update(self, place_id: str, **fields: object) -> None:
        fields["updated_at"] = _now()
        cols = ", ".join(f"{k} = ?" for k in fields)
        values = [str(v) if isinstance(v, LeadStatus) else v for v in fields.values()]
        with self._conn() as c:
            c.execute(f"UPDATE leads SET {cols} WHERE place_id = ?", (*values, place_id))

    # --- lectura -----------------------------------------------------------
    def get(self, place_id: str) -> Lead | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM leads WHERE place_id = ?", (place_id,)).fetchone()
        return self._to_lead(row) if row else None

    def get_business(self, place_id: str) -> Business | None:
        with self._conn() as c:
            row = c.execute("SELECT payload_json FROM leads WHERE place_id = ?", (place_id,)).fetchone()
        return Business.model_validate(json.loads(row["payload_json"])) if row and row["payload_json"] else None

    def actionable(self, limit: int) -> list[Lead]:
        """Leads que aún requieren trabajo (PENDING o GENERATED sin enviar)."""
        with self._conn() as c:
            rows = c.execute(
                """SELECT * FROM leads WHERE status IN ('PENDING','GENERATED')
                   ORDER BY review_count DESC, rating DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [self._to_lead(r) for r in rows]

    def phone_already_contacted(self, phone_digits: str, exclude_place_id: str) -> bool:
        """Evita escribir dos veces al mismo número aunque venga de otra ficha."""
        with self._conn() as c:
            row = c.execute(
                """SELECT 1 FROM leads WHERE phone_digits = ? AND place_id != ?
                   AND status = 'SENT' LIMIT 1""",
                (phone_digits, exclude_place_id),
            ).fetchone()
        return row is not None

    def sent_today(self) -> int:
        with self._conn() as c:
            row = c.execute(
                "SELECT COUNT(*) AS n FROM leads WHERE status = 'SENT' AND date(contacted_at) = date('now')"
            ).fetchone()
        return int(row["n"])

    @staticmethod
    def _to_lead(row: sqlite3.Row) -> Lead:
        return Lead(
            place_id=row["place_id"], name=row["name"], phone=row["phone"],
            rating=row["rating"] or 0, review_count=row["review_count"] or 0,
            address=row["address"] or "", preview_url=row["preview_url"],
            status=LeadStatus(row["status"]),
            contacted_at=datetime.fromisoformat(row["contacted_at"]) if row["contacted_at"] else None,
            attempts=row["attempts"], last_error=row["last_error"],
        )
