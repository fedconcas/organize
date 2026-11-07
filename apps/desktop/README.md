# Organize desktop

## Folder selection and reusable profiles

Downloads is an initial suggestion, not a restriction. In the configuration
screen, replace or remove it and add one or more readable folders. Choose a
separate target folder; scanning previews changes without moving files.

Type-based organization supports editable General, Office and Media templates.
Add or disable classifications, edit display names, destination subfolder names
and extension lists. Choose whether unmatched files stay in place or go to a
named Other folder. An extension may belong to only one enabled classification;
subfolder names cannot escape the target. Save a named profile to reuse its
sources, destination and rules, or make a separate copy. The last scanned profile
is restored after restarting. GUI rules currently match extensions, not arbitrary
filename/content expressions; the upstream CLI remains separate.

Settings control theme, default destination, future quarantine location and
reminder period, history display limit, diagnostic path redaction and completion
notifications. Notifications need OS permission and are sent when backgrounded.
History limits do not delete undo journals. Changing quarantine location does
not move existing files and invalidates previous quarantine previews. Reminder
periods apply to newly quarantined files; nothing is automatically deleted.

## Build a local macOS installer

Prerequisites: Node.js/npm, Rust, Xcode command-line tools, and Python 3.9 or
newer.

```bash
cd apps/desktop
npm ci
npm run bundle:macos
```

The build creates an architecture-specific application and DMG under:

```text
src-tauri/target/release/bundle/macos/Organize.app
src-tauri/target/release/bundle/dmg/
```

The build script creates an isolated Python environment under the repository's
ignored `build/` directory, freezes the engine with PyInstaller, and bundles it
as a Tauri sidecar. The resulting application does not require Python to be
installed on the destination machine.

Local builds use an ad-hoc macOS signature. A Developer ID certificate and
Apple notarization are still required before distributing the DMG to other
users.

Run regression checks with `npm test`, `npm run typecheck`, and
`../../build/desktop-python/bin/python -m unittest discover -s ../../engine/tests -v`
from this directory after building the engine environment.

## Automated GitHub installers

`.github/workflows/desktop-release.yml` tests and builds the Apple Silicon macOS
installer on PRs and on every push/merge to `main` or `master` (the current default
branch is `main`). PRs never publish. A manual run on either primary branch can
publish the initial build. No personal GitHub token or website deployment token
is needed: the isolated publish job uses the workflow's `contents: write` token.

CI installs Python 3.11 and the reviewed versions in
`scripts/desktop-build-requirements.txt`, npm's lockfile and Cargo's lockfile.
Dependency updates must also pass the fail-closed license/source checks.
The actual app signature, native architecture, bundled license checksums, frozen
engine version and DMG checksum are verified before uploading any release.

Each run has its own `desktop-v<version>-build.<run>-<commit>` release. Uploads
happen in a draft; only a complete release becomes public. Re-running a published
run leaves its existing assets unchanged. Builds superseded by a newer commit
are retained without replacing the latest download. There is deliberately no
cancel-in-progress group, so every merge can produce its own package.

Stable website links (only valid after the first successful publication):

- `https://github.com/zyggit/organize/releases/latest/download/Organize-macos-arm64.dmg`
- `https://github.com/zyggit/organize/releases/latest/download/SHA256SUMS.txt`
- `https://github.com/zyggit/organize/releases`

The supported evaluation target is macOS 14+ on Apple Silicon, not Intel Macs or
Windows/Linux desktop. These automated builds currently have the same ad-hoc
signature as local builds and are **not Apple notarized**. They are early
evaluation builds, not frictionless public installs; macOS can block downloaded
apps. Do not disable security protections. Before a general public release,
configure Developer ID signing and notarization following
https://v2.tauri.app/distribute/sign/macos/ and update the build verification,
release metadata and website warning to reflect the verified signing status.

The product page lives in the separate `zyggit/app-pages` repository under
`organize/`. It checks GitHub's latest published release before enabling the DMG
link; missing installers disable the download entry. Network errors and rate
limits show an explicitly labelled releases-page link instead of claiming that
an app is available. A new app release does not require rebuilding that website.

Activating the pipeline requires committing the workflow, its supporting scripts
and the app/engine/license changes it builds, then pushing/merging to the primary
branch. A local untracked workflow never runs on GitHub. Check that GitHub Actions
is enabled for this fork. Creating an empty Release manually does not build a
DMG, and the automatic source ZIP/tar.gz files are not desktop installers. After
the first successful run, verify the Release's Assets contain
`Organize-macos-arm64.dmg`, `SHA256SUMS.txt` and `build-info.json`; the website's
download entry will enable automatically.

macOS freezing strips third-party native debug symbols to remove upstream build paths.
CI pins the standalone CPython 3.11.15 runtime in an isolated build directory rather
than copying a locally installed Python Framework with personal build paths.
Release privacy checks scan tracked source, the actual app bundle, decompressed
PyInstaller modules and bundled ZIP/crate contents for personal home paths and
recognizable credential patterns. Runtime databases/logs, private credential
files and external bundle links fail the build. No matched values are printed.
Only the DMG, checksum list, build metadata and aggregate `privacy-audit.json`
are uploaded, never a local build, user configuration, environment dump or
diagnostic archive. Clean GitHub-hosted runners build the published installer.
These checks are defense in depth; do not commit secrets and do not treat pattern
matching as a guarantee against every possible unknown secret format.

## Application icon

The approved O-and-folder master artwork is `app-icon.png`. Generate the
platform icon sizes with `npm run tauri -- icon app-icon.png`. The sidebar and
About page use `src/assets/app-icon.png`, copied from the generated
`src-tauri/icons/128x128@2x.png`. The older SVG concepts are retained as design
history and are not used by the installer.
