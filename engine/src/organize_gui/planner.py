import os
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

from .errors import Cancelled, EngineError
from .paths import (
    absolute_path,
    fingerprint,
    is_within,
    path_key,
    should_skip_name,
    unique_destination,
)
from .presets import (
    IMAGE_EXTENSIONS,
    INSTALLER_EXTENSIONS,
)
from .profiles import normalized_extension, type_configuration, validate_type_configuration
from .similar import items_from_scan, scan_similar_photos
from .store import Store
from .v3_core import (
    CORE_VERSION,
    apply,
    duplicate_filter,
    extension_filter,
    hash_filter,
    last_modified_filter,
    resource_for,
    size_filter,
    walk_files,
)


Progress = Optional[Callable[[Dict[str, Any]], None]]
CancelledCheck = Optional[Callable[[], bool]]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime) -> str:
    return value.isoformat()


def validate_profile(profile: Dict[str, Any], check_paths: bool = True) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    source_values = profile.get("sourceFolders", [])
    if not isinstance(source_values, list) or any(
        not isinstance(value, str) or not value.strip() for value in source_values
    ):
        return [{"code": "SOURCE_NOT_FOUND", "field": "sourceFolders"}]
    sources = [absolute_path(item) for item in source_values]
    if not sources:
        issues.append({"code": "SOURCE_NOT_FOUND", "field": "sourceFolders"})
    for source in sources:
        if not check_paths:
            continue
        if not source.exists() or not source.is_dir():
            issues.append({"code": "SOURCE_NOT_FOUND", "path": str(source)})
        elif not os.access(str(source), os.R_OK | os.X_OK):
            issues.append({"code": "SOURCE_NOT_READABLE", "path": str(source)})

    preset = profile.get("presetType")
    if preset not in {"by-type", "by-date", "old-installers", "duplicates", "similar-photos"}:
        issues.append({"code": "INVALID_PRESET", "field": "presetType"})

    target_value = profile.get("targetFolder")
    if preset not in {"old-installers", "duplicates", "similar-photos"}:
        if not isinstance(target_value, str) or not target_value.strip():
            issues.append({"code": "TARGET_NOT_WRITABLE", "field": "targetFolder"})
        else:
            target = absolute_path(target_value)
            nearest = target
            while not nearest.exists() and nearest.parent != nearest:
                nearest = nearest.parent
            if check_paths and (not nearest.is_dir() or not os.access(str(nearest), os.W_OK | os.X_OK)):
                issues.append({"code": "TARGET_NOT_WRITABLE", "path": str(target)})
            for source in sources:
                if path_key(source) == path_key(target) or is_within(target, source):
                    issues.append(
                        {
                            "code": "SOURCE_TARGET_OVERLAP",
                            "path": str(target),
                            "source": str(source),
                        }
                    )
    if not isinstance(profile.get("parameters", {}), dict):
        issues.append({"code": "INVALID_TYPE_RULES", "field": "parameters"})
    elif preset == "by-type":
        rule_issues = validate_type_configuration(profile)
        issues.extend(rule_issues)
        if not rule_issues and isinstance(target_value, str) and target_value.strip():
            rules, unmatched, other_folder = type_configuration(profile)
            folders = [rule["folderName"] for rule in rules if rule["enabled"]]
            if unmatched == "other":
                folders.append(other_folder)
            target = absolute_path(target_value)
            for folder in folders:
                destination = target / folder
                if not is_within(destination, target):
                    issues.append({"code": "TARGET_OUTSIDE_ROOT", "path": str(destination)})
                elif any(is_within(destination, source) for source in sources):
                    issues.append({"code": "SOURCE_TARGET_OVERLAP", "path": str(destination)})
    if isinstance(profile.get("parameters", {}), dict):
        params = profile.get("parameters", {})
        for key, minimum, maximum in [("olderThanDays", 1, 36500), ("minimumBytes", 0, 10**15)]:
            if key in params and (type(params[key]) is not int or not minimum <= params[key] <= maximum):
                issues.append({"code": "INVALID_PARAMETER", "field": "parameters.%s" % key})
        if preset == "similar-photos":
            if params.get("scanExact") is False and params.get("scanSimilar") is False:
                issues.append({"code": "INVALID_PARAMETER", "field": "parameters.scanExact"})
            for key in ("scanExact", "scanSimilar", "geometricInvariance"):
                if key in params and not isinstance(params[key], bool):
                    issues.append({"code": "INVALID_PARAMETER", "field": "parameters.%s" % key})
            if "maxDifference" in params and (
                type(params["maxDifference"]) is not int or not 0 <= params["maxDifference"] <= 40
            ):
                issues.append({"code": "INVALID_PARAMETER", "field": "parameters.maxDifference"})
            if "hashSize" in params and params["hashSize"] not in (8, 16, 32, 64):
                issues.append({"code": "INVALID_PARAMETER", "field": "parameters.hashSize"})
            if "keepRule" in params and params["keepRule"] not in {"resolution", "largest", "newest", "shortest"}:
                issues.append({"code": "INVALID_PARAMETER", "field": "parameters.keepRule"})
    return issues


def scan_files(
    sources: List[Path],
    recursive: bool,
    progress: Progress = None,
    cancelled: CancelledCheck = None,
):
    count = 0
    seen: Set[str] = set()
    for resource in walk_files(sources, recursive):
        if cancelled and cancelled():
            raise Cancelled()
        source = resource.path
        if source is None:
            continue
        key = path_key(source)
        if key in seen:
            continue
        seen.add(key)
        count += 1
        reason = should_skip_name(source.name)
        if progress and (count == 1 or count % 100 == 0):
            progress(
                {
                    "type": "progress",
                    "core": CORE_VERSION,
                    "checked": count,
                    "path": str(source),
                }
            )
        yield resource, reason


class Planner:
    def __init__(self, store: Store, quarantine_root: Path) -> None:
        self.store = store
        self.quarantine_root = quarantine_root
        self.scan_similar = scan_similar_photos

    def create(
        self,
        profile: Dict[str, Any],
        progress: Progress = None,
        cancelled: CancelledCheck = None,
    ) -> Dict[str, Any]:
        issues = validate_profile(profile)
        if issues:
            raise EngineError("PROFILE_INVALID", "The profile is invalid.", {"issues": issues})
        now = utc_now()
        plan_id = uuid.uuid4().hex
        preset = profile["presetType"]
        extra: Dict[str, Any] = {}
        if preset == "duplicates":
            items = self._duplicates(plan_id, profile, progress, cancelled)
        elif preset == "similar-photos":
            items, extra = self._similar_photos(plan_id, profile, progress, cancelled)
        else:
            items = self._regular(plan_id, profile, progress, cancelled)
        summary = self._summary(items)
        summary.update(extra)
        self.store.save_profile(profile, iso(now))
        self.store.save_plan(
            plan_id,
            profile,
            iso(now),
            iso(now + timedelta(minutes=30)),
            summary,
            items,
        )
        result = self.store.get_plan(plan_id)
        if progress:
            progress({"type": "completed", "planId": plan_id, "summary": summary})
        return result

    def _regular(
        self,
        plan_id: str,
        profile: Dict[str, Any],
        progress: Progress,
        cancelled: CancelledCheck,
    ) -> List[Dict[str, Any]]:
        sources = [absolute_path(item) for item in profile["sourceFolders"]]
        target = absolute_path(profile.get("targetFolder", str(self.quarantine_root)))
        recursive = bool(profile.get("includeSubfolders", False))
        occupied: Set[str] = set()
        items: List[Dict[str, Any]] = []
        params = profile.get("parameters", {})
        age_days = int(params.get("olderThanDays", 90))
        rules, unmatched, other_folder = type_configuration(profile) if profile["presetType"] == "by-type" else ([], "keep", "")
        category_filters = [
            (rule, extension_filter([normalized_extension(value) for value in rule["extensions"]]))
            for rule in rules if rule["enabled"]
        ] if profile["presetType"] == "by-type" else []
        image_filter = extension_filter(IMAGE_EXTENSIONS)
        modified_filter = last_modified_filter()
        include_archives = bool(params.get("includeArchives", False))
        installer_filter = extension_filter(
            INSTALLER_EXTENSIONS | ({"zip"} if include_archives else set())
        )
        old_filter = last_modified_filter(days=age_days)

        for resource, skip_reason in scan_files(sources, recursive, progress, cancelled):
            source = resource.path
            if source is None:
                continue
            root = resource.basedir or source.parent
            item: Optional[Dict[str, Any]] = None
            if skip_reason:
                item = self._item(plan_id, len(items), source, None, "skip", False, skip_reason)
            elif profile["presetType"] == "by-type":
                rule = next(
                    (
                        candidate
                        for candidate, filter_instance in category_filters
                        if apply(filter_instance, resource_for(source, root))
                    ),
                    None,
                )
                if rule is not None or unmatched == "other":
                    folder = rule["folderName"] if rule else other_folder
                    destination = target / folder / source.name
                    destination, renamed = unique_destination(destination, occupied)
                    item = self._item(plan_id, len(items), source, destination, "move", True)
                    item["metadata"]["category"] = rule["id"] if rule else "other"
                    item["metadata"]["categoryName"] = rule["name"] if rule else other_folder
                    if renamed:
                        item["warningCode"] = "TARGET_CONFLICT"
                else:
                    item = self._item(plan_id, len(items), source, None, "skip", False, "Unmatched category, left in place")
            elif profile["presetType"] == "by-date":
                date_resource = resource_for(source, root)
                if apply(image_filter, date_resource) and apply(modified_filter, date_resource):
                    modified = date_resource.vars["lastmodified"]
                    destination = target / ("%d" % modified.year) / ("%02d" % modified.month) / source.name
                    destination, renamed = unique_destination(destination, occupied)
                    item = self._item(plan_id, len(items), source, destination, "move", True)
                    if renamed:
                        item["warningCode"] = "TARGET_CONFLICT"
            elif profile["presetType"] == "old-installers":
                old_resource = resource_for(source, root)
                if apply(installer_filter, old_resource) and apply(old_filter, old_resource):
                    destination = self._quarantine_destination(plan_id, root, source)
                    item = self._item(plan_id, len(items), source, destination, "quarantine", True)
                    item["reason"] = "Old installers, %d days unmodified" % age_days
            if item is not None:
                item["metadata"]["organizeCore"] = CORE_VERSION
                items.append(item)
        return items

    def _duplicates(
        self,
        plan_id: str,
        profile: Dict[str, Any],
        progress: Progress,
        cancelled: CancelledCheck,
    ) -> List[Dict[str, Any]]:
        sources = [absolute_path(item) for item in profile["sourceFolders"]]
        recursive = bool(profile.get("includeSubfolders", True))
        minimum = int(profile.get("parameters", {}).get("minimumBytes", 1024 * 1024))
        v3_size = size_filter(minimum)
        v3_duplicate = duplicate_filter()
        parents: Dict[Path, Path] = {}
        basedirs: Dict[Path, Path] = {}

        def find(path: Path) -> Path:
            parents.setdefault(path, path)
            if parents[path] != path:
                parents[path] = find(parents[path])
            return parents[path]

        def union(left: Path, right: Path) -> None:
            left_root = find(left)
            right_root = find(right)
            if left_root != right_root:
                parents[right_root] = left_root

        checked = 0
        for resource, reason in scan_files(sources, recursive, progress, cancelled):
            source = resource.path
            if reason or source is None or not apply(v3_size, resource):
                continue
            basedirs[source] = resource.basedir or source.parent
            duplicate_resource = resource_for(source, resource.basedir)
            checked += 1
            if apply(v3_duplicate, duplicate_resource):
                original = Path(duplicate_resource.vars["duplicate"]["original"])
                assert duplicate_resource.path is not None
                duplicate = Path(duplicate_resource.path)
                basedirs.setdefault(original, resource.basedir or original.parent)
                basedirs.setdefault(duplicate, resource.basedir or duplicate.parent)
                union(original, duplicate)
            if progress:
                progress(
                    {
                        "type": "progress",
                        "core": CORE_VERSION,
                        "stage": "duplicate",
                        "checked": checked,
                        "path": str(source),
                    }
                )

        grouped: Dict[Path, List[Path]] = defaultdict(list)
        for path in parents:
            grouped[find(path)].append(path)

        v3_hash = hash_filter()
        items: List[Dict[str, Any]] = []
        group_index = 0
        for paths in sorted(grouped.values(), key=lambda group: [str(path) for path in group]):
            if len(paths) < 2:
                continue
            group_index += 1
            group_id = "%s-g%d" % (plan_id, group_index)
            paths = sorted(paths, key=str)
            recommended = min(paths, key=lambda path: (path.stat().st_mtime_ns, str(path)))
            digest_resource = resource_for(paths[0], basedirs[paths[0]])
            apply(v3_hash, digest_resource)
            digest = digest_resource.vars["hash"]
            for source in paths:
                root = basedirs[source]
                destination = self._quarantine_destination(plan_id, root, source)
                item = self._item(plan_id, len(items), source, destination, "quarantine", False)
                item["groupId"] = group_id
                item["metadata"].update(
                    {
                        "digest": digest,
                        "recommendedKeep": source == recommended,
                        "decision": "undecided",
                        "organizeCore": CORE_VERSION,
                    }
                )
                item["reason"] = "Duplicate files"
                items.append(item)
        return items

    def _similar_photos(
        self,
        plan_id: str,
        profile: Dict[str, Any],
        progress: Progress,
        cancelled: CancelledCheck,
    ):
        if cancelled and cancelled():
            raise Cancelled()
        preview_dir = self.quarantine_root.parent / "similar-previews" / plan_id
        result = self.scan_similar(profile, preview_dir, progress, cancelled)
        sources = [absolute_path(item) for item in profile["sourceFolders"]]

        def destination(source: Path) -> Path:
            matches = [item for item in sources if is_within(source, item)]
            root = max(matches, key=lambda item: len(path_key(item))) if matches else source.parent
            return self._quarantine_destination(plan_id, root, source)

        items = items_from_scan(plan_id, profile, result, self._item, destination)
        extra = {
            "warnings": list(result.get("warnings") or []),
            "heicDecoder": result.get("heicDecoder") or "none",
        }
        return items, extra

    def _quarantine_destination(self, plan_id: str, root: Path, source: Path) -> Path:
        try:
            relative = source.relative_to(root)
        except ValueError:
            relative = Path(source.name)
        destination = self.quarantine_root / plan_id / uuid.uuid4().hex[:8] / relative
        if not is_within(destination, self.quarantine_root):
            raise EngineError("INVALID_PATH", "Quarantine path escaped its root.")
        return destination

    @staticmethod
    def _item(
        plan_id: str,
        sequence: int,
        source: Path,
        target: Optional[Path],
        operation: str,
        selected: bool,
        reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        return {
            "itemId": uuid.uuid4().hex,
            "planId": plan_id,
            "sequence": sequence,
            "operation": operation,
            "sourcePath": str(source),
            "targetPath": str(target) if target else None,
            "size": source.stat().st_size,
            "fingerprint": fingerprint(source),
            "selected": selected,
            "status": "planned" if operation != "skip" else "skipped",
            "warningCode": None,
            "reason": reason,
            "metadata": {},
        }

    @staticmethod
    def _summary(items: List[Dict[str, Any]]) -> Dict[str, Any]:
        selected = [item for item in items if item.get("selected")]
        return {
            "total": len(items),
            "selected": len(selected),
            "selectedBytes": sum(item["size"] for item in selected),
            "move": sum(item["operation"] == "move" for item in selected),
            "quarantine": sum(item["operation"] == "quarantine" for item in selected),
            "skip": sum(item["status"] == "skipped" for item in items),
            "conflict": sum(bool(item.get("warningCode")) for item in items),
            "groups": len({item.get("groupId") for item in items if item.get("groupId")}),
        }
