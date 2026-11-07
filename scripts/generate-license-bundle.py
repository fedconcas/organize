#!/usr/bin/env python3
"""Build offline distribution notices from the actual installed dependency graph.

No network calls. Missing notices or mismatched MPL archives fail the release.
Run with the Python interpreter used by the sidecar build.
"""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[1]
DESKTOP = ROOT / 'apps/desktop'
LEGAL = ROOT / 'legal'
MPL = {'option-ext', 'selectors', 'cssparser', 'cssparser-macros', 'dtoa-short'}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def license_name(name):
    return name.lower().startswith(('license', 'licence', 'notice', 'copying', 'unlicense'))


def notice_files(directory):
    result = [p for p in directory.iterdir() if p.is_file() and license_name(p.name)]
    for name in ('licenses', 'LICENSES'):
        folder = directory / name
        if folder.is_dir():
            result.extend(p for p in folder.rglob('*') if p.is_file())
    return sorted(set(result))


def record_file(name, data, source):
    return {'name': name, 'text': data.decode('utf-8'), 'sha256': sha(data), 'source': source}


def fallback_files(ecosystem, name, version):
    entries = json.loads((LEGAL / 'upstream.json').read_text())
    key = f'{ecosystem}:{name}@{version}'
    if key not in entries:
        raise RuntimeError(f'Missing license files: {key}. Review and cache upstream notices first.')
    output = []
    for entry in entries[key]:
        path = LEGAL / entry['file']
        data = path.read_bytes()
        if sha(data) != entry['sha256']:
            raise RuntimeError(f'Upstream notice checksum mismatch: {path}')
        output.append(record_file(path.name, data, entry['source']))
    return output


def component(ecosystem, name, version, license_id, files, source, scope):
    return {'ecosystem': ecosystem, 'name': name, 'version': version,
            'license': license_id or 'See original license text', 'source': source,
            'scope': scope, 'files': files}


def _copyleft_only(token):
    name = token.strip().upper()
    if name.startswith('LGPL'):
        return False
    return name.startswith(('GPL', 'AGPL'))


def forbidden_license(name, license):
    """Refuse krokiet and expressions that can only be satisfied by GPL or AGPL.

    ``Apache-2.0 OR GPL-2.0-only`` stays allowed: the app uses the Apache-2.0 side.
    """
    if name == 'krokiet':
        return True
    expression = license.replace('(', ' ').replace(')', ' ')
    for clause in re.split(r'\bAND\b', expression):
        options = [option for option in re.split(r'\bOR\b', clause) if option.strip()]
        if options and all(_copyleft_only(option) for option in options):
            return True
    return False


def cargo_components(target, manifest_dir=None, scope='target graph (runtime + build)'):
    manifest_dir = Path(manifest_dir or (DESKTOP / 'src-tauri'))
    locked = tomllib.loads((manifest_dir / 'Cargo.lock').read_text())
    checksums = {(p['name'], p['version']): p.get('checksum') for p in locked['package']}
    raw = subprocess.check_output(['cargo', 'metadata', '--format-version', '1', '--locked',
                                   '--offline', '--filter-platform', target], cwd=manifest_dir)
    metadata = json.loads(raw)
    nodes = {n['id']: n for n in metadata['resolve']['nodes']}
    seen, todo = set(), [metadata['resolve']['root']]
    while todo:
        current = todo.pop()
        if current in seen:
            continue
        seen.add(current)
        todo.extend(dep['pkg'] for dep in nodes[current]['deps'])
    output, mpl = [], []
    for p in metadata['packages']:
        if p['id'] not in seen or not p['source']:
            continue
        directory = Path(p['manifest_path']).parent
        files = [record_file(f.name, f.read_bytes(), 'Published Cargo crate')
                 for f in notice_files(directory)]
        if p.get('license_file'):
            f = directory / p['license_file']
            if f.is_file() and not any(v['name'] == f.name for v in files):
                files.append(record_file(f.name, f.read_bytes(), 'Published Cargo crate'))
        if not files:
            files = fallback_files('rust', p['name'], p['version'])
        if forbidden_license(p['name'], p.get('license') or ''):
            raise RuntimeError(f'Refusing GPL crate in the bundled graph: {p["name"]} ({p.get("license")})')
        output.append(component('rust', p['name'], p['version'], p.get('license'), files,
                                p.get('repository') or p['source'], scope))
        if 'MPL' in (p.get('license') or ''):
            if p['name'] not in MPL:
                raise RuntimeError(f'New MPL component needs source review: {p["name"]}')
            archive = directory.parents[1].parent / 'cache' / directory.parent.name / f'{directory.name}.crate'
            data = archive.read_bytes()
            expected = checksums[(p['name'], p['version'])]
            if sha(data) != expected:
                raise RuntimeError(f'MPL crate checksum mismatch: {archive}')
            # Verify local sources match the unmodified published crate, not only the cached archive.
            published = set()
            with tarfile.open(archive, 'r:gz') as source:
                for member in source.getmembers():
                    if not member.isfile():
                        continue
                    relative = Path(member.name).relative_to(directory.name)
                    if '..' in relative.parts:
                        raise RuntimeError('Unsafe crate source path')
                    published.add(relative)
                    if source.extractfile(member).read() != (directory / relative).read_bytes():
                        raise RuntimeError(f'MPL source modified: {directory / relative}. Provide modified sources.')
            local = {p.relative_to(directory) for p in directory.rglob('*') if p.is_file()
                     and p.name not in ('.cargo-ok', '.cargo-checksum.json')}
            if local != published:
                raise RuntimeError(f'MPL source file inventory modified: {directory}')
            mpl.append({'name': p['name'], 'version': p['version'], 'sha256': expected,
                        'source': f'https://crates.io/api/v1/crates/{p["name"]}/{p["version"]}/download',
                        'path': archive})
    return output, sorted(mpl, key=lambda p: p['name'])


def npm_components():
    lock = json.loads((DESKTOP / 'package-lock.json').read_text())
    output = []
    for path, entry in lock['packages'].items():
        if not path:
            continue
        directory = DESKTOP / path
        if not directory.is_dir():
            if entry.get('optional'):
                continue
            raise RuntimeError(f'Install locked npm dependency first: {path}')
        package = json.loads((directory / 'package.json').read_text())
        if package['version'] != entry['version']:
            raise RuntimeError(f'npm installed/lock version mismatch: {path}')
        name = package['name']
        files = [record_file(str(f.relative_to(directory)), f.read_bytes(), 'Installed locked npm package')
                 for f in notice_files(directory)]
        native_parents = {'@esbuild/darwin-arm64': 'esbuild', '@rollup/rollup-darwin-arm64': 'rollup',
                          '@tauri-apps/cli-darwin-arm64': '@tauri-apps/cli'}
        if not files and name in native_parents:
            parent = DESKTOP / 'node_modules' / native_parents[name]
            parent_package = json.loads((parent / 'package.json').read_text())
            if parent_package['version'] != entry['version']:
                raise RuntimeError(f'Native npm package/parent version mismatch: {name}')
            files = [record_file(f.name, f.read_bytes(), f'Same-version {parent_package["name"]} package license')
                     for f in notice_files(parent)]
        if not files:
            files = fallback_files('npm', name, entry['version'])
        repository = package.get('repository') or entry.get('resolved', '')
        if isinstance(repository, dict):
            repository = repository.get('url', '')
        output.append(component('npm', name, entry['version'], entry.get('license'), files,
                                repository, 'build tool' if entry.get('dev') else 'frontend dependency'))
    return output


def python_components():
    output, inventory = [], []
    for dist in importlib.metadata.distributions():
        name, version = dist.metadata['Name'], dist.version
        inventory.append({'name': name, 'version': version})
        files = []
        for file in sorted(dist.files or [], key=str):
            # Skip debug-symbol bundles and compiled modules that merely share a license-like name.
            if any(part.endswith('.dSYM') for part in Path(file).parts) or Path(file).suffix in {'.so', '.pyc', '.dylib'}:
                continue
            if license_name(Path(file).name):
                path = Path(dist.locate_file(file))
                if path.is_file():
                    files.append(record_file(str(file), path.read_bytes(), 'Sidecar Python environment'))
        if not files:
            files = fallback_files('python', name, version)
        license_id = dist.metadata.get('License-Expression') or dist.metadata.get('License', '')
        if not license_id or len(license_id) > 100 or license_id == 'UNKNOWN':
            license_id = 'See original license text'
        output.append(component('python', name, version, license_id, files,
                                dist.metadata.get('Home-page') or '\n'.join(dist.metadata.get_all('Project-URL') or []),
                                'sidecar environment (runtime + build tools)'))
    candidates = [Path(sys.base_prefix) / f'lib/python{sys.version_info.major}.{sys.version_info.minor}/LICENSE.txt',
                  Path(sys.base_prefix) / 'LICENSE.txt']
    license_path = next((p for p in candidates if p.is_file()), None)
    if not license_path:
        raise RuntimeError('Missing license for the actual bundled Python interpreter')
    output.append(component('python', 'CPython', platform.python_version(), 'PSF + incorporated licenses',
                            [record_file('LICENSE.txt', license_path.read_bytes(), 'Bundled interpreter standard library')],
                            'https://www.python.org/', 'bundled runtime'))
    # cryptography wheels embed OpenSSL outside Python distribution metadata.
    # Check the actual library version, not the system openssl executable.
    from cryptography.hazmat.backends.openssl.backend import backend
    openssl_version = backend.openssl_version_text().split()[1]
    output.append(component('native', 'OpenSSL', openssl_version, 'Apache-2.0',
                            fallback_files('native', 'OpenSSL', openssl_version),
                            'https://github.com/openssl/openssl', 'embedded in cryptography wheel'))
    return output, sorted(inventory, key=lambda p: p['name'].lower())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target')
    args = parser.parse_args()
    target = args.target or subprocess.check_output(['rustc', '--print', 'host-tuple'], text=True).strip()
    rust, mpl = cargo_components(target)
    python, python_inventory = python_components()
    components = sorted(npm_components() + rust + python,
                        key=lambda p: (p['ecosystem'], p['name'].lower(), p['version']))
    mit = (ROOT / 'LICENSE.txt').read_text() + '\n\n' + (LEGAL / 'DESKTOP-LICENSE.txt').read_text()
    brand = (LEGAL / 'BRAND.md').read_text()
    with tempfile.TemporaryDirectory(prefix='organize-legal-', dir=LEGAL) as staging:
        output = Path(staging)
        for source, dest in [(ROOT / 'LICENSE.txt', 'LICENSE.txt'), (LEGAL / 'DESKTOP-LICENSE.txt', 'DESKTOP-LICENSE.txt'),
                             (LEGAL / 'BRAND.md', 'BRAND.md'),
                             (LEGAL / 'README.md', 'README.md'),
                             (DESKTOP / 'src-tauri/Cargo.lock', 'Cargo.lock'),
                             (DESKTOP / 'package-lock.json', 'package-lock.json')]:
            shutil.copyfile(source, output / dest)
        (output / 'python-packages.json').write_text(json.dumps(python_inventory, indent=2) + '\n')
        archive = output / 'MPL-SOURCES.zip'
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_STORED) as z:
            for p in mpl:
                # Stable timestamps; these are untouched upstream tar.gz crate source archives.
                info = zipfile.ZipInfo(f'{p["name"]}-{p["version"]}.crate', date_time=(1980, 1, 1, 0, 0, 0))
                z.writestr(info, p['path'].read_bytes())
            full_mpl = next(f['text'] for p in components if p['name'] == 'cssparser'
                            for f in p['files'] if 'Mozilla Public License Version 2.0' in f['text'])
            z.writestr(zipfile.ZipInfo('MPL-2.0.txt'), full_mpl)
        source_text = '# MPL-2.0 Corresponding Source\n\nThis distribution provides the following original, unmodified corresponding-version source code under MPL-2.0.\nThe source comes bundled with the app free of charge; no network, payment or login is needed.\n\nTo get it: About & diagnostics → Open-source licenses and source code → Open MPL source archive;\nor in macOS, Show Package Contents → Contents/Resources/legal/MPL-SOURCES.zip.\n\nUnzip the ZIP first; each .crate is a standard tar.gz, extract it with tar -xzf <name-version.crate>.\nAll original source, Cargo.toml and the original license/copyright headers are kept; MPL-2.0.txt provides the full license text.\noption-ext is a desktop runtime dependency. The remaining components are mainly used for building or macro expansion.\nIndependent MIT code does not become MPL as a whole because of this archive. When you redistribute after modifying these MPL files,\nyou must provide the actual modified corresponding source, and must not keep claiming that it is unmodified here.\n\n\n'
        for p in mpl:
            source_text += f'- {p["name"]} {p["version"]}\n  Source: {p["source"]}\n  SHA-256: {p["sha256"]}\n'
        source_text += f'\nMPL-SOURCES.zip SHA-256: {sha(archive.read_bytes())}\n'
        source_text += '\nLicense: https://www.mozilla.org/en-US/MPL/2.0/\n'
        (output / 'MPL-SOURCES.md').write_text(source_text)
        notices = 'Organize — Independent derivative project\n\n' + mit + '\n' + brand
        notices += '\nInventory conservatively includes runtime AND build dependencies.\n'
        for p in components:
            notices += f'\n{"=" * 72}\n{p["ecosystem"]}: {p["name"]} {p["version"]}\nLicense: {p["license"]}\nScope: {p["scope"]}\nSource: {p["source"]}\n'
            for f in p['files']:
                notices += f'\n--- {f["name"]} (SHA-256 {f["sha256"]}) ---\n{f["text"]}\n'
        (output / 'THIRD_PARTY_NOTICES.txt').write_text(notices)
        public_components = [{**p, 'files': [{k: v for k, v in f.items() if k != 'text'} for f in p['files']]}
                             for p in components]
        manifest = {'target': target, 'appVersion': json.loads((DESKTOP / 'package.json').read_text())['version'],
                    'scope': 'Conservative inventory; runtime and build dependencies are not all linked.',
                    'components': public_components,
                    'mplSources': [{k: v for k, v in p.items() if k != 'path'} for p in mpl],
                    'files': {p.name: sha(p.read_bytes()) for p in sorted(output.iterdir())}}
        (output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
        destination = LEGAL / 'generated'
        destination.mkdir(exist_ok=True)
        for p in output.iterdir():
            os.replace(p, destination / p.name)
        frontend = DESKTOP / 'src/generated/legal-notices.json'
        frontend.parent.mkdir(parents=True, exist_ok=True)
        frontend.write_text(json.dumps({'mit': mit, 'brand': brand, 'sources': source_text,
                                        'target': target, 'components': components}, ensure_ascii=False))
    print(f'License bundle: {len(components)} components, {len(mpl)} exact MPL source archives, target {target}')


if __name__ == '__main__':
    main()
