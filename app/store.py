"""Storage: SQLite by default, Postgres when DATABASE_URL is set (Vercel + Neon). Three tables that matter:
bills (incoming), customer_invoices (outgoing), audit."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS bills (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL,
  source TEXT NOT NULL,            -- filename or 'upload'
  raw_text TEXT NOT NULL,
  supplier TEXT, supplier_email TEXT, invoice_number TEXT,
  invoice_date TEXT, due_date TEXT,
  amount REAL, currency TEXT, line_items TEXT,   -- JSON
  confidence REAL,
  status TEXT NOT NULL,            -- extracted | needs_approval | approved | paying | paid | failed | rejected
  reason TEXT,                     -- policy / agent explanation
  payout_batch_id TEXT, payout_item_id TEXT, payout_status TEXT,
  risk_level TEXT, risk_signals TEXT,  -- JSON list
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS suppliers (
  email TEXT PRIMARY KEY, name TEXT, first_seen TEXT, trusted INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS customer_invoices (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL,
  paypal_invoice_id TEXT, invoice_number TEXT,
  customer_name TEXT, customer_email TEXT,
  amount REAL, currency TEXT, due_date TEXT, memo TEXT,
  status TEXT, pay_url TEXT, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL,
  actor TEXT NOT NULL,             -- agent | human | system
  tool TEXT NOT NULL,
  input TEXT, output TEXT, reason TEXT, ok INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS ledger (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL, amount REAL NOT NULL, currency TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY, value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chat (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL
);
"""

BILL_COLS = ["id", "created_at", "source", "raw_text", "supplier", "supplier_email", "invoice_number",
             "invoice_date", "due_date", "amount", "currency", "line_items", "confidence", "status", "reason",
             "payout_batch_id", "payout_item_id", "payout_status", "updated_at"]


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class _DB:
    """Minimal uniform layer: execute(sql, params) with '?' placeholders, rows as dicts, autocommit."""

    def __init__(self, path: str):
        # Prefer a direct connection: Neon's pooled URL shares server sessions between callers, and a
        # session that once ran SET search_path keeps it for everyone, so tables can land in the wrong schema.
        self.url = os.environ.get("DATABASE_URL_UNPOOLED") or os.environ.get("DATABASE_URL")
        if self.url:
            import psycopg
            from psycopg.rows import dict_row
            self.pg = True
            self.conn = psycopg.connect(self.url, autocommit=True, row_factory=dict_row)
            schema = SCHEMA.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
            with self.conn.cursor() as cur:
                cur.execute("SET search_path TO public")
                for stmt in schema.split(";"):
                    if stmt.strip():
                        cur.execute(stmt)
                for col in ("risk_level", "risk_signals"):
                    cur.execute(f"ALTER TABLE bills ADD COLUMN IF NOT EXISTS {col} TEXT")
        else:
            self.pg = False
            self.conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
            self.conn.row_factory = sqlite3.Row
            self.conn.executescript(SCHEMA)
            have = {r[1] for r in self.conn.execute("PRAGMA table_info(bills)").fetchall()}
            for col in ("risk_level", "risk_signals"):
                if col not in have:
                    self.conn.execute(f"ALTER TABLE bills ADD COLUMN {col} TEXT")

    def execute(self, sql: str, params: tuple = ()):
        if self.pg:
            cur = self.conn.cursor()
            cur.execute(sql.replace("?", "%s"), params)
            return cur
        return self.conn.execute(sql, params)

    def insert(self, sql: str, params: tuple = ()) -> int:
        if self.pg:
            cur = self.conn.cursor()
            cur.execute(sql.replace("?", "%s") + " RETURNING id", params)
            return cur.fetchone()["id"]
        return self.conn.execute(sql, params).lastrowid


class Store:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        self.db = _DB(path)

    # --- bills -------------------------------------------------------------
    def add_bill(self, source: str, raw_text: str) -> int:
        with self._lock:
            return self.db.insert(
                "INSERT INTO bills (created_at, source, raw_text, status, updated_at) VALUES (?,?,?,?,?)",
                (now(), source, raw_text, "received", now()))

    def update_bill(self, bill_id: int, **fields: Any) -> None:
        for k in ("line_items", "risk_signals"):
            if k in fields and fields[k] is not None and not isinstance(fields[k], str):
                fields[k] = json.dumps(fields[k], ensure_ascii=False)
        fields["updated_at"] = now()
        cols = ", ".join(f"{k}=?" for k in fields)
        with self._lock:
            self.db.execute(f"UPDATE bills SET {cols} WHERE id=?", (*fields.values(), bill_id))

    def get_bill(self, bill_id: int) -> dict | None:
        row = self.db.execute("SELECT * FROM bills WHERE id=?", (bill_id,)).fetchone()
        return _bill(row) if row else None

    def list_bills(self, status: str | None = None) -> list[dict]:
        if status:
            rows = self.db.execute("SELECT * FROM bills WHERE status=? ORDER BY id DESC", (status,)).fetchall()
        else:
            rows = self.db.execute("SELECT * FROM bills ORDER BY id DESC").fetchall()
        return [_bill(r) for r in rows]

    def find_duplicate(self, supplier_email: str | None, invoice_number: str | None, exclude_id: int) -> dict | None:
        if not invoice_number:
            return None
        row = self.db.execute(
            "SELECT * FROM bills WHERE invoice_number=? AND COALESCE(supplier_email,'')=COALESCE(?,'') "
            "AND id<>? AND status<>'rejected' ORDER BY id LIMIT 1",
            (invoice_number, supplier_email, exclude_id)).fetchone()
        return _bill(row) if row else None

    # --- suppliers ---------------------------------------------------------
    def get_supplier(self, email: str | None) -> dict | None:
        if not email:
            return None
        row = self.db.execute("SELECT * FROM suppliers WHERE email=?", (email.lower(),)).fetchone()
        return dict(row) if row else None

    def find_supplier_by_name(self, name: str | None) -> dict | None:
        if not name:
            return None
        row = self.db.execute("SELECT * FROM suppliers WHERE lower(name)=lower(?) AND trusted=1 LIMIT 1", (name.strip(),)).fetchone()
        return dict(row) if row else None

    def upsert_supplier(self, email: str, name: str | None, trusted: bool | None = None) -> None:
        email = email.lower()
        with self._lock:
            cur = self.db.execute("SELECT trusted FROM suppliers WHERE email=?", (email,)).fetchone()
            if cur is None:
                self.db.execute("INSERT INTO suppliers (email, name, first_seen, trusted) VALUES (?,?,?,?)",
                                (email, name, now(), 1 if trusted else 0))
            elif trusted is not None:
                self.db.execute("UPDATE suppliers SET trusted=?, name=COALESCE(?, name) WHERE email=?",
                                (1 if trusted else 0, name, email))

    def list_suppliers(self) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT * FROM suppliers ORDER BY name").fetchall()]

    # --- customer invoices -------------------------------------------------
    def add_customer_invoice(self, **f: Any) -> int:
        f.setdefault("created_at", now())
        f["updated_at"] = now()
        cols = ", ".join(f)
        qs = ", ".join("?" for _ in f)
        with self._lock:
            return self.db.insert(f"INSERT INTO customer_invoices ({cols}) VALUES ({qs})", tuple(f.values()))

    def update_customer_invoice(self, row_id: int, **fields: Any) -> None:
        fields["updated_at"] = now()
        cols = ", ".join(f"{k}=?" for k in fields)
        with self._lock:
            self.db.execute(f"UPDATE customer_invoices SET {cols} WHERE id=?", (*fields.values(), row_id))

    def list_customer_invoices(self) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT * FROM customer_invoices ORDER BY id DESC").fetchall()]

    # --- settings ------------------------------------------------------------
    def get_setting(self, key: str) -> str | None:
        row = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return dict(row)["value"] if row else None

    def set_setting(self, key: str, value: str) -> None:
        with self._lock:
            self.db.execute("DELETE FROM settings WHERE key=?", (key,))
            self.db.execute("INSERT INTO settings (key, value) VALUES (?,?)", (key, value))

    # --- audit & chat ------------------------------------------------------
    def audit(self, actor: str, tool: str, input: Any, output: Any, reason: str | None, ok: bool) -> None:
        with self._lock:
            self.db.execute("INSERT INTO audit (ts, actor, tool, input, output, reason, ok) VALUES (?,?,?,?,?,?,?)",
                            (now(), actor, tool, _dump(input), _dump(output), reason, 1 if ok else 0))

    def add_ledger(self, amount: float, currency: str) -> None:
        """Money that left the PayPal account through Kassa. Survives demo resets on purpose."""
        with self._lock:
            self.db.execute("INSERT INTO ledger (ts, amount, currency) VALUES (?,?,?)", (now(), amount, currency))

    def sent_since(self, ts: str, currency: str) -> float:
        row = self.db.execute("SELECT COALESCE(SUM(amount), 0) AS s FROM ledger WHERE ts > ? AND currency = ?",
                              (ts, currency)).fetchone()
        return float(row["s"] or 0)

    def list_audit(self, limit: int = 200) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]

    def add_chat(self, role: str, content: str) -> None:
        with self._lock:
            self.db.execute("INSERT INTO chat (ts, role, content) VALUES (?,?,?)", (now(), role, content))

    def list_chat(self, limit: int = 40) -> list[dict]:
        rows = self.db.execute("SELECT * FROM chat ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in reversed(rows)]

    def reset(self) -> None:
        with self._lock:
            for t in ("bills", "suppliers", "customer_invoices", "audit", "chat"):
                self.db.execute(f"DELETE FROM {t}")


def _bill(row) -> dict:
    d = dict(row)
    for k in ("line_items", "risk_signals"):
        if d.get(k):
            try:
                d[k] = json.loads(d[k])
            except (ValueError, TypeError):
                pass
    return d


def _dump(x: Any) -> str:
    if isinstance(x, str):
        return x[:4000]
    return json.dumps(x, ensure_ascii=False, default=str)[:4000]
