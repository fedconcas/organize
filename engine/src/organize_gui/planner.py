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
from .classify.classifier import ContentClassifier, metadata_matches
from .photo_meta import read_meta
from .profiles import normalized_extension, rule_kind, type_configuration, validate_type_configuration
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
    if preset not in {"by-type", "by-date", "old-installers", "duplicates"}:
        issues.append({"code": "INVALID_PRESET", "field": "presetType"})

    target_value = profile.get("targetFolder")
    if preset not in {"old-installers", "duplicates"}:
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
        if "dateSource" in params and params["dateSource"] not in {"taken", "modified"}:
            issues.append({"code": "INVALID_PARAMETER", "field": "parameters.dateSource"})
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
        # Set by the service: () -> settings dict, and an optional model-session factory (tests).
        self.ai_settings: Callable[[], Dict[str, Any]] = lambda: {"aiEnabled": False}
        self.session_factory: Optional[Callable[[], Any]] = None

    def create(
        self,
        profile: Dict[str, Any],
        progress: Progress = None,
        cancelled: CancelledCheck = None,
        from_analysis: Optional[str] = None,
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
        elif preset == "by-type":
            items, extra = self._by_type(plan_id, profile, progress, cancelled, from_analysis)
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

    def _by_type(
        self,
        plan_id: str,
        profile: Dict[str, Any],
        progress: Progress,
        cancelled: CancelledCheck,
        from_analysis: Optional[str],
    ):
        """extension rules -> metadata rules -> content rules (analysis assignment, else nearest centroid)."""
        sources = [absolute_path(item) for item in profile["sourceFolders"]]
        target = absolute_path(profile["targetFolder"])
        recursive = bool(profile.get("includeSubfolders", False))
        rules, unmatched, other_folder = type_configuration(profile)
        enabled = [rule for rule in rules if rule["enabled"]]
        by_id = {rule["id"]: rule for rule in enabled}
        extension_rules = [(rule, extension_filter([normalized_extension(value) for value in rule["extensions"]]))
                           for rule in enabled if rule_kind(rule) == "extension"]
        metadata_rules = [(rule, {normalized_extension(value) for value in rule.get("extensions", [])})
                          for rule in enabled if rule_kind(rule) == "metadata"]
        content_rules = [rule for rule in enabled if rule_kind(rule) == "content"]
        assignments = self.store.assignments(from_analysis) if from_analysis else {}
        settings = self.ai_settings()

        decisions: List[Any] = []
        pending: List[Path] = []
        metas: Dict[Path, Dict[str, Any]] = {}
        for resource, skip_reason in scan_files(sources, recursive, progress, cancelled):
            source = resource.path
            if source is None:
                continue
            if skip_reason:
                decisions.append((source, None, None, skip_reason))
                continue
            assigned = assignments.get(path_key(source))
            if assigned and assigned["fingerprint"] == fingerprint(source):
                ref = assigned["categoryRef"]
                confidence = assigned["confidence"]
                manual = confidence.startswith("manual:")
                confidence = confidence.split(":", 1)[-1]
                if ref in by_id:
                    rule = by_id[ref]
                    source_kind = "manual" if manual else "analysis" if rule_kind(rule) == "content" else rule_kind(rule)
                    decisions.append((source, rule, (confidence, source_kind), None))
                    continue
                if ref == "other":
                    decisions.append((source, None, ("high", "analysis"), None))
                    continue
            root = resource.basedir or source.parent
            rule = next((candidate for candidate, filter_instance in extension_rules
                         if apply(filter_instance, resource_for(source, root))), None)
            if rule is not None:
                decisions.append((source, rule, ("high", "extension"), None))
                continue
            extension = source.suffix.lower().lstrip(".")
            candidates = [candidate for candidate, scope in metadata_rules if not scope or extension in scope]
            if candidates:
                meta = read_meta(source)
                metas[source] = meta
                rule = next((candidate for candidate in candidates
                             if metadata_matches(candidate.get("match", {}), meta, source.name)), None)
                if rule is not None:
                    decisions.append((source, rule, ("high", "metadata"), None))
                    continue
            if content_rules:
                pending.append(source)
                decisions.append((source, "pending", None, None))
            else:
                decisions.append((source, None, None, None))

        notice = None
        matched: Dict[Path, Any] = {}
        if pending:
            if progress:
                progress({"type": "progress", "core": CORE_VERSION, "stage": "classify", "checked": len(pending),
                          "label": "Matching files to your categories"})
            classifier = ContentClassifier(self.store, content_rules, settings.get("aiEmbedModel", ""),
                                           bool(settings.get("aiEnabled")), self.session_factory)
            matched, notice = classifier.classify(pending, metas, cancelled, sources)

        occupied: Set[str] = set()
        items: List[Dict[str, Any]] = []
        suggestions = 0
        for source, rule, decision, skip_reason in decisions:
            if skip_reason:
                items.append(self._item(plan_id, len(items), source, None, "skip", False, skip_reason))
                continue
            reason = None
            if rule == "pending":
                found = matched.get(source)
                if found:
                    rule, confidence, _ = found
                    decision = (confidence, "content")
                else:
                    rule = None
                    reason = ("Not classified: local AI is off" if notice == "AI_DISABLED"
                              else "Not classified: local AI unavailable" if notice == "AI_UNAVAILABLE"
                              else "No category was a close match")
            if rule is None and unmatched != "other":
                item = self._item(plan_id, len(items), source, None, "skip", False, reason or "Unmatched category, left in place")
            else:
                folder = rule["folderName"] if rule else other_folder
                destination, renamed = unique_destination(target / folder / source.name, occupied)
                confidence, origin = decision or ("high", "unmatched")
                selected = not (origin in {"content", "analysis"} and confidence != "high")
                item = self._item(plan_id, len(items), source, destination, "move", selected, reason)
                item["metadata"].update({
                    "category": rule["id"] if rule else "other",
                    "categoryName": rule["name"] if rule else other_folder,
                    "confidence": confidence,
                    "source": origin,
                })
                if origin in {"content", "analysis"}:
                    suggestions += 1
                if renamed:
                    item["warningCode"] = "TARGET_CONFLICT"
            item["metadata"]["organizeCore"] = CORE_VERSION
            items.append(item)
        extra: Dict[str, Any] = {"suggestions": suggestions}
        if from_analysis:
            extra["fromAnalysisId"] = from_analysis
        if notice:
            extra["aiNotice"] = notice
        return items, extra

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
        use_date_taken = params.get("dateSource", "taken") == "taken"

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
                    when = date_resource.vars["lastmodified"]
                    date_source = "modified"
                    if use_date_taken:
                        meta = read_meta(source)
                        if meta["dateSource"] == "taken" and meta["dateTaken"]:
                            when = datetime.fromisoformat(meta["dateTaken"])
                            date_source = "taken"
                    destination = target / ("%d" % when.year) / ("%02d" % when.month) / source.name
                    destination, renamed = unique_destination(destination, occupied)
                    item = self._item(plan_id, len(items), source, destination, "move", True)
                    item["metadata"]["dateSource"] = date_source
                    item["reason"] = (
                        "Date taken" if date_source == "taken"
                        else "Modified date (no date taken)" if use_date_taken else "Modified date"
                    )
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
