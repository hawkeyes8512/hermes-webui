"""Privacy-preserving, durable WebUI completion notification outbox.

This module deliberately sits on the WebUI side of the boundary. It does not
use agent/plugin session state, and it never stores or formats conversation
content. WebUI workers enqueue a small outcome record; a separate process
sends the fixed-status message to Discord and retries failures.
"""
from __future__ import annotations

import logging
import os
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

TERMINAL_EVENTS = frozenset({"done", "cancel", "apperror", "error"})
DEFAULT_TARGET = "discord:1545823202415222894"
DEFAULT_POLL_SECONDS = 1.0


def _outcome_for_event(event_name: str, payload: Any) -> str | None:
    name = str(event_name or "").strip().lower()
    data = payload if isinstance(payload, dict) else {}
    error_type = str(data.get("type") or "").strip().lower()
    if name == "done":
        terminal_state = str(data.get("terminal_state") or "").strip().lower()
        return "failed" if terminal_state == "tool_limit_reached" else "completed"
    if name == "cancel":
        return "interrupted"
    if name in {"apperror", "error"}:
        if error_type in {"cancelled", "canceled", "interrupted"}:
            return "interrupted"
        return "failed"
    return None


def message_for_outcome(outcome: str) -> str:
    """Return a fixed message that contains no session/run/user data."""
    return {
        "completed": "✅ WebUIの作業が完了しました。\n内容はWebUIで確認してください。",
        "failed": "❌ WebUIの作業が失敗しました。\n内容はWebUIで確認してください。",
        "interrupted": "⏹️ WebUIの作業が中断されました。\n内容はWebUIで確認してください。",
    }.get(str(outcome), "⚠️ WebUIの作業状態を確認してください。\n内容はWebUIで確認してください。")


class NotificationStore:
    """SQLite-backed outbox shared by all WebUI sessions in one profile."""

    def __init__(self, db_path: str | os.PathLike[str]):
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS deliveries (
                    delivery_key TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    event_name TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    next_attempt_at REAL NOT NULL,
                    sent_at REAL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS deliveries_pending_idx "
                "ON deliveries(status, next_attempt_at, created_at)"
            )

    def record_terminal(
        self,
        *,
        session_id: str,
        run_id: str,
        event_name: str,
        payload: Any = None,
        created_at: float | None = None,
    ) -> bool:
        """Insert one terminal event; return False for non-terminal/duplicate."""
        name = str(event_name or "").strip().lower()
        if name not in TERMINAL_EVENTS:
            return False
        outcome = _outcome_for_event(name, payload)
        if outcome is None:
            return False
        sid = str(session_id or "").strip()
        rid = str(run_id or "").strip()
        if not sid or not rid:
            return False
        # One logical WebUI run gets one Discord message even if the transport
        # emits duplicate terminal frames or a later stream_end frame.
        delivery_key = f"{sid}:{rid}"
        ts = float(created_at if created_at is not None else time.time())
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO deliveries
                (delivery_key, session_id, run_id, event_name, outcome,
                 created_at, status, attempts, next_attempt_at)
                VALUES (?, ?, ?, ?, ?, ?, 'pending', 0, ?)
                """,
                (delivery_key, sid, rid, name, outcome, ts, ts),
            )
            return cur.rowcount == 1

    def pending(self, *, now: float | None = None, limit: int = 50) -> list[dict[str, Any]]:
        current = float(now if now is not None else time.time())
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT delivery_key, session_id, run_id, event_name, outcome,
                       created_at, attempts, next_attempt_at
                FROM deliveries
                WHERE status = 'pending' AND next_attempt_at <= ?
                ORDER BY created_at, delivery_key
                LIMIT ?
                """,
                (current, max(1, int(limit))),
            ).fetchall()
        return [dict(row) for row in rows]

    def mark_sent(self, delivery_key: str, *, sent_at: float | None = None) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE deliveries SET status='sent', sent_at=? "
                "WHERE delivery_key=? AND status='pending'",
                (float(sent_at if sent_at is not None else time.time()), delivery_key),
            )

    def mark_failed(
        self,
        delivery_key: str,
        *,
        now: float | None = None,
        retry_seconds: float = 5.0,
    ) -> None:
        current = float(now if now is not None else time.time())
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE deliveries
                SET attempts = attempts + 1,
                    next_attempt_at = ?
                WHERE delivery_key=? AND status='pending'
                """,
                (current + max(0.0, float(retry_seconds)), delivery_key),
            )

    def counts(self) -> dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS n FROM deliveries GROUP BY status"
            ).fetchall()
        result = {"pending": 0, "sent": 0}
        result.update({str(row["status"]): int(row["n"]) for row in rows})
        return result


def default_state_dir() -> Path:
    configured = str(os.environ.get("HERMES_WEBUI_STATE_DIR") or "").strip()
    return Path(configured).expanduser() if configured else Path.home() / ".hermes" / "webui"


def default_store() -> NotificationStore:
    return NotificationStore(default_state_dir() / "webui-discord-notifications.db")


def record_webui_terminal_event(
    *,
    session_id: str,
    run_id: str,
    event_name: str,
    payload: Any = None,
    created_at: float | None = None,
) -> bool:
    """Best-effort enqueue API used by every WebUI stream callback."""
    try:
        return default_store().record_terminal(
            session_id=session_id,
            run_id=run_id,
            event_name=event_name,
            payload=payload,
            created_at=created_at,
        )
    except Exception:
        # Notification failure must never fail the user's WebUI turn.
        logger.exception("Failed to enqueue WebUI completion notification")
        return False


def send_fixed_message(
    outcome: str,
    *,
    target: str | None = None,
    sender: Callable[[str], bool] | None = None,
) -> bool:
    """Send one fixed outcome message without exposing outbox metadata."""
    message = message_for_outcome(outcome)
    if sender is not None:
        return bool(sender(message))
    destination = str(target or os.environ.get("HERMES_WEBUI_DISCORD_TARGET") or DEFAULT_TARGET)
    hermes_bin = str(os.environ.get("HERMES_SEND_BIN") or "").strip() or "hermes"
    try:
        completed = subprocess.run(
            [hermes_bin, "send", "--to", destination, "--json", message],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
            check=False,
        )
    except Exception:
        logger.exception("Failed to invoke Hermes Discord sender")
        return False
    if completed.returncode != 0:
        logger.warning(
            "WebUI Discord notification failed (exit=%s): %s",
            completed.returncode,
            (completed.stderr or completed.stdout).strip()[:500],
        )
        return False
    return True


def deliver_pending(
    store: NotificationStore,
    *,
    sender: Callable[[str], bool] | None = None,
    now: float | None = None,
    retry_seconds: float = 5.0,
    limit: int = 50,
) -> dict[str, int]:
    rows = store.pending(now=now, limit=limit)
    sent = failed = 0
    for row in rows:
        ok = send_fixed_message(row["outcome"], sender=sender)
        if ok:
            store.mark_sent(row["delivery_key"], sent_at=now)
            sent += 1
        else:
            store.mark_failed(row["delivery_key"], now=now, retry_seconds=retry_seconds)
            failed += 1
    return {"examined": len(rows), "sent": sent, "failed": failed}


def run_forever(*, poll_seconds: float = DEFAULT_POLL_SECONDS) -> None:
    store = default_store()
    logger.info("WebUI Discord notification dispatcher started")
    while True:
        try:
            deliver_pending(store)
        except Exception:
            logger.exception("WebUI Discord notification dispatcher cycle failed")
        time.sleep(max(0.2, float(poll_seconds)))


if __name__ == "__main__":
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    run_forever()
