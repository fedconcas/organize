#!/usr/bin/env bash
set -euo pipefail

# All values come from trusted GitHub runner metadata, not PR titles/bodies.
: "${GH_REPO:?}" "${GITHUB_SHA:?}" "${GITHUB_RUN_NUMBER:?}" "${GITHUB_REF_NAME:?}"
case "$GITHUB_REF_NAME" in main|master) ;; *) echo 'Publishing requires main/master' >&2; exit 1 ;; esac

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
release_dir="$repo_root/build/desktop-release"
cd "$release_dir"
sha256sum --check SHA256SUMS.txt
test "$(jq -r .commit build-info.json)" = "$GITHUB_SHA"
test "$(jq -r .status privacy-audit.json)" = passed
version="$(jq -r .appVersion build-info.json)"
tag="desktop-v${version}-build.${GITHUB_RUN_NUMBER}-${GITHUB_SHA:0:7}"

# A draft is invisible to the website until every asset has uploaded successfully.
if gh release view "$tag" --json isDraft >/dev/null 2>&1; then
  if [[ "$(gh release view "$tag" --json isDraft --jq .isDraft)" == false ]]; then
    echo "Already published: $tag"
    exit 0
  fi
else
  gh release create "$tag" --target "$GITHUB_SHA" --draft --latest=false \
    --title "Organize ${version} · build ${GITHUB_RUN_NUMBER}" \
    --notes "macOS 14+ / Apple Silicon (M-series), early evaluation build.

Download Organize-macos-arm64.dmg, open it and drag Organize into Applications.
This build is ad-hoc signed and NOT Apple notarized; macOS may block it.
Do not disable system security protections. Use a notarized release when required.

Only the macOS Apple Silicon desktop installer is provided; there are no Intel, Windows or Linux desktop builds.
SHA256SUMS.txt provides the installer checksum; build-info.json records the exact source commit.
Source: ${GITHUB_SHA}"
fi
gh release upload "$tag" Organize-macos-arm64.dmg SHA256SUMS.txt build-info.json privacy-audit.json --clobber
head_sha="$(gh api "repos/$GH_REPO/git/ref/heads/$GITHUB_REF_NAME" --jq .object.sha)"
make_latest=false
if [[ "$head_sha" == "$GITHUB_SHA" ]]; then make_latest=true; fi
gh release edit "$tag" --draft=false --latest="$make_latest"
if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
  {
    echo "Release: https://github.com/$GH_REPO/releases/tag/$tag"
    echo "Download: https://github.com/$GH_REPO/releases/latest/download/Organize-macos-arm64.dmg"
    echo "Ad-hoc signed; not Apple notarized."
  } >> "$GITHUB_STEP_SUMMARY"
fi
