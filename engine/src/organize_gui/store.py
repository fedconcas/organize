import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


SCHEMA_VERSION = 3

# Presets that were removed from the app. Profiles that use them can no longer be planned.
REMOVED_PRESETS = ("similar-photos",)


class Store:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._local = threading.local()
        self.migrate()

    def connection(self) -> sqlite3.Connection:
        connection = getattr(self._local, "connection", None)
        if connection is None:
            connection = sqlite3.connect(str(self.path), timeout=30)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("PRAGMA foreign_keys=ON")
            self._local.connection = connection
        return connection

    def migrate(self) -> None:
        db = self.connection()
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS profiles (
                profile_id TEXT PRIMARY KEY,
                profile_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS saved_profiles (
                profile_id TEXT PRIMARY KEY,
                profile_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS plans (
                plan_id TEXT PRIMARY KEY,
                profile_json TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                summary_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS plan_items (
                item_id TEXT PRIMARY KEY,
                plan_id TEXT NOT NULL REFERENCES plans(plan_id) ON DELETE CASCADE,
                seq INTEGER NOT NULL,
                group_id TEXT,
                operation TEXT NOT NULL,
                source_path TEXT NOT NULL,
                target_path TEXT,
                size INTEGER NOT NULL,
                fingerprint_json TEXT NOT NULL,
                selected INTEGER NOT NULL,
                status TEXT NOT NULL,
                warning_code TEXT,
                reason TEXT,
                metadata_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_plan_items_plan ON plan_items(plan_id, seq);
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                plan_id TEXT NOT NULL,
                profile_json TEXT NOT NULL,
                status TEXT NOT NULL,
                total INTEGER NOT NULL,
                success INTEGER NOT NULL DEFAULT 0,
                skipped INTEGER NOT NULL DEFAULT 0,
                failed INTEGER NOT NULL DEFAULT 0,
                started_at TEXT NOT NULL,
                ended_at TEXT
            );
            CREATE TABLE IF NOT EXISTS operations (
                operation_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL REFERENCES runs(run_id),
                item_id TEXT NOT NULL,
                seq INTEGER NOT NULL,
                operation TEXT NOT NULL,
                source_path TEXT NOT NULL,
                target_path TEXT NOT NULL,
                before_json TEXT NOT NULL,
                after_json TEXT,
                state TEXT NOT NULL,
                error_code TEXT,
                error_detail TEXT,
                started_at TEXT NOT NULL,
                applied_at TEXT,
                undone_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_operations_run ON operations(run_id, seq);
            CREATE TABLE IF NOT EXISTS quarantine_items (
                quarantine_id TEXT PRIMARY KEY,
                operation_id TEXT NOT NULL,
                original_path TEXT NOT NULL,
                quarantine_path TEXT NOT NULL,
                reason TEXT NOT NULL,
                size INTEGER NOT NULL,
                fingerprint_json TEXT NOT NULL,
                quarantined_at TEXT NOT NULL,
                retention_until TEXT NOT NULL,
                status TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value_json TEXT NOT NULL
            );
            """
        )
        applied = {row[0] for row in db.execute("SELECT version FROM schema_migrations")}
        if 3 not in applied:
            self._drop_removed_preset_profiles(db)
        db.executemany(
            "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, datetime('now'))",
            [(version,) for version in range(2, SCHEMA_VERSION + 1)],
        )
        db.commit()

    @staticmethod
    def _drop_removed_preset_profiles(db: sqlite3.Connection) -> None:
        """Version 3: the similar-photos preset was removed; forget profiles and open plans that use it."""
        for table in ("saved_profiles", "profiles"):
            rows = db.execute("SELECT profile_id, profile_json FROM %s" % table).fetchall()
            for row in rows:
                try:
                    preset = json.loads(row[1]).get("presetType")
                except (ValueError, AttributeError):
                    continue
                if preset in REMOVED_PRESETS:
                    db.execute("DELETE FROM %s WHERE profile_id=?" % table, (row[0],))
        for row in db.execute("SELECT plan_id, profile_json FROM plans WHERE status='ready'").fetchall():
            try:
                preset = json.loads(row[1]).get("presetType")
            except (ValueError, AttributeError):
                continue
            if preset in REMOVED_PRESETS:
                db.execute("UPDATE plans SET status='expired' WHERE plan_id=?", (row[0],))

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _decode_row(row: sqlite3.Row, json_fields: Iterable[str]) -> Dict[str, Any]:
        result = dict(row)
        for field in json_fields:
            if result.get(field) is not None:
                result[field[:-5] if field.endswith("_json") else field] = json.loads(result.pop(field))
        return result

    def save_profile(self, profile: Dict[str, Any], now: str) -> None:
        self.connection().execute(
            """
            INSERT INTO profiles(profile_id, profile_json, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(profile_id) DO UPDATE SET profile_json=excluded.profile_json, updated_at=excluded.updated_at
            """,
            (profile["id"], self._json(profile), now, now),
        )
        self.connection().commit()

    def saved_profiles(self) -> List[Dict[str, Any]]:
        return [json.loads(row[0]) for row in self.connection().execute(
            "SELECT profile_json FROM saved_profiles ORDER BY updated_at DESC"
        )]

    def save_named_profile(self, profile: Dict[str, Any], now: str) -> None:
        with self.connection() as db:
            db.execute("INSERT OR REPLACE INTO saved_profiles VALUES (?, ?, ?)",
                       (profile["id"], self._json(profile), now))

    def delete_named_profile(self, profile_id: str) -> None:
        with self.connection() as db:
            db.execute("DELETE FROM saved_profiles WHERE profile_id=?", (profile_id,))

    def last_profile(self) -> Optional[Dict[str, Any]]:
        row = self.connection().execute(
            "SELECT profile_json FROM profiles ORDER BY updated_at DESC LIMIT 1"
        ).fetchone()
        return json.loads(row[0]) if row else None

    def save_plan(
        self,
        plan_id: str,
        profile: Dict[str, Any],
        created_at: str,
        expires_at: str,
        summary: Dict[str, Any],
        items: List[Dict[str, Any]],
    ) -> None:
        db = self.connection()
        with db:
            db.execute(
                "INSERT INTO plans VALUES (?, ?, 'ready', ?, ?, ?)",
                (plan_id, self._json(profile), created_at, expires_at, self._json(summary)),
            )
            db.executemany(
                """
                INSERT INTO plan_items VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        item["itemId"], plan_id, item["sequence"], item.get("groupId"),
                        item["operation"], item["sourcePath"], item.get("targetPath"),
                        item["size"], self._json(item["fingerprint"]),
                        1 if item.get("selected", True) else 0, item.get("status", "planned"),
                        item.get("warningCode"), item.get("reason"), self._json(item.get("metadata", {})),
                    )
                    for item in items
                ],
            )

    def get_plan(self, plan_id: str) -> Dict[str, Any]:
        db = self.connection()
        plan = db.execute("SELECT * FROM plans WHERE plan_id=?", (plan_id,)).fetchone()
        if plan is None:
            raise KeyError(plan_id)
        result = self._decode_row(plan, ("profile_json", "summary_json"))
        rows = db.execute(
            "SELECT * FROM plan_items WHERE plan_id=? ORDER BY seq", (plan_id,)
        ).fetchall()
        items = []
        for row in rows:
            item = self._decode_row(row, ("fingerprint_json", "metadata_json"))
            item["selected"] = bool(item["selected"])
            items.append(item)
        result["items"] = items
        return result

    def select_items(self, plan_id: str, selected_ids: List[str]) -> None:
        db = self.connection()
        with db:
            db.execute("UPDATE plan_items SET selected=0 WHERE plan_id=?", (plan_id,))
            db.executemany(
                "UPDATE plan_items SET selected=1 WHERE plan_id=? AND item_id=? AND status='planned'",
                [(plan_id, item_id) for item_id in selected_ids],
            )
            plan = self.get_plan(plan_id)
            summary = plan["summary"]
            chosen = [item for item in plan["items"] if item["selected"]]
            summary.update(selected=len(chosen), selectedBytes=sum(item["size"] for item in chosen),
                           move=sum(item["operation"] == "move" for item in chosen),
                           quarantine=sum(item["operation"] == "quarantine" for item in chosen))
            db.execute("UPDATE plans SET summary_json=? WHERE plan_id=?", (self._json(summary), plan_id))

    def create_run(self, run: Dict[str, Any]) -> None:
        db = self.connection()
        with db:
            db.execute(
                "UPDATE plans SET status='executing' WHERE plan_id=?",
                (run["planId"],),
            )
            db.execute(
                """INSERT INTO runs(run_id, plan_id, profile_json, status, total, started_at)
                VALUES (?, ?, ?, 'running', ?, ?)""",
                (
                    run["runId"], run["planId"], self._json(run["profile"]),
                    run["total"], run["startedAt"],
                ),
            )

    def start_operation(self, operation: Dict[str, Any]) -> None:
        self.connection().execute(
            """INSERT INTO operations(operation_id, run_id, item_id, seq, operation,
            source_path, target_path, before_json, state, started_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'started', ?)""",
            (
                operation["operationId"], operation["runId"], operation["itemId"],
                operation["sequence"], operation["operation"], operation["sourcePath"],
                operation["targetPath"], self._json(operation["before"]), operation["startedAt"],
            ),
        )
        self.connection().commit()

    def finish_operation(
        self,
        operation_id: str,
        state: str,
        after: Optional[Dict[str, Any]],
        timestamp: str,
        error_code: Optional[str] = None,
        error_detail: Optional[str] = None,
    ) -> None:
        self.connection().execute(
            """UPDATE operations SET state=?, after_json=?, applied_at=?, error_code=?, error_detail=?
            WHERE operation_id=?""",
            (
                state,
                self._json(after) if after is not None else None,
                timestamp if state == "applied" else None,
                error_code,
                error_detail,
                operation_id,
            ),
        )
        self.connection().commit()

    def add_quarantine(self, item: Dict[str, Any]) -> None:
        self.connection().execute(
            """INSERT INTO quarantine_items VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')""",
            (
                item["quarantineId"], item["operationId"], item["originalPath"],
                item["quarantinePath"], item["reason"], item["size"],
                self._json(item["fingerprint"]), item["quarantinedAt"], item["retentionUntil"],
            ),
        )
        self.connection().commit()

    def finish_run(self, run_id: str, result: Dict[str, Any]) -> None:
        db = self.connection()
        with db:
            db.execute(
                """UPDATE runs SET status=?, success=?, skipped=?, failed=?, ended_at=? WHERE run_id=?""",
                (
                    result["status"], result["success"], result["skipped"],
                    result["failed"], result["endedAt"], run_id,
                ),
            )
            db.execute(
                "UPDATE plans SET status='completed' WHERE plan_id=(SELECT plan_id FROM runs WHERE run_id=?)",
                (run_id,),
            )

    def list_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        rows = self.connection().execute(
            """SELECT runs.*, (SELECT COUNT(*) FROM operations WHERE operations.run_id=runs.run_id
            AND state='applied') AS undoable_count FROM runs ORDER BY started_at DESC LIMIT ?""", (limit,)
        ).fetchall()
        return [self._decode_row(row, ("profile_json",)) for row in rows]

    def run_detail(self, run_id: str) -> Dict[str, Any]:
        db = self.connection()
        row = db.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        result = self._decode_row(row, ("profile_json",))
        ops = db.execute(
            "SELECT * FROM operations WHERE run_id=? ORDER BY seq", (run_id,)
        ).fetchall()
        result["operations"] = [
            self._decode_row(op, ("before_json", "after_json")) for op in ops
        ]
        return result

    def list_quarantine(self) -> List[Dict[str, Any]]:
        rows = self.connection().execute(
            "SELECT * FROM quarantine_items WHERE status='active' ORDER BY quarantined_at DESC"
        ).fetchall()
        return [self._decode_row(row, ("fingerprint_json",)) for row in rows]

    def quarantine_items(self, quarantine_ids: List[str]) -> List[Dict[str, Any]]:
        if not quarantine_ids:
            return []
        placeholders = ",".join("?" for _ in quarantine_ids)
        rows = self.connection().execute(
            "SELECT * FROM quarantine_items WHERE status='active' AND quarantine_id IN (%s)"
            % placeholders,
            quarantine_ids,
        ).fetchall()
        decoded = [self._decode_row(row, ("fingerprint_json",)) for row in rows]
        order = {item_id: index for index, item_id in enumerate(quarantine_ids)}
        return sorted(decoded, key=lambda item: order[item["quarantine_id"]])

    def mark_quarantine(self, quarantine_id: str, status: str) -> None:
        self.connection().execute(
            "UPDATE quarantine_items SET status=? WHERE quarantine_id=?",
            (status, quarantine_id),
        )
        self.connection().commit()

    def started_operations(self) -> List[Dict[str, Any]]:
        rows = self.connection().execute(
            "SELECT * FROM operations WHERE state='started' ORDER BY started_at"
        ).fetchall()
        return [self._decode_row(row, ("before_json", "after_json")) for row in rows]

    def running_run_ids(self) -> List[str]:
        rows = self.connection().execute(
            "SELECT run_id FROM runs WHERE status='running' ORDER BY started_at"
        ).fetchall()
        return [row["run_id"] for row in rows]

    def finish_recovered_run(self, run_id: str, timestamp: str) -> None:
        db = self.connection()
        run = db.execute("SELECT total FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if run is None:
            return
        counts = {
            row["state"]: row["count"]
            for row in db.execute(
                "SELECT state, COUNT(*) AS count FROM operations WHERE run_id=? GROUP BY state",
                (run_id,),
            ).fetchall()
        }
        success = int(counts.get("applied", 0))
        failed = int(counts.get("failed", 0))
        skipped = max(int(run["total"]) - success - failed, 0)
        status = "partial" if success else "failed"
        with db:
            db.execute(
                "UPDATE runs SET status=?, success=?, skipped=?, failed=?, ended_at=? WHERE run_id=?",
                (status, success, skipped, failed, timestamp, run_id),
            )
            db.execute(
                "UPDATE plans SET status='completed' WHERE plan_id=(SELECT plan_id FROM runs WHERE run_id=?)",
                (run_id,),
            )

    def mark_undone(self, operation_id: str, timestamp: str) -> None:
        db = self.connection()
        with db:
            db.execute(
                "UPDATE operations SET state='undone', undone_at=? WHERE operation_id=?",
                (timestamp, operation_id),
            )
            db.execute(
                "UPDATE quarantine_items SET status='restored' WHERE operation_id=?",
                (operation_id,),
            )

    def get_setting(self, key: str, default: Any = None) -> Any:
        row = self.connection().execute(
            "SELECT value_json FROM settings WHERE key=?", (key,)
        ).fetchone()
        return default if row is None else json.loads(row["value_json"])

    def set_setting(self, key: str, value: Any) -> None:
        self.connection().execute(
            """INSERT INTO settings(key, value_json) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json""",
            (key, self._json(value)),
        )
        self.connection().commit()

    def database_health(self) -> Dict[str, Any]:
        result = self.connection().execute("PRAGMA integrity_check").fetchone()
        return {
            "integrity": result[0] if result is not None else "unknown",
            "schemaVersion": SCHEMA_VERSION,
        }

    def recent_failures(self, limit: int = 20) -> List[Dict[str, Any]]:
        rows = self.connection().execute(
            """SELECT operation, error_code, error_detail, started_at
            FROM operations WHERE state='failed' ORDER BY started_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]
