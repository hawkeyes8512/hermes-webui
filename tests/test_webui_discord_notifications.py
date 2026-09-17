from __future__ import annotations

import importlib
import json
import sqlite3
from pathlib import Path


MODULE = "api.webui_discord_notifications"


def load_module():
    return importlib.import_module(MODULE)


def test_all_sessions_enqueue_privacy_safe_terminal_notifications(tmp_path):
    mod = load_module()
    db = tmp_path / "notifications.db"
    store = mod.NotificationStore(db)

    store.record_terminal(
        session_id="session-a",
        run_id="run-a",
        event_name="done",
        payload={
            "session": {"messages": [{"content": "PRIVATE QUESTION"}]},
            "usage": {"duration_seconds": 12},
        },
        created_at=100.0,
    )
    store.record_terminal(
        session_id="session-b",
        run_id="run-b",
        event_name="apperror",
        payload={"message": "PRIVATE PROVIDER ERROR", "type": "error"},
        created_at=101.0,
    )

    rows = store.pending(now=200.0)
    assert [(r["session_id"], r["outcome"]) for r in rows] == [
        ("session-a", "completed"),
        ("session-b", "failed"),
    ]
    for row in rows:
        assert "PRIVATE" not in json.dumps(row, ensure_ascii=False)


def test_duplicate_terminal_event_is_idempotent_and_stream_end_is_not_duplicate(tmp_path):
    mod = load_module()
    store = mod.NotificationStore(tmp_path / "notifications.db")

    for event in ("done", "stream_end", "done"):
        store.record_terminal(
            session_id="same-session",
            run_id="same-run",
            event_name=event,
            payload={"session": {"messages": [{"content": "secret"}]}},
            created_at=100.0,
        )

    assert len(store.pending(now=200.0)) == 1


def test_failed_delivery_is_retried_and_success_is_marked(tmp_path):
    mod = load_module()
    store = mod.NotificationStore(tmp_path / "notifications.db")
    store.record_terminal(
        session_id="session-a",
        run_id="run-a",
        event_name="cancel",
        payload={},
        created_at=100.0,
    )
    [row] = store.pending(now=200.0)
    store.mark_failed(row["delivery_key"], now=200.0, retry_seconds=0)
    [retried] = store.pending(now=200.0)
    assert retried["attempts"] == 1
    store.mark_sent(retried["delivery_key"], sent_at=201.0)
    assert store.pending(now=300.0) == []


def test_outcome_message_has_no_session_or_content(tmp_path):
    mod = load_module()
    store = mod.NotificationStore(tmp_path / "notifications.db")
    store.record_terminal(
        session_id="private-session-id",
        run_id="private-run-id",
        event_name="error",
        payload={"content": "do not leak"},
        created_at=100.0,
    )
    [row] = store.pending(now=200.0)
    message = mod.message_for_outcome(row["outcome"])
    assert "失敗" in message
    assert "private-session-id" not in message
    assert "private-run-id" not in message
    assert "do not leak" not in message
