import os
import json
import platform
import sys
import zipfile
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from organize.__version__ import __version__ as organize_version

from . import __version__
from .classify import MAX_CATEGORIES, pii
from .classify.backend import BackendUnavailable, find_ollama
from .classify.classifier import CONFIDENCE_ORDER, ModelSession
from .classify.discover import Discovery
from .classify.vectors import backend_name
from .executor import Executor
from .planner import Planner, validate_profile
from .presets import all_presets
from .profiles import type_configuration
from .store import Store
from .errors import EngineError
from .paths import absolute_path, is_within, path_key, unique_destination

AI_DEFAULTS = {
    "aiEnabled": False,
    "aiEmbedModel": "nomic-embed-text",
    "aiLlmModel": "qwen2.5:3b-instruct",
    "aiDescriptions": False,
    "aiThreshold": 0.75,
    "aiOcr": False,
}


def default_data_dir() -> Path:
    override = os.environ.get("ORGANIZE_GUI_DATA_DIR")
    if override:
        return Path(override).expanduser().absolute()
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))
    return base / "organize-gui"


class EngineService:
    def __init__(self, data_dir: Optional[Path] = None) -> None:
        self.data_dir = data_dir or default_data_dir()
        self.store = Store(self.data_dir / "journal.db")
        quarantine = absolute_path(self.store.get_setting("quarantineFolder", str(self.data_dir / "quarantine")))
        self.planner = Planner(self.store, quarantine)
        self.executor = Executor(self.store, self.store.get_setting("retentionDays", 30))
        # Optional (backend, server) factory; tests inject a FakeBackend here.
        self.session_factory: Optional[Callable[[], Any]] = None
        self.planner.ai_settings = self.settings
        self.planner.session_factory = lambda: self._session()
        self.discovery = Discovery(self.store, self.settings, lambda: self._session())

    def _session(self):
        if self.session_factory is not None:
            return self.session_factory()
        from .classify.classifier import default_session
        return default_session()

    def initialize(self) -> Dict[str, Any]:
        recovery = self.executor.recover_interrupted()
        return {
            "engineVersion": __version__,
            "firstLaunch": self.store.get_setting("onboardingCompleted", False) is False,
            "dataDir": str(self.data_dir),
            "recoverableRuns": sum(
                1 for run in self.store.list_history() if run["status"] in {"completed", "partial", "cancelled"}
            ),
            "quarantineCount": len(self.store.list_quarantine()),
            "recovery": recovery,
            "lastProfile": self.store.last_profile(),
        }

    def version(self) -> Dict[str, str]:
        return {"engine": __version__, "organize": organize_version}

    def presets(self) -> List[Dict[str, Any]]:
        return all_presets()

    def validate(self, profile: Dict[str, Any]) -> Dict[str, Any]:
        issues = validate_profile(profile)
        if not issues and any(
            is_within(self.planner.quarantine_root, absolute_path(source)) or
            is_within(absolute_path(source), self.planner.quarantine_root)
            for source in profile["sourceFolders"]
        ):
            issues.append({"code": "QUARANTINE_OVERLAP", "field": "sourceFolders"})
        return {"valid": not issues, "issues": issues}

    def create_plan(
        self,
        profile: Dict[str, Any],
        events: Optional[Callable[[Dict[str, Any]], None]] = None,
        cancelled: Optional[Callable[[], bool]] = None,
        from_analysis: Optional[str] = None,
    ) -> Dict[str, Any]:
        validation = self.validate(profile)
        if not validation["valid"]:
            raise EngineError("PROFILE_INVALID", "Please check the sources, target and category rules.", {"issues": validation["issues"]})
        if from_analysis is not None and not isinstance(from_analysis, str):
            raise EngineError("INVALID_REQUEST", "Invalid analysis.")
        return self.planner.create(profile, events, cancelled, from_analysis)

    def _ready_plan(self, plan_id: str) -> Dict[str, Any]:
        try:
            plan = self.store.get_plan(plan_id)
        except KeyError as exc:
            raise EngineError("PLAN_EXPIRED", "The plan is no longer available.") from exc
        if plan["status"] != "ready" or datetime.fromisoformat(plan["expires_at"]) < datetime.now(timezone.utc):
            raise EngineError("PLAN_EXPIRED", "The plan is no longer ready.")
        return plan

    def set_item_category(self, plan_id: str, item_id: str, category_id: str) -> Dict[str, Any]:
        plan = self._ready_plan(plan_id)
        profile = plan["profile"]
        if profile.get("presetType") != "by-type":
            raise EngineError("INVALID_CATEGORY", "Only plans organized by category can change categories.")
        rules, unmatched, other_folder = type_configuration(profile)
        enabled = {rule["id"]: rule for rule in rules if rule["enabled"]}
        if category_id == "other":
            if unmatched != "other":
                raise EngineError("INVALID_CATEGORY", "This plan leaves unmatched files in place.")
            rule, folder, name = None, other_folder, other_folder
        elif category_id in enabled:
            rule = enabled[category_id]
            folder, name = rule["folderName"], rule["name"]
        else:
            raise EngineError("INVALID_CATEGORY", "Unknown or disabled category.")
        item = next((candidate for candidate in plan["items"] if candidate["item_id"] == item_id), None)
        if item is None or item["reason"] in {"SYSTEM_FILE", "INCOMPLETE_DOWNLOAD"}:
            raise EngineError("INVALID_CATEGORY", "This file cannot be organized.")
        target = absolute_path(profile["targetFolder"])
        destination = target / folder / Path(item["source_path"]).name
        if not is_within(destination, target):
            raise EngineError("TARGET_OUTSIDE_ROOT", "The destination escaped the target folder.")
        occupied = {path_key(Path(other["target_path"])) for other in plan["items"]
                    if other["item_id"] != item_id and other.get("target_path")}
        destination, renamed = unique_destination(destination, occupied)
        metadata = dict(item.get("metadata") or {})
        metadata.update(category=category_id, categoryName=name, confidence="high", source="manual")
        item.update(operation="move", status="planned", target_path=str(destination), selected=True,
                    warning_code="TARGET_CONFLICT" if renamed else None, metadata=metadata,
                    reason=None if item["operation"] == "skip" else item["reason"])
        self.store.update_item(plan_id, item)
        self.store.refresh_summary(plan_id)
        return self.store.get_plan(plan_id)

    def accept_suggestions(self, plan_id: str, min_confidence: str = "high") -> Dict[str, Any]:
        plan = self._ready_plan(plan_id)
        if min_confidence not in CONFIDENCE_ORDER:
            raise EngineError("INVALID_REQUEST", "Unknown confidence level.")
        floor = CONFIDENCE_ORDER[min_confidence]
        for item in plan["items"]:
            metadata = item.get("metadata") or {}
            if (item["status"] == "planned" and not item["selected"]
                    and metadata.get("source") in {"content", "analysis"}
                    and CONFIDENCE_ORDER.get(metadata.get("confidence"), -1) >= floor):
                item["selected"] = True
                self.store.update_item(plan_id, item)
        self.store.refresh_summary(plan_id)
        return self.store.get_plan(plan_id)

    # ---- local AI
    def classifier_status(self, probe: bool = False) -> Dict[str, Any]:
        settings = self.settings()
        result: Dict[str, Any] = {
            "aiEnabled": settings["aiEnabled"], "ollamaInstalled": bool(find_ollama()),
            "vectorBackend": backend_name(), "maxCategories": MAX_CATEGORIES, "models": None,
            "embedModelInstalled": None, "llmModelInstalled": None, "error": None,
        }
        if probe and result["ollamaInstalled"]:
            with ModelSession(lambda: self._session()) as session:
                try:
                    backend = session.get()
                    models = sorted(backend.models())
                    result.update(models=models, embedModelInstalled=backend.has_model(settings["aiEmbedModel"]),
                                  llmModelInstalled=backend.has_model(settings["aiLlmModel"]))
                except BackendUnavailable:
                    result["error"] = "AI_UNAVAILABLE"
        return result

    def analysis_scan(self, params: Dict[str, Any], events=None, cancelled=None) -> Dict[str, Any]:
        return self.discovery.scan(params.get("sourceFolders"), bool(params.get("includeSubfolders", False)), events, cancelled)

    def analysis_discover(self, analysis_id: str, options: Dict[str, Any], events=None, cancelled=None) -> Dict[str, Any]:
        return self.discovery.discover(analysis_id, options or {}, events, cancelled)

    def analysis_split(self, analysis_id: str, category_id: str, events=None, cancelled=None) -> Dict[str, Any]:
        return self.discovery.split(analysis_id, category_id, events, cancelled)

    def analysis_accept(self, analysis_id: str, profile: Dict[str, Any], categories: List[Dict[str, Any]],
                        moves: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        return self.discovery.accept(analysis_id, profile, categories, moves)

    def clear_ai_data(self) -> Dict[str, Any]:
        self.discovery.analyses.clear()
        return {"cleared": self.store.clear_ai_data()}

    def saved_profiles(self) -> List[Dict[str, Any]]:
        return self.store.saved_profiles()

    def save_profile(self, profile: Dict[str, Any]) -> Dict[str, Any]:
        issues = validate_profile(profile, check_paths=False)
        if not isinstance(profile.get("id"), str) or not profile.get("id"):
            issues.append({"code": "INVALID_PROFILE_ID"})
        if not isinstance(profile.get("name"), str) or not profile["name"].strip() or len(profile["name"]) > 80:
            issues.append({"code": "INVALID_PROFILE_NAME"})
        if issues:
            raise EngineError("PROFILE_INVALID", "Please check the plan name, folders and category rules.", {"issues": issues})
        self.store.save_named_profile(profile, datetime.now(timezone.utc).isoformat())
        return profile

    def get_plan(self, plan_id: str) -> Dict[str, Any]:
        return self.store.get_plan(plan_id)

    def select_plan_items(self, plan_id: str, selected_ids: List[str]) -> Dict[str, Any]:
        self.store.select_items(plan_id, selected_ids)
        return self.store.get_plan(plan_id)

    def execute(self, plan_id: str, events: Optional[Callable[[Dict[str, Any]], None]] = None) -> Dict[str, Any]:
        try:
            analysis_id = (self.store.get_plan(plan_id).get("summary") or {}).get("fromAnalysisId")
        except KeyError:
            analysis_id = None
        result = self.executor.execute(plan_id, events)
        if analysis_id:
            self.store.delete_assignments(analysis_id)
        return result

    def history(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        return self.store.list_history(min(max(limit or self.settings()["historyLimit"], 1), 2000))

    def history_detail(self, run_id: str) -> Dict[str, Any]:
        return self.store.run_detail(run_id)

    def undo_preview(self, run_id: str) -> Dict[str, Any]:
        return self.executor.undo_preview(run_id)

    def undo(self, run_id: str, operation_ids: List[str], events: Optional[Callable[[Dict[str, Any]], None]] = None) -> Dict[str, Any]:
        return self.executor.undo(run_id, operation_ids, events)

    def quarantine(self) -> List[Dict[str, Any]]:
        return self.store.list_quarantine()

    def restore_quarantine(
        self, quarantine_ids: List[str], destination_folder: Optional[str] = None
    ) -> Dict[str, Any]:
        return self.executor.restore_quarantine(quarantine_ids, destination_folder)

    def trash_quarantine(self, quarantine_ids: List[str]) -> Dict[str, Any]:
        return self.executor.move_quarantine_to_trash(quarantine_ids)

    def settings(self) -> Dict[str, Any]:
        return {
            "theme": self.store.get_setting("theme", "system"),
            "retentionDays": self.store.get_setting("retentionDays", 30),
            "historyLimit": self.store.get_setting("historyLimit", 200),
            "redactPaths": self.store.get_setting("redactPaths", True),
            "notifyOnComplete": self.store.get_setting("notifyOnComplete", True),
            "defaultTargetFolder": self.store.get_setting("defaultTargetFolder", "~/Documents/Organize"),
            "quarantineFolder": self.store.get_setting("quarantineFolder", str(self.data_dir / "quarantine")),
            **{key: self.store.get_setting(key, value) for key, value in AI_DEFAULTS.items()},
        }

    def update_settings(self, values: Dict[str, Any]) -> Dict[str, Any]:
        for key, value in values.items():
            if key == "theme" and (not isinstance(value, str) or value not in {"system", "light", "dark"}):
                raise EngineError("INVALID_SETTING", "Please choose a valid theme.")
            if key in {"retentionDays", "historyLimit"}:
                low, high = (7, 3650) if key == "retentionDays" else (10, 2000)
                if type(value) is not int or not low <= value <= high:
                    raise EngineError("INVALID_SETTING", "%s Must be between %s–%s ." % (key, low, high))
            if key in {"redactPaths", "notifyOnComplete", "onboardingCompleted", "aiEnabled", "aiDescriptions", "aiOcr"} and type(value) is not bool:
                raise EngineError("INVALID_SETTING", "The switch must be a boolean.")
            if key in {"aiEmbedModel", "aiLlmModel"} and (
                    not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/\-]{0,99}", value)):
                raise EngineError("INVALID_SETTING", "Please choose an installed model.")
            if key == "aiThreshold" and (type(value) not in (int, float) or not 0.5 <= float(value) <= 0.95):
                raise EngineError("INVALID_SETTING", "The match threshold must be between 0.5 and 0.95.")
            if key in {"defaultTargetFolder", "quarantineFolder"}:
                if not isinstance(value, str) or not value.strip():
                    raise EngineError("INVALID_SETTING", "Please choose a valid folder.")
                path = absolute_path(value)
                if not path.is_dir() or not os.access(str(path), os.W_OK | os.X_OK):
                    raise EngineError("INVALID_SETTING", "Folder does not exist or cannot be written to.")
            if key not in {*self.settings(), "onboardingCompleted"}:
                raise EngineError("INVALID_SETTING", "Unknown setting: %s" % key)
        for key, value in values.items():
            self.store.set_setting(key, value)
        self.executor.retention_days = self.settings()["retentionDays"]
        new_root = absolute_path(self.settings()["quarantineFolder"])
        if new_root != self.planner.quarantine_root:
            with self.store.connection() as db:
                db.execute("UPDATE plans SET status='expired' WHERE status='ready' AND plan_id IN "
                           "(SELECT plan_id FROM plan_items WHERE operation='quarantine')")
            self.planner.quarantine_root = new_root
        return self.settings()

    def export_diagnostics(self, destination: str) -> Dict[str, Any]:
        output = Path(destination).expanduser().absolute()
        if output.exists():
            raise EngineError(
                "TARGET_CONFLICT", "The diagnostic archive already exists.",
                {"path": str(output)},
            )
        output.parent.mkdir(parents=True, exist_ok=True)
        failures = self.store.recent_failures()
        redact = self.store.get_setting("redactPaths", True)
        def redacted(text: str) -> str:
            # Redact full paths, including paths outside the user's home, in exported diagnostics only.
            return re.sub(r'(?:[A-Za-z]:[\\/]|/)[^\n\"\'<>]*', '[Path hidden]', text)
        def redact_values(value: Any) -> Any:
            if isinstance(value, dict):
                return {key: redact_values(item) for key, item in value.items()}
            if isinstance(value, list):
                return [redact_values(item) for item in value]
            return redacted(value) if isinstance(value, str) else value

        def scrubbed(value: Any) -> Any:
            # PII scrubbing always applies, independent of the path setting.
            if isinstance(value, dict):
                return {key: scrubbed(item) for key, item in value.items()}
            if isinstance(value, list):
                return [scrubbed(item) for item in value]
            return pii.scrub(value) if isinstance(value, str) else value
        manifest = {
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "app": self.version(),
            "system": {
                "platform": platform.platform(),
                "python": sys.version,
            },
            "settings": self.settings(),
            "database": self.store.database_health(),
            "recentFailures": failures,
            # Category descriptions, analysis tables, the vector cache and photo metadata are never exported.
        }
        manifest = scrubbed(manifest)
        try:
            with zipfile.ZipFile(str(output), "x", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(
                    "diagnostics.json",
                    json.dumps(redact_values(manifest) if redact else manifest, ensure_ascii=False, indent=2),
                )
                logs = self.data_dir / "logs"
                if logs.is_dir():
                    for log in sorted(logs.glob("*.log")):
                        if log.is_file() and log.stat().st_size <= 5 * 1024 * 1024:
                            text = pii.scrub(log.read_text(errors="replace"))
                            archive.writestr("logs/%s" % log.name, redacted(text) if redact else text)
        except FileExistsError as exc:
            raise EngineError("TARGET_CONFLICT", "The diagnostic archive already exists.") from exc
        return {"path": str(output), "size": output.stat().st_size}
