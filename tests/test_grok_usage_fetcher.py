import unittest
from unittest.mock import patch
from api import grok_usage as plugin_api

class _Response:

    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

class _Client:

    def __init__(self, response, calls, **kwargs):
        self.response = response
        self.calls = calls
        self.kwargs = kwargs

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs, self.kwargs))
        return self.response

class GrokBillingTests(unittest.TestCase):
    _PERIOD_END = '2026-10-07T22:41:48.515769+00:00'

    def _fetch_payload(self, payload):
        calls = []
        with patch.object(plugin_api, 'resolve_xai_oauth_runtime_credentials', return_value={'api_key': 'test-access-token'}), patch.object(plugin_api.httpx, 'Client', side_effect=lambda **kwargs: _Client(_Response(payload), calls, **kwargs)):
            snapshot = plugin_api.fetch_grok_account_usage()
        return (snapshot, calls)

    def test_grok_billing_snapshot_reads_weekly_credit_usage(self):
        calls = []
        payload = {'config': {'creditUsagePercent': 7.0, 'currentPeriod': {'type': 'USAGE_PERIOD_TYPE_WEEKLY', 'end': '2026-10-07T22:41:48.515769+00:00'}}}
        with patch.object(plugin_api, 'resolve_xai_oauth_runtime_credentials', return_value={'api_key': 'test-access-token'}), patch.object(plugin_api.httpx, 'Client', side_effect=lambda **kwargs: _Client(_Response(payload), calls, **kwargs)):
            snapshot = plugin_api.fetch_grok_account_usage()
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.provider, 'xai-oauth')
        self.assertEqual(snapshot.source, 'billing_api')
        self.assertIsNone(snapshot.unavailable_reason)
        self.assertEqual(len(snapshot.windows), 1)
        self.assertEqual(snapshot.windows[0].label, 'Weekly')
        self.assertEqual(snapshot.windows[0].used_percent, 7.0)
        self.assertIsNotNone(snapshot.windows[0].reset_at)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], 'https://cli-chat-proxy.grok.com/v1/billing?format=credits')
        self.assertEqual(calls[0][1], {'headers': {'Authorization': 'Bearer test-access-token', 'Accept': 'application/json'}})
        self.assertFalse(calls[0][2]['follow_redirects'])
        self.assertGreater(calls[0][2]['timeout'], 0)

    def test_invalid_credit_usage_percent_is_unavailable(self):
        missing = object()
        for name, value in (('missing', missing), ('bool', True), ('false', False), ('nan', float('nan')), ('infinity', float('inf')), ('negative', -0.1), ('over_limit', 100.1), ('string', '7.0')):
            with self.subTest(name=name):
                config = {'currentPeriod': {'type': 'USAGE_PERIOD_TYPE_WEEKLY', 'end': self._PERIOD_END}}
                if value is not missing:
                    config['creditUsagePercent'] = value
                snapshot, _ = self._fetch_payload({'config': config})
                self.assertEqual(snapshot.windows, ())
                self.assertTrue(snapshot.unavailable_reason)

    def test_explicit_zero_is_valid_and_not_derived_from_on_demand(self):
        snapshot, _ = self._fetch_payload({'config': {'creditUsagePercent': 0, 'currentPeriod': {'type': 'USAGE_PERIOD_TYPE_WEEKLY', 'end': self._PERIOD_END}, 'onDemandCap': {'val': 0}, 'onDemandUsed': {'val': 0}}})
        self.assertEqual(snapshot.windows[0].used_percent, 0.0)
        snapshot, _ = self._fetch_payload({'config': {'currentPeriod': {'type': 'USAGE_PERIOD_TYPE_WEEKLY', 'end': self._PERIOD_END}, 'onDemandCap': {'val': 0}, 'onDemandUsed': {'val': 0}}})
        self.assertEqual(snapshot.windows, ())
        self.assertTrue(snapshot.unavailable_reason)

    def test_http_status_is_sanitized_without_response_body_or_token(self):
        calls = []
        secret = 'test-access-token'
        body_secret = 'raw-provider-error-and-token'
        response = _Response({'error': body_secret}, status_code=401)
        with patch.object(plugin_api, 'resolve_xai_oauth_runtime_credentials', return_value={'api_key': secret}), patch.object(plugin_api.httpx, 'Client', side_effect=lambda **kwargs: _Client(response, calls, **kwargs)):
            snapshot = plugin_api.fetch_grok_account_usage()
        self.assertEqual(snapshot.windows, ())
        self.assertIn('HTTP 401', snapshot.unavailable_reason)
        self.assertNotIn(secret, snapshot.unavailable_reason)
        self.assertNotIn(body_secret, snapshot.unavailable_reason)
        self.assertEqual(len(calls), 1)

    def test_missing_credentials_do_not_make_a_billing_request(self):
        resolver_calls = []
        with patch.object(plugin_api, 'resolve_xai_oauth_runtime_credentials', side_effect=lambda *args, **kwargs: resolver_calls.append((args, kwargs)) or {'api_key': ''}), patch.object(plugin_api.httpx, 'Client', side_effect=AssertionError('billing network call without credentials')):
            snapshot = plugin_api.fetch_grok_account_usage()
        self.assertEqual(resolver_calls, [((), {})])
        self.assertEqual(snapshot.windows, ())
        self.assertTrue(snapshot.unavailable_reason)

    def test_invalid_weekly_period_is_unavailable(self):
        for name, period in (('missing', None), ('wrong_type', {'type': 'USAGE_PERIOD_TYPE_DAILY', 'end': self._PERIOD_END}), ('missing_end', {'type': 'USAGE_PERIOD_TYPE_WEEKLY'}), ('naive_end', {'type': 'USAGE_PERIOD_TYPE_WEEKLY', 'end': '2026-10-07T22:41:48'}), ('malformed_end', {'type': 'USAGE_PERIOD_TYPE_WEEKLY', 'end': 'not-a-date'})):
            with self.subTest(name=name):
                config = {'creditUsagePercent': 7.0}
                if period is not None:
                    config['currentPeriod'] = period
                snapshot, _ = self._fetch_payload({'config': config})
                self.assertEqual(snapshot.windows, ())
                self.assertTrue(snapshot.unavailable_reason)