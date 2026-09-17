from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PANELS = ROOT / "static" / "panels.js"


def test_provider_settings_loads_all_supported_account_limits():
    source = PANELS.read_text(encoding="utf-8")

    assert "const _PROVIDER_LIMIT_IDS=Object.freeze(['openai-codex','anthropic','openrouter']);" in source
    assert "_fetchAllProviderQuotaStatuses(false)" in source
    assert "provider=${encodeURIComponent(providerId)}" in source


def test_each_provider_limit_card_refreshes_its_own_provider():
    source = PANELS.read_text(encoding="utf-8")

    assert "card.dataset.providerQuotaProvider=status.provider||'';" in source
    assert "_fetchProviderQuotaStatus(true,card.dataset.providerQuotaProvider||null)" in source
