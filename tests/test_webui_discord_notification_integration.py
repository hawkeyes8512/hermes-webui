from __future__ import annotations

from pathlib import Path


WEBUI_ROOT = Path(__file__).resolve().parents[1]


def _function_source(path: Path, name: str) -> str:
    source = path.read_text(encoding="utf-8")
    marker = f"def {name}"
    start = source.index(marker)
    next_def = source.find("\ndef ", start + len(marker))
    return source[start:] if next_def < 0 else source[start:next_def]


def test_every_local_webui_terminal_callback_enqueues_global_notification():
    source = _function_source(WEBUI_ROOT / "api" / "streaming.py", "put")
    assert "record_webui_terminal_event" in source
    assert "event in ('done', 'cancel', 'apperror', 'error')" in source
    assert "stream_id=stream_id" in source


def test_gateway_webui_terminal_callback_enqueues_global_notification():
    source = _function_source(WEBUI_ROOT / "api" / "gateway_chat.py", "put_gateway_event")
    assert "record_webui_terminal_event" in source
    assert "event in (\"done\", \"cancel\", \"apperror\", \"error\")" in source
    assert "run_id=stream_id" in source
