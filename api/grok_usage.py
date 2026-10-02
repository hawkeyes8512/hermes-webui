"""Read-only Grok OAuth weekly usage; runs inside profile-isolated quota workers.

CLI-facing billing endpoint (not a guaranteed public API). Never infer zero
from absent creditUsagePercent, nor from the separate on-demand money meter.
"""
from __future__ import annotations
import math
from datetime import datetime, timezone
from typing import Any, Optional
import httpx
from agent.account_usage import AccountUsageSnapshot, AccountUsageWindow
from hermes_cli.auth_xai import resolve_xai_oauth_runtime_credentials

GROK_BILLING_URL = "https://cli-chat-proxy.grok.com/v1/billing?format=credits"
GROK_BILLING_TIMEOUT_S = 10.0
GROK_WEEKLY_PERIOD_TYPE = "USAGE_PERIOD_TYPE_WEEKLY"

def _grok_unavailable(reason: str) -> AccountUsageSnapshot:
    return AccountUsageSnapshot(
        provider="xai-oauth",
        source="billing_api",
        fetched_at=datetime.now(timezone.utc),
        title="Grok credits",
        unavailable_reason=reason,
    )


def _grok_usage_percent(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        percent = float(value)
    except (OverflowError, ValueError):
        return None
    return percent if math.isfinite(percent) and 0.0 <= percent <= 100.0 else None


def _grok_period_end(value: Any) -> Optional[datetime]:
    if not isinstance(value, dict) or value.get("type") != GROK_WEEKLY_PERIOD_TYPE:
        return None
    end = value.get("end")
    if not isinstance(end, str) or not end.strip():
        return None
    text = end.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def fetch_grok_account_usage() -> AccountUsageSnapshot:
    try:
        credentials = resolve_xai_oauth_runtime_credentials()
        token = str(credentials.get("api_key") or "").strip()
    except Exception:
        return _grok_unavailable("Grok billing credentials are unavailable.")
    if not token:
        return _grok_unavailable("Grok billing credentials are unavailable.")

    try:
        with httpx.Client(timeout=GROK_BILLING_TIMEOUT_S, follow_redirects=False) as client:
            response = client.get(
                GROK_BILLING_URL,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            )
    except Exception:
        return _grok_unavailable("Grok billing request failed.")

    status_code = getattr(response, "status_code", None)
    if not isinstance(status_code, int) or isinstance(status_code, bool) or not 100 <= status_code <= 599:
        return _grok_unavailable("Grok billing response was invalid.")
    if status_code < 200 or status_code >= 300:
        return _grok_unavailable(f"Grok billing endpoint returned HTTP {status_code}.")

    try:
        payload = response.json()
    except Exception:
        return _grok_unavailable("Grok billing response was invalid.")
    if not isinstance(payload, dict):
        return _grok_unavailable("Grok billing response was invalid.")
    config = payload.get("config")
    if not isinstance(config, dict):
        return _grok_unavailable("Grok billing response was invalid.")

    used_percent = _grok_usage_percent(config.get("creditUsagePercent"))
    if used_percent is None:
        return _grok_unavailable("Grok weekly usage is unavailable.")
    reset_at = _grok_period_end(config.get("currentPeriod"))
    if reset_at is None:
        return _grok_unavailable("Grok weekly billing period is unavailable.")

    return AccountUsageSnapshot(
        provider="xai-oauth",
        source="billing_api",
        fetched_at=datetime.now(timezone.utc),
        title="Grok credits",
        windows=(AccountUsageWindow(label="Weekly", used_percent=used_percent, reset_at=reset_at),),
    )
