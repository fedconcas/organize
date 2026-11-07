"""Build-script regressions with fake Cargo; no network or real compilation."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TARGET = 'aarch64-apple-darwin'


class DesktopBuildTests(unittest.TestCase):
    def run_script(self, name, **flags):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scripts = root / 'scripts'
            scripts.mkdir()
            script = scripts / name
            script.write_bytes((ROOT / 'scripts' / name).read_bytes())
            fake_tools = root / 'tools'
            fake_tools.mkdir()
            stub = '''#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
root = pathlib.Path(os.environ['BUILD_TEST_ROOT'])
if pathlib.Path(sys.argv[0]).name == 'rustc':
    print('rustc 1.99.0' if args == ['--version'] else 'aarch64-apple-darwin')
    sys.exit(0)
with (root / 'calls.jsonl').open('a') as log:
    log.write(json.dumps(args) + '\\n')
if args[0] == 'fetch':
    sys.exit(int(os.environ.get('BUILD_TEST_FETCH_FAIL', '0')))
if args[0] == 'metadata':
    if '--no-deps' in args:
        print(json.dumps({'target_directory': str(root / 'target')}))
    else:
        if '--filter-platform' not in args:
            sys.exit('attempting to make an HTTP request, but --offline was specified')
        license_name = 'GPL-3.0-only' if os.environ.get('BUILD_TEST_GPL') else 'MIT'
        print(json.dumps({
            'packages': [
                {'id': 'host', 'name': 'organize-desktop', 'license': license_name},
                {'id': 'other-platform', 'name': 'unrelated', 'license': 'GPL-3.0-only'},
            ],
            'resolve': {'nodes': [{'id': 'host'}]},
        }))
'''
            for tool_name in ('cargo', 'rustc'):
                tool = fake_tools / tool_name
                tool.write_text(stub)
                tool.chmod(0o755)
            env = {**os.environ, 'PATH': str(fake_tools) + os.pathsep + os.environ['PATH'],
                   'BUILD_TEST_ROOT': str(root), **flags}
            result = subprocess.run(['bash', str(script)], env=env, capture_output=True, text=True)
            log = root / 'calls.jsonl'
            calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
            return result, calls

    def test_license_preparation_fetches_the_locked_host_graph(self):
        result, calls = self.run_script('prepare-license-deps.sh')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][:4], ['fetch', '--locked', '--target', TARGET])
        self.assertTrue(calls[0][-1].endswith('apps/desktop/src-tauri/Cargo.toml'))

    def test_license_preparation_stops_if_locked_dependencies_cannot_be_fetched(self):
        result, calls = self.run_script('prepare-license-deps.sh', BUILD_TEST_FETCH_FAIL='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(calls), 1)

    def test_removed_similar_photos_sidecar_is_not_built(self):
        package = json.loads((ROOT / 'apps/desktop/package.json').read_text())
        self.assertNotIn('build:similar', package['scripts'])
        self.assertFalse((ROOT / 'scripts/build-similar-sidecar.sh').exists())
        self.assertFalse((ROOT / 'sidecars/similar-photos').exists())

    def test_npm_prepares_cache_before_offline_license_generation(self):
        package = json.loads((ROOT / 'apps/desktop/package.json').read_text())
        steps = package['scripts']['build:licenses'].split(' && ')
        self.assertEqual(steps[0], 'bash ../../scripts/prepare-license-deps.sh')
        self.assertIn('generate-license-bundle.py', steps[1])


if __name__ == '__main__':
    unittest.main()
