# Distribution Licenses and Source

Organize is an independent desktop derivative project developed from [Thomas Feldmann's organize](https://github.com/tfeldmann/organize),
and is not the official desktop distribution of upstream.
The upstream code remains under the MIT license in the root `LICENSE.txt`; the original copyright notice is kept.
The desktop code, documentation and original vector icons added in this repository are also distributed under MIT. Third-party components remain under their own licenses,
and this project's MIT statement cannot replace them. The license grants no third-party trademark rights.

## Files in the installer package

macOS: right-click the app → Show Package Contents → `Contents/Resources/legal/`.
Inside the app you can also use "About & diagnostics → Open-source licenses and source code" to read the full text and open that folder.

- `LICENSE.txt`: the upstream MIT license and original copyright notice.
- `DESKTOP-LICENSE.txt`: the MIT license for the added desktop contributions and original icons; it does not replace the upstream notice.
- `THIRD_PARTY_NOTICES.txt`: component versions, full license texts, copyrights and the original NOTICE text.
- `manifest.json`: build target, component sources, license file SHA-256 values, lockfiles and source archive SHA-256.
- `MPL-SOURCES.md`, `MPL-SOURCES.zip`: source code for the corresponding versions of MPL components, no network needed.
- `BRAND.md`: independent project and branding notice.
- `Cargo.lock`, `similar-photos-Cargo.lock`, `package-lock.json`, `python-packages.json`: the dependency records for this build.
  `similar-photos` links only the MIT `czkawka_core` and does not include the GPL-3.0-only krokiet.
  The `czkawka_core` dependency graph includes the MPL-2.0 symphonia audio libraries. This feature does not call any audio tools,
  but the unmodified corresponding source is still shipped when the license bundle is generated.

## Reproducible generation

After the npm / Cargo dependencies and the engine packaging environment are installed, run:

```sh
cd apps/desktop
npm run build:licenses
```

`build:bundle` first builds the engine and the similar-photos sidecar, then generates the license materials, and finally builds the frontend.
`build:licenses` first downloads the dependencies of the two Cargo lockfiles for the current host platform, then runs an offline license check.
A network connection is needed for the first build or after dependency updates; once the cache is complete, the check itself does not touch the network.
The generator reads the current npm lockfile, the Cargo dependency graphs of the desktop app and similar-photos, and all distributions installed in the packaged Python environment
(a conservative cover of runtime and build dependencies; it does not mean every component is linked into the app).
Do not interpret the licenses of all build tools as the license of the app as a whole.
The Python standard library license comes from the interpreter packaged in this build, not from an arbitrary latest web page.
The OpenSSL embedded in the cryptography wheel is licensed separately according to the actual library version. This list is not a complete SBOM of the internal dependencies of every native wheel;
when upgrading or replacing binary wheels you must still check their embedded components and copyright notices.

Some upstream packages ship without a separate license file: license notices fetched from a specified commit are cached in
`legal/upstream/`, and their sources and hashes are stored in `legal/upstream.json`. They must be reviewed again after changing dependency versions;
if a license text or corresponding MPL source is found missing, the build fails instead of silently passing.

## Release checklist

1. Rebuild for the actual release platform and check the legal files in the package; do not reuse another platform's manifest.
2. Keep all copyright and NOTICE texts; when modifying MPL files, also provide the modified corresponding source and a description of the changes.
3. MPL files are still provided under MPL-2.0; independent code not covered by it can stay MIT. See
   [MPL 2.0 section 3](https://www.mozilla.org/en-US/MPL/2.0/).
4. When replacing icons or assets, verify their origin, and do not treat historical design drafts as assets licensed for commercial use.
5. Confirm the distributing entity, trademark search, developer signing, notarization and the download page notes. The current supplementary license materials do not mean
   that a trademark clearance or legal opinion has been completed. The objc2 upstream license notes also keep the interpretation risk of bindings derived from the Apple SDK;
   confirm against the Xcode agreement before a commercial release, and do not read the completed files as eliminating all legal risk.

PyInstaller's output exception allows the generated app to use its own license; see its bundled license text.
The final distributor of the package should keep all materials in this directory; if a binary is distributed on its own, these notes and the source must also be provided.
