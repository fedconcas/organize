"""Verify the real macOS bundle, then stage stable-named GitHub release assets."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile
if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[1]
ASSET_NAME = 'Organize-macos-arm64.dmg'
privacy_spec = importlib.util.spec_from_file_location('privacy_audit', ROOT / 'scripts/check-release-privacy.py')
assert privacy_spec is not None and privacy_spec.loader is not None
privacy = importlib.util.module_from_spec(privacy_spec)
privacy_spec.loader.exec_module(privacy)


def validate_version(response, expected_core):
    if response.get('error') or response.get('id') != 'release-check':
        raise RuntimeError(f'Frozen engine RPC failed: {response}')
    result = response.get('result', {})
    if result.get('organize') != expected_core:
        raise RuntimeError(f'Unexpected organize core: {result}')
    return result


def main():
    desktop = ROOT / 'apps/desktop'
    config = json.loads((desktop / 'src-tauri/tauri.conf.json').read_text())
    bundle = desktop / 'src-tauri/target/release/bundle'
    app = bundle / 'macos/Organize.app'
    privacy_report = privacy.audit_app(app)
    info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
    if info['CFBundleShortVersionString'] != config['version']:
        raise RuntimeError('App/config version mismatch')
    subprocess.run(['codesign', '--verify', '--deep', '--strict', str(app)], check=True)
    engine = app / 'Contents/MacOS/organize-engine'
    arch = subprocess.check_output(['lipo', '-archs', str(engine)], text=True).strip()
    if arch != 'arm64':
        raise RuntimeError(f'Expected arm64 engine, got {arch}')
    executable = app / 'Contents/MacOS' / info['CFBundleExecutable']
    if subprocess.check_output(['lipo', '-archs', str(executable)], text=True).strip() != 'arm64':
        raise RuntimeError('Expected arm64 desktop executable')
    extra = sorted(p.name for p in (app / 'Contents/MacOS').iterdir() if p.name not in {info['CFBundleExecutable'], 'organize-engine'})
    if extra:
        raise RuntimeError(f'Unexpected executables in Contents/MacOS: {extra}')
    legal = app / 'Contents/Resources/legal'
    manifest = json.loads((legal / 'manifest.json').read_text())
    for filename, expected in manifest['files'].items():
        actual = hashlib.sha256((legal / filename).read_bytes()).hexdigest()
        if actual != expected:
            raise RuntimeError(f'Bundled legal resource checksum mismatch: {filename}')
    core = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']['version']
    bundled_core = next(p['version'] for p in manifest['components']
                if p['ecosystem'] == 'python' and p['name'] == 'organize-tool')
    if bundled_core != core:
        raise RuntimeError('Bundled core/source version mismatch')
    with tempfile.TemporaryDirectory(prefix='organize-release-check-') as temporary:
        result = subprocess.run([str(engine)], input=json.dumps({
            'id': 'release-check', 'method': 'app.version', 'params': {}}) + '\n',
            text=True, capture_output=True, check=True, timeout=30,
            env={**os.environ, 'ORGANIZE_GUI_DATA_DIR': temporary})
        responses = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
        version = validate_version(next(r for r in responses if r.get('id') == 'release-check'), core)
    dmg = bundle / 'dmg' / f'Organize_{config["version"]}_aarch64.dmg'
    subprocess.run(['hdiutil', 'verify', str(dmg)], check=True)
    output = ROOT / 'build/desktop-release'
    output.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(dmg, output / ASSET_NAME)
    digest = hashlib.sha256(dmg.read_bytes()).hexdigest()
    (output / 'SHA256SUMS.txt').write_text(f'{digest}  {ASSET_NAME}\n')
    (output / 'build-info.json').write_text(json.dumps({
        'appVersion': config['version'], 'engine': version,
        'commit': os.environ.get('GITHUB_SHA') or subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'workingTreeDirty': bool(subprocess.check_output(
            ['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip()),
        'architecture': 'arm64', 'minimumSupportedOS': 'macOS 14',
        'signing': 'ad-hoc', 'notarized': False,
        'asset': ASSET_NAME, 'sha256': digest,
    }, ensure_ascii=False, indent=2) + '\n')
    (output / 'privacy-audit.json').write_text(json.dumps(privacy_report, indent=2) + '\n')
    print(f'Verified release assets: {output}')


if __name__ == '__main__':
    main()
