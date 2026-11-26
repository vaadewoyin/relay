from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import ValidationError

from relay.domain import Conflict, HandoverReceipt, OperationalReport, Operator
from relay.notion.client import JSON, NotionAdapter, NotionError, Sources
from relay.notion.mapping import map_report, rich_text
from relay.notion.records import ImportResult, Publication, SyncStatus
from relay.service import InvalidInput, NotFound, RelayService, Store, require


@dataclass(frozen=True)
class Effect:
    source: UUID
    key: str
    properties: JSON

    @property
    def id(self) -> UUID:
        return uuid5(NAMESPACE_URL, f"relay:notion:{self.source}:{self.key}")


class NotionSync:
    def __init__(self, adapter: NotionAdapter, sources: Sources, store: Store):
        self.adapter = adapter
        self.sources = sources
        self.store = store
        self.service = RelayService(store)
        self.lock = Lock()

    def verify(self) -> None:
        for source in (
            self.sources.reports,
            self.sources.actions,
            self.sources.receipts,
        ):
            self.adapter.verify(source)

    def pull(self) -> ImportResult:
        counts = dict.fromkeys(("imported", "unchanged", "modified", "invalid"), 0)
        failures: dict[str, str] = {}
        ids = []
        network_failure = None
        try:
            for index, raw in enumerate(
                self.adapter.pages(self.sources.reports), start=1
            ):
                try:
                    command = map_report(raw)
                    with self.store.transaction() as tx:
                        known = tx.operation(command.operation_id) is not None
                    report = self.service.intake(command).report
                except Conflict:
                    counts["modified"] += 1
                    failures[str(index)] = "external_edit_requires_review"
                except (
                    ValidationError,
                    ValueError,
                    KeyError,
                    TypeError,
                    NotFound,
                    InvalidInput,
                ):
                    counts["invalid"] += 1
                    failures[str(index)] = "invalid_report"
                else:
                    ids.append(report.id)
                    counts["unchanged" if known else "imported"] += 1
        except NotionError as exc:
            network_failure = exc.code
        return ImportResult(
            **counts, failures=failures, report_ids=tuple(ids), failure=network_failure
        )

    def effects(self, receipt: HandoverReceipt) -> Iterator[Effect]:
        yield Effect(
            self.sources.receipts,
            str(receipt.id),
            {
                "Name": rich_text(f"Relay handover {str(receipt.id)[:8]}", "title"),
                "Accepted": {"date": {"start": receipt.accepted_at.isoformat()}},
                "Outcome": rich_text(
                    f"{len(receipt.transferred)} transferred, {len(receipt.outstanding)} outstanding."
                ),
                "Accepted By": rich_text(str(receipt.accepted_by)),
                "Outgoing Shift": rich_text(str(receipt.outgoing_shift_id)),
                "Incoming Shift": rich_text(str(receipt.incoming_shift_id)),
            },
        )
        with self.store.transaction() as tx:
            owner = require(tx, Operator, receipt.accepted_by)
            reports = {report.id: report for report in tx.all(OperationalReport)}
        for item in receipt.transferred:
            report = reports[item.report_id]
            yield Effect(
                self.sources.actions,
                f"{receipt.id}:{item.id}",
                {
                    "Name": rich_text(item.description, "title"),
                    "Action ID": rich_text(str(item.id)),
                    "Receipt ID": rich_text(str(receipt.id)),
                    "Owner": rich_text(owner.name),
                    "Owner ID": rich_text(str(receipt.accepted_by)),
                    "Status": rich_text(str(item.status)),
                    "Version": {"number": item.version},
                    "Source": {
                        "url": str(report.source_url) if report.source_url else None
                    },
                },
            )

    def status(self, receipt: HandoverReceipt) -> SyncStatus:
        effects = tuple(self.effects(receipt))
        with self.store.transaction() as tx:
            states = [tx.get(Publication, effect.id) for effect in effects]
        if all(item and item.state == "synced" for item in states):
            return "synced"
        if any(item and item.state == "uncertain" for item in states):
            return "uncertain"
        return "pending"

    def publish(self, receipt: HandoverReceipt) -> tuple[Publication, ...]:
        # Serialize pulls of the same outbox within this demonstration process.
        with self.lock:
            return tuple(self._publish(effect) for effect in self.effects(receipt))

    def _write(
        self,
        effect: Effect,
        state: SyncStatus,
        *,
        remote_id: UUID | None = None,
        failure: str | None = None,
    ) -> Publication:
        record = Publication(
            id=effect.id,
            state=state,
            remote_id=remote_id,
            failure=failure,
            updated_at=datetime.now(UTC),
        )
        with self.store.transaction(write=True) as tx:
            if tx.get(Publication, effect.id):
                tx.update(record)
            else:
                tx.insert(record)
        return record

    def _publish(self, effect: Effect) -> Publication:
        with self.store.transaction() as tx:
            previous = tx.get(Publication, effect.id)
        if previous and previous.state == "synced":
            return previous
        uncertain = bool(previous and previous.state == "uncertain")
        try:
            matches = list(self.adapter.pages(effect.source, effect.key))
            if len(matches) > 1:
                return self._write(effect, "uncertain", failure="duplicate_remote_key")
            if matches:
                return self._write(
                    effect, "synced", remote_id=UUID(str(matches[0]["id"]))
                )
            if uncertain:
                return self._write(
                    effect, "uncertain", failure="awaiting_remote_reconciliation"
                )
        except NotionError as exc:
            return self._write(
                effect, "uncertain" if uncertain else "pending", failure=exc.code
            )
        except (ValueError, KeyError):
            return self._write(effect, "uncertain", failure="invalid_remote_record")

        # Persist the unknown-outcome state before sending a create request.
        self._write(effect, "uncertain")
        try:
            created = self.adapter.create(
                effect.source,
                {
                    **effect.properties,
                    "Relay ID": rich_text(effect.key),
                    "Sync Status": rich_text("Synced"),
                },
            )
            return self._write(effect, "synced", remote_id=UUID(str(created["id"])))
        except NotionError as exc:
            return self._write(
                effect,
                "uncertain" if exc.possibly_created else "pending",
                failure=exc.code,
            )
        except (KeyError, ValueError):
            return self._write(effect, "uncertain", failure="invalid_remote_record")
