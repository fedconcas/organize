import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .errors import EngineError, PlanChanged
from .paths import fingerprint, safe_move, same_fingerprint, unique_destination
from .store import Store


EventCallback = Optional[Callable[[Dict[str, Any]], None]]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Executor:
    def __init__(self, store: Store, retention_days: int = 30) -> None:
        self.store = store
        self.retention_days = retention_days
        self.cancel_event = threading.Event()

    def cancel(self) -> None:
        self.cancel_event.set()

    def execute(self, plan_id: str, events: EventCallback = None) -> Dict[str, Any]:
        self.cancel_event.clear()
        plan = self.store.get_plan(plan_id)
        if plan["status"] != "ready":
            raise EngineError("PLAN_EXPIRED", "The plan is no longer ready.")
        if datetime.fromisoformat(plan["expires_at"]) < datetime.now(timezone.utc):
            raise EngineError("PLAN_EXPIRED", "The plan has expired.")
        items = [item for item in plan["items"] if item["selected"] and item["status"] == "planned"]
        self._preflight(items)
        run_id = uuid.uuid4().hex
        self.store.create_run(
            {
                "runId": run_id,
                "planId": plan_id,
                "profile": plan["profile"],
                "total": len(items),
                "startedAt": now_iso(),
            }
        )
        success = skipped = failed = 0
        success_bytes = 0

        def record_skip(item: Dict[str, Any], code: str) -> None:
            operation_id = uuid.uuid4().hex
            self.store.start_operation({
                "operationId": operation_id, "runId": run_id, "itemId": item["item_id"],
                "sequence": item["seq"], "operation": item["operation"],
                "sourcePath": item["source_path"], "targetPath": item["target_path"],
                "before": item["fingerprint"], "startedAt": now_iso(),
            })
            self.store.finish_operation(operation_id, "skipped", None, now_iso(), code)

        def progress(item: Dict[str, Any], status: str) -> None:
            if events:
                events({"type": "item", "status": status, "index": success + skipped + failed,
                        "success": success, "skipped": skipped, "failed": failed,
                        "total": len(items), "item": item})

        for index, item in enumerate(items):
            if self.cancel_event.is_set():
                skipped += len(items) - index
                for remaining in items[index:]:
                    record_skip(remaining, "CANCELLED")
                progress(item, "skipped")
                break
            if not same_fingerprint(Path(item["source_path"]), item["fingerprint"]):
                skipped += 1
                record_skip(item, "FILE_CHANGED")
                progress(item, "skipped")
                continue
            operation_id = uuid.uuid4().hex
            operation = {
                "operationId": operation_id,
                "runId": run_id,
                "itemId": item["item_id"],
                "sequence": item["seq"],
                "operation": item["operation"],
                "sourcePath": item["source_path"],
                "targetPath": item["target_path"],
                "before": item["fingerprint"],
                "startedAt": now_iso(),
            }
            self.store.start_operation(operation)
            try:
                safe_move(Path(item["source_path"]), Path(item["target_path"]), operation_id)
                after = fingerprint(Path(item["target_path"]))
                self.store.finish_operation(operation_id, "applied", after, now_iso())
                if item["operation"] == "quarantine":
                    stamp = datetime.now(timezone.utc)
                    self.store.add_quarantine(
                        {
                            "quarantineId": uuid.uuid4().hex,
                            "operationId": operation_id,
                            "originalPath": item["source_path"],
                            "quarantinePath": item["target_path"],
                            "reason": item.get("reason") or "Moved to quarantine per the plan",
                            "size": item["size"],
                            "fingerprint": after,
                            "quarantinedAt": stamp.isoformat(),
                            "retentionUntil": (stamp + timedelta(days=self.retention_days)).isoformat(),
                        }
                    )
                success += 1
                success_bytes += item["size"]
                progress(item, "applied")
            except EngineError as exc:
                failed += 1
                self.store.finish_operation(operation_id, "failed", None, now_iso(), exc.code, str(exc))
                progress(item, "failed")
            except OSError as exc:
                failed += 1
                code = self._os_error_code(exc)
                self.store.finish_operation(operation_id, "failed", None, now_iso(), code, str(exc))
                progress(item, "failed")
        if self.cancel_event.is_set():
            status = "cancelled"
        elif failed and success:
            status = "partial"
        elif failed:
            status = "failed"
        else:
            status = "completed"
        result = {
            "runId": run_id,
            "planId": plan_id,
            "status": status,
            "total": len(items),
            "success": success,
            "skipped": skipped,
            "failed": failed,
            "successBytes": success_bytes,
            "endedAt": now_iso(),
        }
        self.store.finish_run(run_id, result)
        if events:
            events({"type": "completed", "result": result})
        return result

    @staticmethod
    def _preflight(items: List[Dict[str, Any]]) -> None:
        for item in items:
            source = Path(item["source_path"])
            target = Path(item["target_path"])
            if not source.exists():
                raise PlanChanged(str(source))
            if target.exists():
                raise PlanChanged(str(target))

    @staticmethod
    def _os_error_code(exc: OSError) -> str:
        if getattr(exc, "errno", None) == 28:
            return "DISK_FULL"
        if isinstance(exc, PermissionError):
            return "PERMISSION_DENIED"
        return "FILE_OPERATION_FAILED"

    def undo_preview(self, run_id: str) -> Dict[str, Any]:
        detail = self.store.run_detail(run_id)
        items = []
        for operation in reversed(detail["operations"]):
            if operation["state"] != "applied":
                continue
            current = Path(operation["target_path"])
            original = Path(operation["source_path"])
            after = operation.get("after") or {}
            if not current.exists():
                state = "missing"
                selected = False
                restore = original
            elif not same_fingerprint(current, after):
                state = "changed"
                selected = False
                restore = original
            elif original.exists():
                state = "rename"
                restore = self._restored_name(original)
                selected = True
            else:
                state = "ready"
                restore = original
                selected = True
            items.append(
                {
                    "operationId": operation["operation_id"],
                    "currentPath": str(current),
                    "restorePath": str(restore),
                    "size": after.get("size", 0),
                    "state": state,
                    "selected": selected,
                }
            )
        return {"runId": run_id, "items": items}

    def undo(self, run_id: str, operation_ids: List[str], events: EventCallback = None) -> Dict[str, Any]:
        preview = self.undo_preview(run_id)
        allowed = {item["operationId"]: item for item in preview["items"]}
        restored = failed = 0
        for operation_id in operation_ids:
            item = allowed.get(operation_id)
            if not item or item["state"] not in {"ready", "rename"}:
                failed += 1
                continue
            try:
                safe_move(Path(item["currentPath"]), Path(item["restorePath"]), uuid.uuid4().hex)
                self.store.mark_undone(operation_id, now_iso())
                restored += 1
                if events:
                    events({"type": "undoItem", "status": "undone", "item": item})
            except (OSError, EngineError) as exc:
                failed += 1
                if events:
                    events({"type": "undoItem", "status": "failed", "item": item, "detail": str(exc)})
        result = {"runId": run_id, "restored": restored, "failed": failed}
        if events:
            events({"type": "undoCompleted", "result": result})
        return result

    def restore_quarantine(
        self,
        quarantine_ids: List[str],
        destination_folder: Optional[str] = None,
        events: EventCallback = None,
    ) -> Dict[str, Any]:
        items = self.store.quarantine_items(quarantine_ids)
        restored = skipped = failed = 0
        occupied: set[str] = set()
        destination_root = Path(destination_folder).expanduser().absolute() if destination_folder else None
        for item in items:
            current = Path(item["quarantine_path"])
            if not same_fingerprint(current, item["fingerprint"]):
                skipped += 1
                continue
            wanted = destination_root / current.name if destination_root else Path(item["original_path"])
            target, _ = unique_destination(wanted, occupied)
            try:
                safe_move(current, target, uuid.uuid4().hex)
                self.store.mark_undone(item["operation_id"], now_iso())
                restored += 1
                if events:
                    events({"type": "quarantineRestore", "status": "restored", "path": str(target)})
            except (OSError, EngineError) as exc:
                failed += 1
                if events:
                    events({"type": "quarantineRestore", "status": "failed", "detail": str(exc)})
        return {"requested": len(quarantine_ids), "restored": restored, "skipped": skipped, "failed": failed}

    def move_quarantine_to_trash(self, quarantine_ids: List[str]) -> Dict[str, Any]:
        try:
            from send2trash import send2trash  # type: ignore
        except ImportError as exc:
            raise EngineError(
                "TRASH_UNAVAILABLE",
                "The system trash integration is not installed.",
            ) from exc
        moved = skipped = failed = 0
        for item in self.store.quarantine_items(quarantine_ids):
            path = Path(item["quarantine_path"])
            if not same_fingerprint(path, item["fingerprint"]):
                skipped += 1
                continue
            try:
                send2trash(str(path))
                self.store.mark_quarantine(item["quarantine_id"], "trashed")
                moved += 1
            except OSError:
                failed += 1
        return {"requested": len(quarantine_ids), "moved": moved, "skipped": skipped, "failed": failed}

    def recover_interrupted(self) -> Dict[str, int]:
        recovered = review = 0
        for operation in self.store.started_operations():
            source = Path(operation["source_path"])
            target = Path(operation["target_path"])
            timestamp = now_iso()
            if target.exists() and not source.exists():
                self.store.finish_operation(
                    operation["operation_id"], "applied", fingerprint(target), timestamp
                )
                recovered += 1
            else:
                detail = "source=%s target=%s" % (source.exists(), target.exists())
                self.store.finish_operation(
                    operation["operation_id"], "failed", None, timestamp,
                    "RECOVERY_REVIEW_REQUIRED", detail,
                )
                review += 1
        for run_id in self.store.running_run_ids():
            self.store.finish_recovered_run(run_id, now_iso())
        return {"recovered": recovered, "review": review}

    @staticmethod
    def _restored_name(path: Path) -> Path:
        base = path.with_name("%s(restored)%s" % (path.stem, path.suffix))
        candidate = base
        counter = 2
        while candidate.exists():
            candidate = path.with_name("%s(restored %d)%s" % (path.stem, counter, path.suffix))
            counter += 1
        return candidate
