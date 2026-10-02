"""Grok OAuth billing integration, isolated from live credentials."""
import ast
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]

class GrokUsageTests(unittest.TestCase):
    def test_worker_and_quota_dispatch_support_grok(self):
        tree = ast.parse((ROOT / 'api/providers.py').read_text())
        ns = {}
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == '_ACCOUNT_USAGE_PROVIDERS' for t in node.targets):
                exec(compile(ast.Module(body=[node], type_ignores=[]), '<providers>', 'exec'), ns)
        self.assertIn('xai-oauth', ns['_ACCOUNT_USAGE_PROVIDERS'])
        source = (ROOT / 'api/providers.py').read_text()
        self.assertIn('Grok billing is a weekly usage meter', source)
        self.assertLess(source.index('if provider in _ACCOUNT_USAGE_PROVIDERS:'), source.index('local_snapshot = _local_pool_snapshot(provider)'))
        worker = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == '_ACCOUNT_USAGE_SUBPROCESS_CODE' for t in n.targets))
        worker = worker[:worker.index('if len(sys.argv) > 1')]
        env = {}
        exec(worker, env)
        with patch('api.grok_usage.fetch_grok_account_usage', return_value=None) as fetch:
            self.assertIsNone(env['_fetch_snapshot']('xai-oauth', None))
            fetch.assert_called_once_with()

if __name__ == '__main__':
    unittest.main()
