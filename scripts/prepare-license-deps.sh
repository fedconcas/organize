#!/usr/bin/env bash
# Populate the locked host graph before the deliberately offline license audit.
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"
target_triple="$(rustc --print host-tuple)"

cargo fetch --locked --target "$target_triple" --manifest-path "$repo_root/apps/desktop/src-tauri/Cargo.toml"
