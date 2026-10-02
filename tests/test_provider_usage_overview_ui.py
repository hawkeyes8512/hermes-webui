"""Node-backed behavior tests for the authenticated provider usage overview."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.js_source_extract import extract_function


ROOT = Path(__file__).resolve().parents[1]
PANELS_JS = (ROOT / "static" / "panels.js").read_text(encoding="utf-8")
NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="node is required for frontend behavior tests")
def test_load_providers_panel_fetches_quota_for_each_authenticated_provider_only():
    """Opening Providers must query one quota endpoint per authenticated provider."""
    fetch_source = extract_function(PANELS_JS, "_fetchProviderQuotaStatus", prefix="async function")
    load_source = extract_function(PANELS_JS, "loadProvidersPanel", prefix="async function")
    helper_source = "\n".join(
        extract_function(PANELS_JS, name)
        for name in (
            "_providerQuotaProviderIdentity",
            "_providerQuotaLoadingStatus",
            "_providerQuotaErrorStatus",
            "_isOpenRouterProvider",
        )
    )

    def quote_template_source(value: str) -> str:
        return value.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")

    fetch_source = quote_template_source(fetch_source)
    load_source = quote_template_source(load_source)
    helper_source = quote_template_source(helper_source)
    script = f"""
const providers = [
  {{ id: 'openrouter', display_name: 'OpenRouter', has_key: true, configurable: true }},
  {{ id: 'xai-oauth', display_name: 'Grok', has_key: true, is_oauth: true }},
  {{ id: 'openai-codex', display_name: 'Codex', has_key: true, is_oauth: true }},
  {{ id: 'gemini', display_name: 'Gemini', has_key: false, is_oauth: true }},
];
const quotaCalls = [];
const list = {{
  _children: [],
  style: {{}},
  get children() {{ return this._children; }},
  set innerHTML(value) {{ if (value === '') this._children = []; }},
  appendChild(node) {{ this._children.push(node); node.isConnected = true; return node; }},
}};
const empty = {{ style: {{}} }};

globalThis.$ = (id) => id === 'providersList' ? list : empty;
globalThis.t = (key) => key;
globalThis.esc = (value) => String(value ?? '');
globalThis.api = async (url) => {{
  if (url === '/api/providers') return {{ providers }};
  if (url.startsWith('/api/provider/quota')) {{
    quotaCalls.push(url);
    return {{ ok: true, status: 'available', provider: 'unexpected' }};
  }}
  throw new Error('unexpected endpoint: ' + url);
}};
globalThis._buildProviderQuotaCard = (status) => ({{
  kind: 'quota', status, dataset: {{}}, isConnected: true,
  replaceWith() {{ this.isConnected = false; }},
}});
globalThis._buildProviderCard = (provider) => ({{ kind: 'provider', provider, isConnected: true }});
globalThis.renderProviderCostChart = () => {{}};

eval(`
const _providerCardEls = new Map();
    let _providersPanelLoadSeq = 0;
const api = globalThis.api;
const $ = globalThis.$;
const t = globalThis.t;
const esc = globalThis.esc;
const _buildProviderQuotaCard = globalThis._buildProviderQuotaCard;
const _buildProviderCard = globalThis._buildProviderCard;
const renderProviderCostChart = globalThis.renderProviderCostChart;
{helper_source}
{fetch_source}
{load_source}
globalThis.__runLoadProvidersPanel = loadProvidersPanel;
`);

(async () => {{
  await globalThis.__runLoadProvidersPanel();
  process.stdout.write(JSON.stringify({{ quotaCalls }}));
}})().catch((error) => {{
  process.stderr.write(String(error && error.stack || error));
  process.exit(1);
}});
"""
    result = subprocess.run([NODE, "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert sorted(payload["quotaCalls"]) == [
        "/api/provider/quota?provider=openai-codex",
        "/api/provider/quota?provider=openrouter",
        "/api/provider/quota?provider=xai-oauth",
    ]


@pytest.mark.skipif(NODE is None, reason="node is required for frontend behavior tests")
def test_provider_quota_refresh_keeps_provider_identity_when_request_fails():
    """A failed card refresh must stay tied to the card's provider."""
    refresh_source = extract_function(PANELS_JS, "_refreshProviderQuota", prefix="async function")
    helper_source = "\n".join(
        extract_function(PANELS_JS, name)
        for name in ("_providerQuotaProviderIdentity", "_providerQuotaErrorStatus")
    )

    def quote_template_source(value: str) -> str:
        return value.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")

    refresh_source = quote_template_source(refresh_source)
    helper_source = quote_template_source(helper_source)
    script = f"""
const calls = [];
let built = null;
let replaced = null;
const card = {{
  dataset: {{ provider: 'xai-oauth', providerName: 'Grok' }},
  isConnected: true,
  replaceWith(next) {{ replaced = next; this.isConnected = false; }},
}};
const button = {{ disabled: false, textContent: 'Refresh', setAttribute() {{}}, removeAttribute() {{}} }};

globalThis.t = (key) => key;
globalThis.showToast = () => {{}};
globalThis._fetchProviderQuotaStatus = async (...args) => {{
  calls.push(args);
  throw new Error('quota timeout');
}};
globalThis._buildProviderQuotaCard = (status) => {{ built = status; return {{ status }}; }};
globalThis.renderProviderCostChart = () => {{}};

eval(`
const t = globalThis.t;
const showToast = globalThis.showToast;
const _fetchProviderQuotaStatus = globalThis._fetchProviderQuotaStatus;
const _buildProviderQuotaCard = globalThis._buildProviderQuotaCard;
const renderProviderCostChart = globalThis.renderProviderCostChart;
{helper_source}
{refresh_source}
globalThis.__runRefreshProviderQuota = _refreshProviderQuota;
`);

(async () => {{
  await globalThis.__runRefreshProviderQuota(card, button);
  process.stdout.write(JSON.stringify({{ calls, built, replaced }}));
}})().catch((error) => {{
  process.stderr.write(String(error && error.stack || error));
  process.exit(1);
}});
"""
    result = subprocess.run([NODE, "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["calls"] == [["xai-oauth", True]]
    assert payload["built"]["provider"] == "xai-oauth"
    assert payload["built"]["display_name"] == "Grok"
    assert payload["replaced"]["status"]["status"] == "failed"


@pytest.mark.skipif(NODE is None, reason="node is required for frontend behavior tests")
def test_provider_quota_card_stores_provider_identity_for_refresh():
    """Rendered quota cards must carry the provider slug used by refresh."""
    card_source = extract_function(PANELS_JS, "_buildProviderQuotaCard")
    helper_source = "\n".join(
        extract_function(PANELS_JS, name)
        for name in (
            "_formatProviderQuotaReset",
            "_formatProviderQuotaPercent",
            "_formatProviderQuotaMoney",
            "_formatProviderQuotaWindowLabel",
            "_formatProviderQuotaLastChecked",
            "_providerQuotaStateClass",
            "_providerQuotaStatusLabel",
            "_providerQuotaWindowMeta",
        )
    )

    def quote_template_source(value: str) -> str:
        return value.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")

    card_source = quote_template_source(card_source)
    helper_source = quote_template_source(helper_source)
    script = f"""
const refreshButton = {{ addEventListener() {{}} }};
const element = {{
  dataset: {{}},
  className: '',
  innerHTML: '',
  querySelector(selector) {{ return selector === '[data-provider-quota-refresh]' ? refreshButton : null; }},
}};
globalThis.document = {{ createElement: () => element }};
globalThis.t = (key) => key;
globalThis.esc = (value) => String(value ?? '');

eval(`
const document = globalThis.document;
const t = globalThis.t;
const esc = globalThis.esc;
{helper_source}
{card_source}
globalThis.__buildProviderQuotaCard = _buildProviderQuotaCard;
`);

const built = globalThis.__buildProviderQuotaCard({{
  ok: false,
  status: 'failed',
  provider: 'xai-oauth',
  display_name: 'Grok',
  quota: null,
  message: 'quota timeout',
}});
process.stdout.write(JSON.stringify({{ dataset: built.dataset }}));
"""
    result = subprocess.run([NODE, "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["dataset"] == {"provider": "xai-oauth", "providerName": "Grok"}


def test_provider_quota_overview_title_does_not_claim_active_provider():
    """The overview card title must not imply only the active provider is shown."""
    i18n = (ROOT / "static" / "i18n.js").read_text(encoding="utf-8")
    assert "provider_quota_title: 'Provider usage'" in i18n
    assert "provider_quota_title: 'プロバイダーの使用状況'" in i18n
    assert "provider_quota_title: 'Active provider quota'" not in i18n
    assert "provider_quota_title: 'アクティブなプロバイダーのクォータ'" not in i18n


@pytest.mark.skipif(NODE is None, reason="node is required for frontend behavior tests")
def test_provider_cost_chart_ignores_non_openrouter_cards():
    """The OpenRouter chart helper must never fetch for another provider."""
    chart_source = extract_function(PANELS_JS, "renderProviderCostChart", prefix="async function")
    router_source = extract_function(PANELS_JS, "_isOpenRouterProvider")

    def quote_template_source(value: str) -> str:
        return value.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")

    chart_source = quote_template_source(chart_source)
    router_source = quote_template_source(router_source)
    script = f"""
const calls = [];
globalThis.api = async (url) => {{ calls.push(url); return {{ ok: true, snapshots: [] }}; }};
globalThis._attachBudgetControls = () => {{}};
const card = {{ dataset: {{ provider: 'xai-oauth' }}, querySelector: () => null }};

eval(`
const api = globalThis.api;
const _attachBudgetControls = globalThis._attachBudgetControls;
{router_source}
{chart_source}
globalThis.__renderProviderCostChart = renderProviderCostChart;
`);
(async () => {{
  await globalThis.__renderProviderCostChart(card);
  process.stdout.write(JSON.stringify({{ calls }}));
}})().catch((error) => {{
  process.stderr.write(String(error && error.stack || error));
  process.exit(1);
}});
"""
    result = subprocess.run([NODE, "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["calls"] == []


@pytest.mark.skipif(NODE is None, reason="node is required for frontend behavior tests")
def test_provider_quota_loading_state_uses_localized_label():
    """Loading cards must expose a localized loading status, not raw "loading"."""
    label_source = extract_function(PANELS_JS, "_providerQuotaStatusLabel")
    state_source = extract_function(PANELS_JS, "_providerQuotaStateClass")

    def quote_template_source(value: str) -> str:
        return value.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")

    label_source = quote_template_source(label_source)
    state_source = quote_template_source(state_source)
    script = f"""
const t = (key) => key;
eval(`
const t = globalThis.__t || ((key) => key);
{state_source}
{label_source}
globalThis.__loadingLabel = _providerQuotaStatusLabel('loading');
`);
process.stdout.write(JSON.stringify({{ label: globalThis.__loadingLabel }}));
"""
    result = subprocess.run([NODE, "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["label"] == "provider_quota_refreshing"


@pytest.mark.skipif(NODE is None, reason="node is required for frontend behavior tests")
def test_authenticated_quota_cards_hide_empty_state_when_no_config_cards_exist():
    """Authenticated usage cards keep Providers visible even without editable cards."""
    fetch_source = extract_function(PANELS_JS, "_fetchProviderQuotaStatus", prefix="async function")
    load_source = extract_function(PANELS_JS, "loadProvidersPanel", prefix="async function")
    helper_source = "\n".join(
        extract_function(PANELS_JS, name)
        for name in (
            "_providerQuotaProviderIdentity",
            "_providerQuotaLoadingStatus",
            "_providerQuotaErrorStatus",
            "_isOpenRouterProvider",
        )
    )

    def quote_template_source(value: str) -> str:
        return value.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")

    fetch_source = quote_template_source(fetch_source)
    load_source = quote_template_source(load_source)
    helper_source = quote_template_source(helper_source)
    script = f"""
const list = {{
  _children: [],
  style: {{}},
  set innerHTML(value) {{ if (value === '') this._children = []; }},
  appendChild(node) {{ this._children.push(node); node.isConnected = true; }},
}};
const empty = {{ style: {{}} }};
globalThis.$ = (id) => id === 'providersList' ? list : empty;
globalThis.t = (key) => key;
globalThis.esc = (value) => String(value ?? '');
globalThis.api = async (url) => {{
  if (url === '/api/providers') return {{ providers: [{{ id: 'xai-oauth', display_name: 'Grok', has_key: true }}] }};
  if (url.startsWith('/api/provider/quota')) return {{ ok: false, status: 'unsupported', provider: 'xai-oauth' }};
  throw new Error('unexpected endpoint: ' + url);
}};
globalThis._buildProviderQuotaCard = (status) => ({{
  kind: 'quota', status, dataset: {{}}, isConnected: true,
  replaceWith() {{ this.isConnected = false; }},
}});
globalThis._buildProviderCard = () => ({{ kind: 'provider' }});
globalThis.renderProviderCostChart = () => {{}};

eval(`
const _providerCardEls = new Map();
let _providersPanelLoadSeq = 0;
const api = globalThis.api;
const $ = globalThis.$;
const t = globalThis.t;
const esc = globalThis.esc;
const _buildProviderQuotaCard = globalThis._buildProviderQuotaCard;
const _buildProviderCard = globalThis._buildProviderCard;
const renderProviderCostChart = globalThis.renderProviderCostChart;
{helper_source}
{fetch_source}
{load_source}
globalThis.__runLoadProvidersPanel = loadProvidersPanel;
`);
(async () => {{
  await globalThis.__runLoadProvidersPanel();
  process.stdout.write(JSON.stringify({{ emptyDisplay: empty.style.display, children: list._children.length }}));
}})().catch((error) => {{
  process.stderr.write(String(error && error.stack || error));
  process.exit(1);
}});
"""
    result = subprocess.run([NODE, "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"emptyDisplay": "none", "children": 1}


@pytest.mark.skipif(NODE is None, reason="node is required for frontend behavior tests")
def test_quota_results_render_independently_with_error_card_identity():
    """One failed quota request must not remove another provider's result."""
    fetch_source = extract_function(PANELS_JS, "_fetchProviderQuotaStatus", prefix="async function")
    load_source = extract_function(PANELS_JS, "loadProvidersPanel", prefix="async function")
    helper_source = "\n".join(
        extract_function(PANELS_JS, name)
        for name in (
            "_providerQuotaProviderIdentity",
            "_providerQuotaLoadingStatus",
            "_providerQuotaErrorStatus",
            "_isOpenRouterProvider",
        )
    )

    def quote_template_source(value: str) -> str:
        return value.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")

    fetch_source = quote_template_source(fetch_source)
    load_source = quote_template_source(load_source)
    helper_source = quote_template_source(helper_source)
    script = f"""
const providers = [
  {{ id: 'openrouter', display_name: 'OpenRouter', has_key: true, configurable: true }},
  {{ id: 'xai-oauth', display_name: 'Grok', has_key: true, is_oauth: true }},
  {{ id: 'openai-codex', display_name: 'Codex', has_key: false, is_oauth: true }},
];
const quotaCalls = [];
const pending = {{}};
const chartProviders = [];
const list = {{
  _children: [],
  style: {{}},
  set innerHTML(value) {{ if (value === '') this._children = []; }},
  appendChild(node) {{ this._children.push(node); node.isConnected = true; }},
}};
const empty = {{ style: {{}} }};
globalThis.$ = (id) => id === 'providersList' ? list : empty;
globalThis.t = (key) => key;
globalThis.esc = (value) => String(value ?? '');
globalThis.api = async (url) => {{
  if (url === '/api/providers') return {{ providers }};
  if (url.startsWith('/api/provider/quota')) {{
    const provider = new URL('http://localhost' + url).searchParams.get('provider');
    quotaCalls.push(provider);
    return new Promise((resolve, reject) => {{ pending[provider] = {{ resolve, reject }}; }});
  }}
  throw new Error('unexpected endpoint: ' + url);
}};
globalThis._buildProviderQuotaCard = (status) => ({{
  kind: 'quota', status, dataset: {{}}, isConnected: true,
  replaceWith(next) {{
    const index = list._children.indexOf(this);
    if (index >= 0) list._children[index] = next;
    this.isConnected = false;
    next.isConnected = true;
  }},
}});
globalThis._buildProviderCard = (provider) => ({{ kind: 'provider', provider }});
globalThis.renderProviderCostChart = (card) => chartProviders.push(card.status.provider);

eval(`
const _providerCardEls = new Map();
let _providersPanelLoadSeq = 0;
const api = globalThis.api;
const $ = globalThis.$;
const t = globalThis.t;
const esc = globalThis.esc;
const _buildProviderQuotaCard = globalThis._buildProviderQuotaCard;
const _buildProviderCard = globalThis._buildProviderCard;
const renderProviderCostChart = globalThis.renderProviderCostChart;
{helper_source}
{fetch_source}
{load_source}
globalThis.__runLoadProvidersPanel = loadProvidersPanel;
`);
(async () => {{
  const run = globalThis.__runLoadProvidersPanel();
  await new Promise((resolve) => setImmediate(resolve));
  const loading = list._children.filter((node) => node.kind === 'quota').map((node) => [node.status.provider, node.status.status]);
  pending['xai-oauth'].reject(new Error('Grok usage unavailable'));
  pending.openrouter.resolve({{ ok: true, status: 'available', provider: 'openrouter', display_name: 'OpenRouter' }});
  await run;
  const final = list._children.filter((node) => node.kind === 'quota').map((node) => ({{
    provider: node.status.provider,
    display_name: node.status.display_name,
    status: node.status.status,
  }})).sort((a, b) => a.provider.localeCompare(b.provider));
  process.stdout.write(JSON.stringify({{ quotaCalls, loading, final, chartProviders }}));
}})().catch((error) => {{
  process.stderr.write(String(error && error.stack || error));
  process.exit(1);
}});
"""
    result = subprocess.run([NODE, "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert sorted(payload["quotaCalls"]) == ["openrouter", "xai-oauth"]
    assert sorted(payload["loading"]) == [["openrouter", "loading"], ["xai-oauth", "loading"]]
    assert payload["final"] == [
        {"provider": "openrouter", "display_name": "OpenRouter", "status": "available"},
        {"provider": "xai-oauth", "display_name": "Grok", "status": "failed"},
    ]
    assert payload["chartProviders"] == ["openrouter"]


@pytest.mark.skipif(NODE is None, reason="node is required for frontend behavior tests")
def test_stale_provider_panel_load_cannot_overwrite_latest_profile():
    """A late response from an earlier panel load must be ignored."""
    fetch_source = extract_function(PANELS_JS, "_fetchProviderQuotaStatus", prefix="async function")
    load_source = extract_function(PANELS_JS, "loadProvidersPanel", prefix="async function")
    helper_source = "\n".join(
        extract_function(PANELS_JS, name)
        for name in (
            "_providerQuotaProviderIdentity",
            "_providerQuotaLoadingStatus",
            "_providerQuotaErrorStatus",
            "_isOpenRouterProvider",
        )
    )

    def quote_template_source(value: str) -> str:
        return value.replace("\\", "\\\\").replace("`", "\\`").replace("${", "\\${")

    fetch_source = quote_template_source(fetch_source)
    load_source = quote_template_source(load_source)
    helper_source = quote_template_source(helper_source)
    script = f"""
const providerResponses = [];
const list = {{
  _children: [],
  style: {{}},
  set innerHTML(value) {{ if (value === '') this._children = []; }},
  appendChild(node) {{ this._children.push(node); node.isConnected = true; }},
}};
const empty = {{ style: {{}} }};
globalThis.$ = (id) => id === 'providersList' ? list : empty;
globalThis.t = (key) => key;
globalThis.esc = (value) => String(value ?? '');
globalThis.api = async (url) => {{
  if (url === '/api/providers') return new Promise((resolve) => providerResponses.push(resolve));
  if (url.startsWith('/api/provider/quota')) {{
    const provider = new URL('http://localhost' + url).searchParams.get('provider');
    return {{ ok: true, status: 'available', provider, display_name: provider === 'xai-oauth' ? 'Latest Grok' : 'Old OpenRouter' }};
  }}
  throw new Error('unexpected endpoint: ' + url);
}};
globalThis._buildProviderQuotaCard = (status) => ({{
  kind: 'quota', status, dataset: {{}}, isConnected: true,
  replaceWith(next) {{
    const index = list._children.indexOf(this);
    if (index >= 0) list._children[index] = next;
    this.isConnected = false;
    next.isConnected = true;
  }},
}});
globalThis._buildProviderCard = (provider) => ({{ kind: 'provider', provider }});
globalThis.renderProviderCostChart = () => {{}};

eval(`
const _providerCardEls = new Map();
let _providersPanelLoadSeq = 0;
const api = globalThis.api;
const $ = globalThis.$;
const t = globalThis.t;
const esc = globalThis.esc;
const _buildProviderQuotaCard = globalThis._buildProviderQuotaCard;
const _buildProviderCard = globalThis._buildProviderCard;
const renderProviderCostChart = globalThis.renderProviderCostChart;
{helper_source}
{fetch_source}
{load_source}
globalThis.__runLoadProvidersPanel = loadProvidersPanel;
`);
(async () => {{
  const first = globalThis.__runLoadProvidersPanel();
  const second = globalThis.__runLoadProvidersPanel();
  providerResponses[1]({{ providers: [{{ id: 'xai-oauth', display_name: 'Latest Grok', has_key: true, is_oauth: true }}] }});
  await second;
  const afterLatest = list._children.filter((node) => node.kind === 'quota').map((node) => node.status.provider);
  providerResponses[0]({{ providers: [{{ id: 'openrouter', display_name: 'Old OpenRouter', has_key: true, configurable: true }}] }});
  await first;
  const final = list._children.filter((node) => node.kind === 'quota').map((node) => ({{
    provider: node.status.provider,
    display_name: node.status.display_name,
  }}));
  process.stdout.write(JSON.stringify({{ afterLatest, final }}));
}})().catch((error) => {{
  process.stderr.write(String(error && error.stack || error));
  process.exit(1);
}});
"""
    result = subprocess.run([NODE, "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {
        "afterLatest": ["xai-oauth"],
        "final": [{"provider": "xai-oauth", "display_name": "Latest Grok"}],
    }
