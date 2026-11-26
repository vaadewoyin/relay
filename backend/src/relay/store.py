import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from uuid import UUID

from relay.domain import (
    ActionItem,
    Asset,
    Handover,
    HandoverReceipt,
    IntegrityFinding,
    OperationalReport,
    Operator,
    Record,
    ReviewDecision,
    Shift,
)
from relay.intelligence.contracts import Execution
from relay.notion.records import Publication

# SQL identifiers come exclusively from this mapping.
TABLES: dict[type[Record], str] = {
    Operator: "operators",
    Shift: "shifts",
    Asset: "assets",
    OperationalReport: "reports",
    ActionItem: "actions",
    IntegrityFinding: "findings",
    ReviewDecision: "reviews",
    Handover: "handovers",
    HandoverReceipt: "receipts",
    Execution: "ai_executions",
    Publication: "notion_publications",
}


class SQLiteSession:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def get[T: Record](self, model: type[T], record_id: UUID) -> T | None:
        row = self.connection.execute(
            f"SELECT payload FROM {TABLES[model]} WHERE id = ?", (str(record_id),)
        ).fetchone()
        return model.model_validate_json(row[0]) if row else None

    def all[T: Record](self, model: type[T]) -> list[T]:
        rows = self.connection.execute(
            f"SELECT payload FROM {TABLES[model]} ORDER BY id"
        )
        return [model.model_validate_json(payload) for (payload,) in rows]

    def insert(self, record: Record, *, ignore_duplicate: bool = False) -> None:
        on_conflict = " ON CONFLICT(id) DO NOTHING" if ignore_duplicate else ""
        self.connection.execute(
            f"INSERT INTO {TABLES[type(record)]} (id, payload) VALUES (?, ?){on_conflict}",
            (str(record.id), record.model_dump_json()),
        )

    def update(self, record: Record) -> None:
        result = self.connection.execute(
            f"UPDATE {TABLES[type(record)]} SET payload = ? WHERE id = ?",
            (record.model_dump_json(), str(record.id)),
        )
        if result.rowcount != 1:
            raise RuntimeError("Expected to update one persisted record.")

    def operation(self, operation_id: UUID) -> tuple[str, str, str] | None:
        row = self.connection.execute(
            "SELECT scope, fingerprint, response FROM operations WHERE id = ?",
            (str(operation_id),),
        ).fetchone()
        return (row[0], row[1], row[2]) if row else None

    def record_operation(
        self, operation_id: UUID, scope: str, fingerprint: str, response: str
    ) -> None:
        self.connection.execute(
            "INSERT INTO operations VALUES (?, ?, ?, ?)",
            (str(operation_id), scope, fingerprint, response),
        )


class SQLiteStore:
    def __init__(self, path: Path):
        self.path = path

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("BEGIN IMMEDIATE")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2, 3):
                raise RuntimeError(
                    f"Unsupported Relay database schema version {version}."
                )
            if version == 0:
                for table in TABLES.values():
                    connection.execute(
                        f"CREATE TABLE {table} (id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
                    )
                connection.execute(
                    """CREATE TABLE operations (
                        id TEXT PRIMARY KEY, scope TEXT NOT NULL,
                        fingerprint TEXT NOT NULL, response TEXT NOT NULL
                    )"""
                )
            if version == 1:
                connection.execute(
                    "CREATE TABLE ai_executions (id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
                )
            if version in (1, 2):
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS notion_publications (id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
                )
            if version < 3:
                connection.execute("PRAGMA user_version = 3")

    @contextmanager
    def transaction(self, *, write: bool = False) -> Iterator[SQLiteSession]:
        with closing(sqlite3.connect(self.path, timeout=5)) as connection, connection:
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield SQLiteSession(connection)
