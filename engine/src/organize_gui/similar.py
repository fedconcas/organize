"""Scan photos with the MIT similar-photos sidecar and map groups into plan items.

The sidecar detects exact and perceptually similar photos. It never deletes them.
Quarantine and undo stay in the executor.
"""

import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .errors import Cancelled, EngineError
from .paths import absolute_path, fingerprint, is_within, path_key, should_skip_name
from .v3_core import CORE_VERSION

Progress = Optional[Callable[[Dict[str, Any]], None]]
CancelledCheck = Optional[Callable[[], bool]]
KEEP_RULES = ("resolution", "largest", "newest", "shortest")


def similar_photos_binary() -> Path:
    override = os.environ.get("ORGANIZE_SIMILAR_PHOTOS")
    if override:
        path = Path(override)
        if path.is_file():
            return path
        raise EngineError(
            "SIMILAR_SCANNER_MISSING",
            "ORGANIZE_SIMILAR_PHOTOS points to a scanner component that does not exist.",
            {"path": override},
        )
    if getattr(sys, "frozen", False):
        extension = ".exe" if os.name == "nt" else ""
        bundled = Path(sys.executable).resolve().with_name("similar-photos" + extension)
        if bundled.is_file():
            return bundled
    binaries = Path(__file__).resolve().parents[3] / "apps" / "desktop" / "src-tauri" / "binaries"
    matches = [
        path for path in binaries.glob("similar-photos-*")
        if path.is_file() and path.suffix == (".exe" if os.name == "nt" else path.suffix)
        and not path.name.endswith(".d")
    ]
    if os.name != "nt":
        matches = [path for path in matches if path.suffix != ".exe"]
    if not matches:
        raise EngineError(
            "SIMILAR_SCANNER_MISSING",
            "Similar-photo scanner not found. Please run first:  scripts/build-similar-sidecar.sh. ",
        )
    return max(matches, key=lambda path: path.stat().st_mtime)


def scan_similar_photos(
    profile: Dict[str, Any],
    preview_dir: Path,
    progress: Progress = None,
    cancelled: CancelledCheck = None,
) -> Dict[str, Any]:
    params = profile.get("parameters") or {}
    preview_dir.mkdir(parents=True, exist_ok=True)
    stop_file = preview_dir / "stop"
    request = {
        "directories": [str(absolute_path(item)) for item in profile["sourceFolders"]],
        "recursive": bool(profile.get("includeSubfolders", True)),
        "exact": bool(params.get("scanExact", True)),
        "similar": bool(params.get("scanSimilar", True)),
        "minimumBytes": int(params.get("minimumBytes") or 0),
        "maxDifference": int(params.get("maxDifference", 5)),
        "hashSize": int(params.get("hashSize", 16)),
        "hashAlg": str(params.get("hashAlg") or "Gradient"),
        "geometricInvariance": "mirror-flip-rotate90" if params.get("geometricInvariance", True) else "off",
        "previewDir": str(preview_dir),
        "stopFile": str(stop_file),
    }
    request_path = preview_dir / "request.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    binary = similar_photos_binary()
    home = preview_dir / "scanner-home"
    cache = preview_dir / "scanner-cache"
    home.mkdir(exist_ok=True)
    cache.mkdir(exist_ok=True)
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["XDG_CACHE_HOME"] = str(cache)
    process = subprocess.Popen(
        [str(binary), "--request", str(request_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    lines: "queue.Queue[Optional[str]]" = queue.Queue()
    errors: List[str] = []

    def read_stdout() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            lines.put(line)
        lines.put(None)

    def read_stderr() -> None:
        assert process.stderr is not None
        errors.append(process.stderr.read())

    stdout_thread = threading.Thread(target=read_stdout, daemon=True)
    stderr_thread = threading.Thread(target=read_stderr, daemon=True)
    stdout_thread.start()
    stderr_thread.start()
    result = None
    try:
        while True:
            if cancelled and cancelled():
                stop_file.write_text("stop", encoding="utf-8")
                process.terminate()
                raise Cancelled()
            try:
                line = lines.get(timeout=0.2)
            except queue.Empty:
                if process.poll() is not None and lines.empty():
                    break
                continue
            if line is None:
                break
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = message.get("type")
            if kind == "progress" and progress:
                progress({
                    "type": "progress",
                    "stage": message.get("stage") or "similar",
                    "checked": message.get("checked") or 0,
                    "total": message.get("total") or 0,
                    "path": message.get("path") or "",
                    "label": message.get("label") or "",
                })
            elif kind == "error":
                raise EngineError("SIMILAR_SCAN_FAILED", str(message.get("message") or "Similar-photo scan failed"))
            elif kind == "result":
                result = message
        return_code = process.wait()
        if cancelled and cancelled():
            raise Cancelled()
        if result and result.get("stopped"):
            raise Cancelled()
        if return_code != 0 or result is None:
            detail = (errors[0] if errors else "").strip()[-2000:]
            message = "Similar-photo scan failed."
            if detail:
                message = "Similar-photo scan failed: %s" % detail[-400:]
            raise EngineError(
                "SIMILAR_SCAN_FAILED",
                message,
                {"exitCode": return_code, "stderr": detail},
            )
        return result
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        stdout_thread.join(timeout=2)
        stderr_thread.join(timeout=2)
        if process.stdout:
            process.stdout.close()
        if process.stderr:
            process.stderr.close()


def items_from_scan(
    plan_id: str,
    profile: Dict[str, Any],
    result: Dict[str, Any],
    make_item: Callable[..., Dict[str, Any]],
    quarantine_destination: Callable[[Path], Path],
) -> List[Dict[str, Any]]:
    """Map sidecar groups into unselected quarantine plan items."""
    sources = [absolute_path(item) for item in profile.get("sourceFolders") or []]
    rule = str((profile.get("parameters") or {}).get("keepRule") or "resolution")
    if rule not in KEEP_RULES:
        rule = "resolution"
    items: List[Dict[str, Any]] = []
    for index, (kind, files) in enumerate(merge_groups(result), start=1):
        usable = []
        for raw in files:
            path = absolute_path(str(raw.get("path") or ""))
            if should_skip_name(path.name) or not path.is_file():
                continue
            if sources and not any(is_within(path, source) or path_key(path.parent) == path_key(source) for source in sources):
                continue
            usable.append((path, raw))
        deduped = []
        seen = set()
        for path, raw in usable:
            key = path_key(path)
            if key in seen:
                continue
            seen.add(key)
            deduped.append((path, raw))
        if len(deduped) < 2:
            continue
        group_id = "%s-g%d" % (plan_id, index)
        keep_path = choose_keep(deduped, rule)
        for sequence_offset, (path, raw) in enumerate(deduped):
            destination = quarantine_destination(path)
            item = make_item(plan_id, len(items), path, destination, "quarantine", False)
            item["groupId"] = group_id
            item["reason"] = "Photos with identical content" if kind == "exact" else "Photos that look similar"
            item["metadata"] = {
                "kind": kind,
                "difference": int(raw.get("difference") or 0),
                "width": int(raw.get("width") or 0),
                "height": int(raw.get("height") or 0),
                "modifiedMs": int(raw.get("modified") or 0) * 1000,
                "previewPath": str(raw.get("previewPath") or path),
                "recommendedKeep": path_key(path) == path_key(keep_path),
                "recommendedRule": rule,
                "decision": "undecided",
                "organizeCore": CORE_VERSION,
            }
            item["fingerprint"] = fingerprint(path)
            item["size"] = path.stat().st_size
            items.append(item)
            del sequence_offset
    return items


def merge_groups(result: Dict[str, Any]) -> List[tuple]:
    """Keep rotated copies visible when an exact copy of the same photo also exists."""
    exact_groups = []
    for group in result.get("exact") or []:
        files = [file for file in group.get("files") or [] if file.get("path")]
        if len({path_key(Path(file["path"])) for file in files}) >= 2:
            exact_groups.append(files)
    path_to_exact = {}
    for index, files in enumerate(exact_groups):
        for file in files:
            path_to_exact[path_key(Path(file["path"]))] = index
    consumed = set()
    merged = []
    for group in result.get("similar") or []:
        files = [dict(file) for file in group.get("files") or [] if file.get("path")]
        seen = {path_key(Path(file["path"])) for file in files}
        extras = []
        for file in list(files):
            exact_index = path_to_exact.get(path_key(Path(file["path"])))
            if exact_index is None:
                continue
            consumed.add(exact_index)
            for sibling in exact_groups[exact_index]:
                key = path_key(Path(sibling["path"]))
                if key in seen:
                    continue
                seen.add(key)
                extra = dict(sibling)
                extra["difference"] = 0
                extras.append(extra)
        files.extend(extras)
        if len(seen) >= 2:
            merged.append(("similar", _dedupe_files(files)))
    for index, files in enumerate(exact_groups):
        if index not in consumed:
            merged.append(("exact", _dedupe_files(files)))
    return merged


def _dedupe_files(files: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    chosen = []
    seen = set()
    for file in files:
        key = path_key(Path(file["path"]))
        if key in seen:
            continue
        seen.add(key)
        chosen.append(file)
    return chosen


def choose_keep(files: List[tuple], rule: str) -> Path:
    def sort_key(entry: tuple):
        path, raw = entry
        pixels = int(raw.get("width") or 0) * int(raw.get("height") or 0)
        size = int(raw.get("size") or 0)
        modified = int(raw.get("modified") or 0)
        text = str(path)
        if rule == "largest":
            return (size, pixels, modified, -len(text), text)
        if rule == "newest":
            return (modified, pixels, size, -len(text), text)
        if rule == "shortest":
            return (-len(text), text, pixels, size, modified)
        return (pixels, size, modified, -len(text), text)

    return max(files, key=sort_key)[0]
