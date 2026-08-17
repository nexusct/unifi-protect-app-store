"""Subscription store: SQLite-backed signup records.

Self-contained (no external DB) — the container owns its subscription data.
Signups also forward to the Base44 sales pipeline as FormSubmissions when
BASE44_ALERT_URL is configured (they're hot leads — scoreAndRouteLead picks
them up on the NexusCT side).
"""
import json
import os
import secrets
import sqlite3
import threading
import time
from pathlib import Path

DB_PATH = Path(os.environ.get("VISION_DATA", "/app/data")) / "subscriptions.db"
_lock = threading.Lock()


class SubscriptionCapacityError(RuntimeError):
    """Raised when the configured local signup-record bound is reached."""

SCHEMA = """
CREATE TABLE IF NOT EXISTS subscriptions (
  id TEXT PRIMARY KEY,
  company TEXT NOT NULL,
  contact_name TEXT NOT NULL,
  email TEXT NOT NULL,
  phone TEXT,
  industry TEXT,
  tier TEXT NOT NULL,
  sites INTEGER DEFAULT 1,
  cameras INTEGER,
  functions TEXT DEFAULT '[]',
  notes TEXT,
  status TEXT DEFAULT 'new',
  created_at TEXT NOT NULL
);
"""


def _conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(DB_PATH))
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with _lock, _conn() as c:
        c.executescript(SCHEMA)


def create_sub(data: dict) -> dict:
    sub_id = "SUB-" + secrets.token_urlsafe(24)
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    row = {
        "id": sub_id,
        "company": str(data.get("company", "")).strip()[:200],
        "contact_name": str(data.get("contactName", "")).strip()[:120],
        "email": str(data.get("email", "")).strip()[:200],
        "phone": str(data.get("phone", "")).strip()[:40],
        "industry": str(data.get("industry", "")).strip()[:80],
        "tier": str(data.get("tier", "")).strip()[:20],
        "sites": max(1, int(data.get("sites") or 1)),
        "cameras": int(data["cameras"]) if data.get("cameras") else None,
        "functions": json.dumps(data.get("functions") or []),
        "notes": str(data.get("notes", "")).strip()[:2000],
        "status": "new",
        "created_at": now,
    }
    max_records = max(1, int(os.environ.get("VISION_SUBSCRIPTION_MAX_RECORDS", "10000")))
    with _lock, _conn() as c:
        count = c.execute("SELECT COUNT(*) FROM subscriptions").fetchone()[0]
        if count >= max_records:
            raise SubscriptionCapacityError(f"subscription record limit {max_records} reached")
        c.execute(
            "INSERT INTO subscriptions (id, company, contact_name, email, phone, industry, tier, sites, cameras, functions, notes, status, created_at) "
            "VALUES (:id, :company, :contact_name, :email, :phone, :industry, :tier, :sites, :cameras, :functions, :notes, :status, :created_at)",
            row,
        )
    return row


def get_sub(sub_id: str) -> dict | None:
    with _lock, _conn() as c:
        r = c.execute("SELECT * FROM subscriptions WHERE id = ?", (sub_id,)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["functions"] = json.loads(d["functions"])
    return d


def list_subs(status: str | None = None) -> list[dict]:
    q = "SELECT * FROM subscriptions"
    args = ()
    if status:
        q += " WHERE status = ?"
        args = (status,)
    q += " ORDER BY created_at DESC"
    with _lock, _conn() as c:
        rows = c.execute(q, args).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["functions"] = json.loads(d["functions"])
        out.append(d)
    return out


def set_status(sub_id: str, status: str) -> bool:
    with _lock, _conn() as c:
        cur = c.execute("UPDATE subscriptions SET status = ? WHERE id = ?", (status, sub_id))
        return cur.rowcount > 0


def forward_to_base44(row: dict) -> bool:
    """Best-effort forward into the NexusCT sales pipeline as a FormSubmission.
    The existing scoreAndRouteLead workflow scores and routes it as a hot lead."""
    url = os.environ.get("BASE44_ALERT_URL", "")
    token = os.environ.get("BASE44_INTERNAL_TOKEN", "")
    if not url or not token or "change-me" in token.lower():
        return False
    try:
        import requests
        # Reuse the vision ingest endpoint's auth channel with a lead payload
        r = requests.post(url, json={
            "internalToken": token,
            "source": "nexus-vision-signup",
            "title": f"Vision subscription: {row['company']} ({row['tier']})",
            "detail": f"{row['contact_name']} <{row['email']}> {row.get('phone','')} · {row['industry']} · {row['sites']} site(s) · {row.get('cameras') or '?'} cams · functions: {', '.join(json.loads(row['functions'])) or 'none picked'}",
            "detector": "signup",
            "severity": "info",
            "site": row["company"],
            "camera": "landing-page",
            "meta": {"tier": row["tier"], "subscription_id": row["id"]},
        }, timeout=15)
        return 200 <= r.status_code < 300
    except Exception:
        return False
