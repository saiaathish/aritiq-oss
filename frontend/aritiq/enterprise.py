"""
Minimal Phase 4 enterprise layer for Aritiq.

This module is deliberately outside ``aritiq/core``. It stores identity,
API-key, audit-history, watchlist, and webhook delivery state. It does not
verify financial claims and does not import any model SDK.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional


SCHEMA_VERSION = 1
DEFAULT_LIMIT_PER_MINUTE = 30
def _default_db_path() -> str:
    """Live enterprise/identity DB location.

    Deliberately kept OUT of the repo's read-only ``benchmark/reliability/cache``
    tree (which is often inside a synced folder): storing mutable state there let
    parallel sessions collide on one file. We use an XDG state dir, honoring
    ``XDG_STATE_HOME`` and falling back to ``~/.local/state/aritiq``.
    """
    base = os.environ.get("XDG_STATE_HOME") or os.path.join(
        os.path.expanduser("~"), ".local", "state"
    )
    return os.path.join(base, "aritiq", "enterprise.sqlite")


DEFAULT_DB_PATH = _default_db_path()


def db_path() -> str:
    return os.environ.get("ARITIQ_ENTERPRISE_DB", DEFAULT_DB_PATH)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: Optional[str] = None) -> sqlite3.Connection:
    path = path or db_path()
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    init_db(conn)
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS orgs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            org_id INTEGER NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
            email TEXT NOT NULL,
            name TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(org_id, email)
        );

        CREATE TABLE IF NOT EXISTS api_keys (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            org_id INTEGER NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
            user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            key_hash TEXT NOT NULL UNIQUE,
            key_prefix TEXT NOT NULL,
            label TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active',
            limit_per_minute INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            rotated_at TEXT,
            last_used_at TEXT
        );

        CREATE TABLE IF NOT EXISTS api_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            org_id INTEGER NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
            api_key_id INTEGER REFERENCES api_keys(id) ON DELETE SET NULL,
            method TEXT NOT NULL,
            path TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS audits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            org_id INTEGER NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
            user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            api_key_id INTEGER REFERENCES api_keys(id) ON DELETE SET NULL,
            ticker TEXT,
            source_label TEXT,
            score_json TEXT NOT NULL,
            verdict_counts_json TEXT NOT NULL,
            result_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS watchlists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            org_id INTEGER NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
            ticker TEXT NOT NULL,
            last_seen_accession TEXT,
            last_checked_at TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(org_id, ticker)
        );

        CREATE TABLE IF NOT EXISTS webhooks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            org_id INTEGER NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
            url TEXT NOT NULL,
            event_type TEXT NOT NULL DEFAULT 'filing_detected',
            secret TEXT,
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS webhook_deliveries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            org_id INTEGER NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
            webhook_id INTEGER NOT NULL REFERENCES webhooks(id) ON DELETE CASCADE,
            watchlist_id INTEGER REFERENCES watchlists(id) ON DELETE SET NULL,
            ticker TEXT NOT NULL,
            accession TEXT NOT NULL,
            event_type TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            status TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            next_attempt_at REAL NOT NULL DEFAULT 0,
            last_error TEXT,
            created_at TEXT NOT NULL,
            delivered_at TEXT
        );
        """
    )
    # Migration: per-user isolation for Supabase-authenticated users. Each
    # Supabase account gets its own org+user keyed by the token's `sub`.
    cols = {r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
    if "supabase_sub" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN supabase_sub TEXT")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_supabase_sub "
        "ON users(supabase_sub) WHERE supabase_sub IS NOT NULL"
    )
    conn.commit()


@dataclass(frozen=True)
class AuthContext:
    org_id: int
    user_id: Optional[int]
    api_key_id: Optional[int]
    api_key_prefix: str
    limit_per_minute: int
    source: str = "enterprise"

    def to_dict(self) -> dict:
        return {
            "org_id": self.org_id,
            "user_id": self.user_id,
            "api_key_id": self.api_key_id,
            "api_key_prefix": self.api_key_prefix,
            "limit_per_minute": self.limit_per_minute,
            "source": self.source,
        }


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_api_key() -> str:
    return "ariq_" + secrets.token_urlsafe(32)


def ensure_default_workspace(conn: sqlite3.Connection) -> AuthContext:
    row = conn.execute("SELECT id FROM orgs ORDER BY id LIMIT 1").fetchone()
    now = utc_now()
    if row:
        org_id = int(row["id"])
    else:
        cur = conn.execute(
            "INSERT INTO orgs(name, created_at) VALUES(?, ?)",
            ("Default workspace", now),
        )
        org_id = int(cur.lastrowid)
    user = conn.execute(
        "SELECT id FROM users WHERE org_id = ? ORDER BY id LIMIT 1", (org_id,)
    ).fetchone()
    if user:
        user_id = int(user["id"])
    else:
        cur = conn.execute(
            "INSERT OR IGNORE INTO users(org_id, email, name, created_at) VALUES(?, ?, ?, ?)",
            (org_id, "local@aritiq.dev", "Local user", now),
        )
        user_id = int(cur.lastrowid) if cur.lastrowid else int(
            conn.execute(
                "SELECT id FROM users WHERE org_id = ? ORDER BY id LIMIT 1",
                (org_id,),
            ).fetchone()["id"]
        )
    conn.commit()
    return AuthContext(
        org_id=org_id,
        user_id=user_id,
        api_key_id=None,
        api_key_prefix="legacy",
        limit_per_minute=DEFAULT_LIMIT_PER_MINUTE,
        source="legacy",
    )


def ensure_supabase_workspace(
    conn: sqlite3.Connection,
    sub: str,
    email: Optional[str] = None,
    name: Optional[str] = None,
) -> AuthContext:
    """Org + user for one Supabase account, keyed by the token's `sub`.

    Unlike ``ensure_default_workspace`` (a shared local-dev workspace), this
    isolates each signed-in user's audit history in their own org, so
    ``store_audit`` / ``list_audits`` never commingle users' data.
    """
    if not sub:
        raise ValueError("supabase sub is required")
    now = utc_now()
    row = conn.execute(
        "SELECT id, org_id FROM users WHERE supabase_sub = ?", (sub,)
    ).fetchone()
    if row:
        user_id, org_id = int(row["id"]), int(row["org_id"])
        if email:
            conn.execute(
                "UPDATE users SET email = ? WHERE id = ? AND email != ?",
                (email.strip().lower(), user_id, email.strip().lower()),
            )
    else:
        cur = conn.execute(
            "INSERT INTO orgs(name, created_at) VALUES(?, ?)",
            ((email or f"user-{sub[:8]}").strip().lower(), now),
        )
        org_id = int(cur.lastrowid)
        cur = conn.execute(
            "INSERT INTO users(org_id, email, name, created_at, supabase_sub) "
            "VALUES(?, ?, ?, ?, ?)",
            (
                org_id,
                (email or f"{sub}@supabase.local").strip().lower(),
                name,
                now,
                sub,
            ),
        )
        user_id = int(cur.lastrowid)
    conn.commit()
    return AuthContext(
        org_id=org_id,
        user_id=user_id,
        api_key_id=None,
        api_key_prefix="supabase",
        limit_per_minute=DEFAULT_LIMIT_PER_MINUTE,
        source="supabase",
    )


def create_workspace(
    org_name: str,
    user_email: str,
    *,
    user_name: Optional[str] = None,
    key_label: str = "Initial key",
    limit_per_minute: int = DEFAULT_LIMIT_PER_MINUTE,
    path: Optional[str] = None,
) -> dict:
    raw_key = generate_api_key()
    now = utc_now()
    with connect(path) as conn:
        cur = conn.execute(
            "INSERT INTO orgs(name, created_at) VALUES(?, ?)",
            (org_name.strip() or "Aritiq workspace", now),
        )
        org_id = int(cur.lastrowid)
        cur = conn.execute(
            "INSERT INTO users(org_id, email, name, created_at) VALUES(?, ?, ?, ?)",
            (org_id, user_email.strip().lower(), user_name, now),
        )
        user_id = int(cur.lastrowid)
        api_key = insert_api_key(
            conn,
            org_id=org_id,
            user_id=user_id,
            label=key_label,
            limit_per_minute=limit_per_minute,
            raw_key=raw_key,
        )
        conn.commit()
        return {
            "org": {"id": org_id, "name": org_name.strip() or "Aritiq workspace"},
            "user": {"id": user_id, "email": user_email.strip().lower(), "name": user_name},
            "api_key": api_key | {"key": raw_key},
        }


def insert_api_key(
    conn: sqlite3.Connection,
    *,
    org_id: int,
    user_id: Optional[int],
    label: str,
    limit_per_minute: int,
    raw_key: Optional[str] = None,
) -> dict:
    raw_key = raw_key or generate_api_key()
    now = utc_now()
    prefix = raw_key[:12]
    cur = conn.execute(
        """
        INSERT INTO api_keys(
            org_id, user_id, key_hash, key_prefix, label, status,
            limit_per_minute, created_at
        )
        VALUES(?, ?, ?, ?, ?, 'active', ?, ?)
        """,
        (
            org_id,
            user_id,
            hash_key(raw_key),
            prefix,
            label.strip() or "API key",
            int(limit_per_minute or DEFAULT_LIMIT_PER_MINUTE),
            now,
        ),
    )
    return {
        "id": int(cur.lastrowid),
        "org_id": org_id,
        "user_id": user_id,
        "key_prefix": prefix,
        "label": label.strip() or "API key",
        "status": "active",
        "limit_per_minute": int(limit_per_minute or DEFAULT_LIMIT_PER_MINUTE),
        "created_at": now,
        "rotated_at": None,
        "last_used_at": None,
    }


def authenticate(raw_key: Optional[str], *, path: Optional[str] = None) -> Optional[AuthContext]:
    if not raw_key:
        return None
    with connect(path) as conn:
        row = conn.execute(
            """
            SELECT id, org_id, user_id, key_prefix, limit_per_minute
            FROM api_keys
            WHERE key_hash = ? AND status = 'active'
            """,
            (hash_key(raw_key),),
        ).fetchone()
        if not row:
            return None
        now = utc_now()
        conn.execute("UPDATE api_keys SET last_used_at = ? WHERE id = ?", (now, row["id"]))
        conn.commit()
        return AuthContext(
            org_id=int(row["org_id"]),
            user_id=int(row["user_id"]) if row["user_id"] is not None else None,
            api_key_id=int(row["id"]),
            api_key_prefix=str(row["key_prefix"]),
            limit_per_minute=int(row["limit_per_minute"]),
            source="enterprise",
        )


def record_usage(ctx: AuthContext, method: str, path_value: str, *, path: Optional[str] = None) -> None:
    if ctx.api_key_id is None:
        return
    with connect(path) as conn:
        conn.execute(
            "INSERT INTO api_usage(org_id, api_key_id, method, path, created_at) VALUES(?, ?, ?, ?, ?)",
            (ctx.org_id, ctx.api_key_id, method, path_value, utc_now()),
        )
        conn.commit()


def list_api_keys(org_id: int, *, path: Optional[str] = None) -> list[dict]:
    with connect(path) as conn:
        rows = conn.execute(
            """
            SELECT id, org_id, user_id, key_prefix, label, status,
                   limit_per_minute, created_at, rotated_at, last_used_at
            FROM api_keys
            WHERE org_id = ?
            ORDER BY id
            """,
            (org_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def create_api_key(
    org_id: int,
    *,
    user_id: Optional[int],
    label: str,
    limit_per_minute: int,
    path: Optional[str] = None,
) -> dict:
    raw_key = generate_api_key()
    with connect(path) as conn:
        data = insert_api_key(
            conn,
            org_id=org_id,
            user_id=user_id,
            label=label,
            limit_per_minute=limit_per_minute,
            raw_key=raw_key,
        )
        conn.commit()
        return data | {"key": raw_key}


def rotate_api_key(key_id: int, org_id: int, *, path: Optional[str] = None) -> dict:
    raw_key = generate_api_key()
    with connect(path) as conn:
        old = conn.execute(
            "SELECT user_id, label, limit_per_minute FROM api_keys WHERE id = ? AND org_id = ?",
            (key_id, org_id),
        ).fetchone()
        if not old:
            raise KeyError("api key not found")
        now = utc_now()
        conn.execute(
            "UPDATE api_keys SET status = 'rotated', rotated_at = ? WHERE id = ?",
            (now, key_id),
        )
        data = insert_api_key(
            conn,
            org_id=org_id,
            user_id=int(old["user_id"]) if old["user_id"] is not None else None,
            label=f"{old['label']} (rotated)",
            limit_per_minute=int(old["limit_per_minute"]),
            raw_key=raw_key,
        )
        conn.commit()
        return data | {"key": raw_key, "rotated_from": key_id}


def deactivate_api_key(key_id: int, org_id: int, *, path: Optional[str] = None) -> None:
    with connect(path) as conn:
        cur = conn.execute(
            "UPDATE api_keys SET status = 'disabled' WHERE id = ? AND org_id = ?",
            (key_id, org_id),
        )
        if cur.rowcount == 0:
            raise KeyError("api key not found")
        conn.commit()


def api_key_dashboard(org_id: int, *, path: Optional[str] = None) -> dict:
    keys = list_api_keys(org_id, path=path)
    with connect(path) as conn:
        usage_rows = conn.execute(
            """
            SELECT api_key_id, COUNT(*) AS calls, MAX(created_at) AS last_call_at
            FROM api_usage
            WHERE org_id = ?
            GROUP BY api_key_id
            """,
            (org_id,),
        ).fetchall()
    usage = {int(r["api_key_id"]): dict(r) for r in usage_rows}
    out = []
    for key in keys:
        u = usage.get(int(key["id"]), {})
        out.append(key | {"usage": {"calls": int(u.get("calls") or 0), "last_call_at": u.get("last_call_at")}})
    return {"org_id": org_id, "api_keys": out}


def _verdict_counts(audit_payload: dict) -> dict:
    counts: dict[str, int] = {}
    for item in audit_payload.get("results", []):
        status = item.get("status") or "UNKNOWN"
        counts[status] = counts.get(status, 0) + 1
    for item in audit_payload.get("conflicts", []):
        status = item.get("status") or "CONFLICT"
        counts[status] = counts.get(status, 0) + 1
    return counts


def store_audit(
    ctx: AuthContext,
    audit_payload: dict,
    *,
    ticker: Optional[str] = None,
    source_label: Optional[str] = None,
    path: Optional[str] = None,
) -> int:
    with connect(path) as conn:
        cur = conn.execute(
            """
            INSERT INTO audits(
                org_id, user_id, api_key_id, ticker, source_label,
                score_json, verdict_counts_json, result_json, created_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ctx.org_id,
                ctx.user_id,
                ctx.api_key_id,
                ticker.upper() if ticker else None,
                source_label,
                json.dumps(audit_payload.get("score") or {}, sort_keys=True),
                json.dumps(_verdict_counts(audit_payload), sort_keys=True),
                json.dumps(audit_payload, sort_keys=True),
                utc_now(),
            ),
        )
        conn.commit()
        return int(cur.lastrowid)


def list_audits(org_id: int, *, limit: int = 50, path: Optional[str] = None) -> list[dict]:
    with connect(path) as conn:
        rows = conn.execute(
            """
            SELECT id, ticker, source_label, score_json, verdict_counts_json, created_at
            FROM audits
            WHERE org_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (org_id, int(limit)),
        ).fetchall()
        return [
            dict(r)
            | {
                "score": json.loads(r["score_json"]),
                "verdict_counts": json.loads(r["verdict_counts_json"]),
            }
            for r in rows
        ]


def get_audit(org_id: int, audit_id: int, *, path: Optional[str] = None) -> Optional[dict]:
    with connect(path) as conn:
        row = conn.execute(
            """
            SELECT id, ticker, source_label, score_json, verdict_counts_json,
                   result_json, created_at
            FROM audits
            WHERE org_id = ? AND id = ?
            """,
            (org_id, audit_id),
        ).fetchone()
        if not row:
            return None
        return dict(row) | {
            "score": json.loads(row["score_json"]),
            "verdict_counts": json.loads(row["verdict_counts_json"]),
            "result": json.loads(row["result_json"]),
        }


def add_watchlist(org_id: int, ticker: str, *, path: Optional[str] = None) -> dict:
    ticker = ticker.strip().upper()
    now = utc_now()
    with connect(path) as conn:
        conn.execute(
            """
            INSERT INTO watchlists(org_id, ticker, created_at)
            VALUES(?, ?, ?)
            ON CONFLICT(org_id, ticker) DO NOTHING
            """,
            (org_id, ticker, now),
        )
        row = conn.execute(
            "SELECT * FROM watchlists WHERE org_id = ? AND ticker = ?",
            (org_id, ticker),
        ).fetchone()
        conn.commit()
        return dict(row)


def list_watchlists(org_id: int, *, path: Optional[str] = None) -> list[dict]:
    with connect(path) as conn:
        rows = conn.execute(
            "SELECT * FROM watchlists WHERE org_id = ? ORDER BY ticker",
            (org_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def update_watchlist_seen(
    org_id: int,
    watchlist_id: int,
    accession: Optional[str],
    *,
    path: Optional[str] = None,
) -> None:
    with connect(path) as conn:
        conn.execute(
            """
            UPDATE watchlists
            SET last_seen_accession = ?, last_checked_at = ?
            WHERE org_id = ? AND id = ?
            """,
            (accession, utc_now(), org_id, watchlist_id),
        )
        conn.commit()


def add_webhook(org_id: int, url: str, *, secret: Optional[str] = None, path: Optional[str] = None) -> dict:
    with connect(path) as conn:
        cur = conn.execute(
            """
            INSERT INTO webhooks(org_id, url, secret, active, event_type, created_at)
            VALUES(?, ?, ?, 1, 'filing_detected', ?)
            """,
            (org_id, url.strip(), secret, utc_now()),
        )
        conn.commit()
        return dict(
            conn.execute(
                "SELECT id, org_id, url, event_type, active, created_at FROM webhooks WHERE id = ?",
                (cur.lastrowid,),
            ).fetchone()
        )


def list_webhooks(org_id: int, *, path: Optional[str] = None) -> list[dict]:
    with connect(path) as conn:
        rows = conn.execute(
            "SELECT id, org_id, url, event_type, active, created_at FROM webhooks WHERE org_id = ? ORDER BY id",
            (org_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def enqueue_webhook_deliveries(
    org_id: int,
    *,
    watchlist_id: int,
    ticker: str,
    accession: str,
    filing: dict,
    path: Optional[str] = None,
) -> int:
    payload = {
        "event": "filing_detected",
        "ticker": ticker,
        "accession": accession,
        "filing": filing,
    }
    with connect(path) as conn:
        hooks = conn.execute(
            "SELECT id FROM webhooks WHERE org_id = ? AND active = 1 AND event_type = 'filing_detected'",
            (org_id,),
        ).fetchall()
        for hook in hooks:
            conn.execute(
                """
                INSERT INTO webhook_deliveries(
                    org_id, webhook_id, watchlist_id, ticker, accession,
                    event_type, payload_json, status, next_attempt_at, created_at
                )
                VALUES(?, ?, ?, ?, ?, 'filing_detected', ?, 'pending', ?, ?)
                """,
                (
                    org_id,
                    int(hook["id"]),
                    watchlist_id,
                    ticker,
                    accession,
                    json.dumps(payload, sort_keys=True),
                    time.time(),
                    utc_now(),
                ),
            )
        conn.commit()
        return len(hooks)


def dispatch_due_webhooks(
    org_id: int,
    *,
    deliver: Optional[Callable[[str, dict], None]] = None,
    max_deliveries: int = 25,
    path: Optional[str] = None,
) -> dict:
    deliver = deliver or _post_json
    now = time.time()
    sent = failed = 0
    with connect(path) as conn:
        rows = conn.execute(
            """
            SELECT d.*, w.url
            FROM webhook_deliveries d
            JOIN webhooks w ON w.id = d.webhook_id
            WHERE d.org_id = ?
              AND d.status IN ('pending', 'retry')
              AND d.next_attempt_at <= ?
            ORDER BY d.id
            LIMIT ?
            """,
            (org_id, now, int(max_deliveries)),
        ).fetchall()
        for row in rows:
            payload = json.loads(row["payload_json"])
            try:
                deliver(row["url"], payload)
            except Exception as exc:  # pragma: no cover - exact network errors vary
                attempts = int(row["attempts"]) + 1
                delay = min(3600, 2 ** attempts)
                status = "failed" if attempts >= 5 else "retry"
                conn.execute(
                    """
                    UPDATE webhook_deliveries
                    SET attempts = ?, status = ?, next_attempt_at = ?, last_error = ?
                    WHERE id = ?
                    """,
                    (attempts, status, time.time() + delay, str(exc)[:500], row["id"]),
                )
                failed += 1
            else:
                conn.execute(
                    """
                    UPDATE webhook_deliveries
                    SET attempts = attempts + 1, status = 'delivered',
                        delivered_at = ?, last_error = NULL
                    WHERE id = ?
                    """,
                    (utc_now(), row["id"]),
                )
                sent += 1
        conn.commit()
    return {"delivered": sent, "failed_or_retrying": failed}


def _post_json(url: str, payload: dict) -> None:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "Aritiq-webhook/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status >= 400:
                raise RuntimeError(f"HTTP {resp.status}")
    except urllib.error.URLError as exc:
        raise RuntimeError(str(exc)) from exc

