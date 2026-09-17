"""Regression contracts for the WebUI session-switch performance path."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SESSIONS = (ROOT / "static" / "sessions.js").read_text(encoding="utf-8")
UI = (ROOT / "static" / "ui.js").read_text(encoding="utf-8")
WORKSPACE = (ROOT / "static" / "workspace.js").read_text(encoding="utf-8")
BOOT = (ROOT / "static" / "boot.js").read_text(encoding="utf-8")
ROUTES = (ROOT / "api" / "routes.py").read_text(encoding="utf-8")


def test_session_switch_records_fetch_dom_and_postprocess_stages():
    assert "_beginSessionSwitchPerf(sid)" in SESSIONS
    assert "_markSessionSwitchPerf('metadata-ready',sid)" in SESSIONS
    assert "_markSessionSwitchPerf('messages-ready',sid)" in SESSIONS
    assert "_markSessionSwitchPerf('dom-built',sid)" in UI
    assert "_finishSessionSwitchPerf('postprocess-ready',sid)" in UI


def test_collapsed_tool_details_are_materialized_only_when_opened():
    assert "data-tool-detail-deferred=\"1\"" in UI
    assert "function _materializeToolCardDetail" in UI
    assert "_materializeToolCardDetail(card)" in UI
    build_start = UI.index("function buildToolCard(tc)")
    build_end = UI.index("function _colorDiffLines", build_start)
    build_body = UI[build_start:build_end]
    assert "<div class=\"tool-card-detail\">" not in build_body


def test_cached_transcript_restore_runs_guarded_postprocessing():
    cache_start = UI.index("// Fast path: switching back to a previously rendered session")
    cache_end = UI.index("// Mid-stream flicker fix", cache_start)
    cache_branch = UI[cache_start:cache_end]
    assert "requestAnimationFrame" in cache_branch
    assert "_postProcessWithAnchorSuppression(inner)" in cache_branch
    assert "_finishSessionSwitchPerf('postprocess-ready',sid)" in cache_branch


def test_closed_workspace_panel_detaches_file_tree_and_rehydrates_on_open():
    assert "function suspendWorkspacePanelDom" in WORKSPACE
    assert "function resumeWorkspacePanelDom" in WORKSPACE
    assert "tree.replaceChildren()" in WORKSPACE
    assert "suspendWorkspacePanelDom()" in BOOT
    assert "resumeWorkspacePanelDom()" in BOOT


def test_session_route_diagnostics_name_business_stages():
    expected = (
        "session_loaded",
        "state_loaded",
        "model_resolved",
        "messages_windowed",
        "payload_built",
        "response_ready",
    )
    for stage in expected:
        assert f'_diag.stage("{stage}")' in ROUTES
