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
from .executor import Executor
from .planner import Planner, validate_profile
from .presets import all_presets
from .store import Store
from .errors import EngineError
from .paths import absolute_path, is_within


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
    ) -> Dict[str, Any]:
        validation = self.validate(profile)
        if not validation["valid"]:
            raise EngineError("PROFILE_INVALID", "Please check the sources, target and category rules.", {"issues": validation["issues"]})
        return self.planner.create(profile, events, cancelled)

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
        return self.executor.execute(plan_id, events)

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
        }

    def update_settings(self, values: Dict[str, Any]) -> Dict[str, Any]:
        for key, value in values.items():
            if key == "theme" and (not isinstance(value, str) or value not in {"system", "light", "dark"}):
                raise EngineError("INVALID_SETTING", "Please choose a valid theme.")
            if key in {"retentionDays", "historyLimit"}:
                low, high = (7, 3650) if key == "retentionDays" else (10, 2000)
                if type(value) is not int or not low <= value <= high:
                    raise EngineError("INVALID_SETTING", "%s Must be between %s–%s ." % (key, low, high))
            if key in {"redactPaths", "notifyOnComplete", "onboardingCompleted"} and type(value) is not bool:
                raise EngineError("INVALID_SETTING", "The switch must be a boolean.")
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
        }
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
                            archive.writestr("logs/%s" % log.name,
                                             redacted(log.read_text(errors="replace")) if redact else log.read_bytes())
        except FileExistsError as exc:
            raise EngineError("TARGET_CONFLICT", "The diagnostic archive already exists.") from exc
        return {"path": str(output), "size": output.stat().st_size}
