import hashlib
import json
from collections.abc import Callable, Iterable
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from typing import Annotated, Protocol
from uuid import UUID, uuid4

from pydantic import AwareDatetime, Field, HttpUrl

from relay import rules
from relay.domain import (
    ActionItem,
    ActionSnapshot,
    ActionStatus,
    Asset,
    AssetStatus,
    Conflict,
    Contract,
    Forbidden,
    Handover,
    HandoverReceipt,
    IntegrityFinding,
    Name,
    OperationalReport,
    Operator,
    Record,
    ReviewDecision,
    ReviewOutcome,
    ReviewStatus,
    Shift,
    Text,
    Version,
)


class Session(Protocol):
    def get[T: Record](self, model: type[T], record_id: UUID) -> T | None: ...
    def all[T: Record](self, model: type[T]) -> list[T]: ...
    def insert(self, record: Record, *, ignore_duplicate: bool = False) -> None: ...
    def update(self, record: Record) -> None: ...
    def operation(self, operation_id: UUID) -> tuple[str, str, str] | None: ...
    def record_operation(
        self, operation_id: UUID, scope: str, fingerprint: str, response: str
    ) -> None: ...


class Store(Protocol):
    def transaction(
        self, *, write: bool = False
    ) -> AbstractContextManager[Session]: ...


class NotFound(Exception):
    pass


class InvalidInput(Exception):
    pass


class Command(Contract):
    operation_id: UUID


class NewAction(Contract):
    description: Text
    owner_id: UUID | None = None
    due_at: AwareDatetime | None = None


class ReportIntake(Command):
    source_ref: Name
    source_url: HttpUrl | None = None
    source_revision: AwareDatetime | None = None
    shift_id: UUID
    author_id: UUID
    asset_id: UUID
    observed_at: AwareDatetime
    text: Text
    asset_status: AssetStatus | None = None
    synthetic: bool = False
    actions: Annotated[tuple[NewAction, ...], Field(max_length=25)] = ()


class ReportDetails(Contract):
    report: OperationalReport
    actions: tuple[ActionItem, ...]


class ActionUpdate(Command):
    actor_id: UUID
    expected_version: Version
    status: ActionStatus


class ReviewFinding(Command):
    reviewer_id: UUID
    outcome: ReviewOutcome
    reason: Text


class PreviewHandover(Command):
    outgoing_shift_id: UUID
    incoming_shift_id: UUID
    actor_id: UUID


class AcceptHandover(Command):
    actor_id: UUID
    expected_version: Version
    confirmed: bool = Field(strict=True)


def require[T: Record](tx: Session, model: type[T], record_id: UUID) -> T:
    record = tx.get(model, record_id)
    if record is None:
        raise NotFound(f"{model.__name__} does not exist.")
    return record


def remember_findings(tx: Session, findings: Iterable[IntegrityFinding | None]) -> None:
    for finding in findings:
        if finding is not None:
            tx.insert(finding, ignore_duplicate=True)


def fingerprint(command: Command) -> str:
    fields = command.model_dump(mode="json")
    if isinstance(command, ReportIntake):
        # Preserve replay fingerprints written before source provenance was added.
        for key in ("source_url", "source_revision"):
            if fields[key] is None:
                fields.pop(key)
    payload = json.dumps(fields, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def replay[T: Contract](
    tx: Session, scope: str, command: Command, response_model: type[T]
) -> T | None:
    previous = tx.operation(command.operation_id)
    if previous is None:
        return None
    previous_scope, previous_fingerprint, response = previous
    if (scope, fingerprint(command)) != (previous_scope, previous_fingerprint):
        raise Conflict(
            "operation_id_reused",
            "Operation ID was already used for a different request.",
        )
    return response_model.model_validate_json(response)


def complete[T: Contract](tx: Session, scope: str, command: Command, response: T) -> T:
    tx.record_operation(
        command.operation_id, scope, fingerprint(command), response.model_dump_json()
    )
    return response


class RelayService:
    def __init__(
        self, store: Store, clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    ):
        self.store = store
        self.clock = clock

    def intake(self, command: ReportIntake) -> ReportDetails:
        scope = "report.intake"
        with self.store.transaction(write=True) as tx:
            if previous := replay(tx, scope, command, ReportDetails):
                return previous
            shift = require(tx, Shift, command.shift_id)
            require(tx, Operator, command.author_id)
            require(tx, Asset, command.asset_id)
            if not shift.starts_at <= command.observed_at < shift.ends_at:
                raise InvalidInput(
                    "Observation time must fall within the report's shift."
                )
            now = self.clock()
            report = OperationalReport(
                id=uuid4(),
                received_at=now,
                **command.model_dump(exclude={"operation_id", "actions"}),
            )
            previous_reports = tx.all(OperationalReport)
            tx.insert(report)
            for previous_report in previous_reports:
                remember_findings(
                    tx,
                    (
                        rules.duplicate_report(report, previous_report, now),
                        rules.contradictory_status(report, previous_report, now),
                    ),
                )
            actions = []
            for draft in command.actions:
                if draft.owner_id is not None:
                    require(tx, Operator, draft.owner_id)
                action = ActionItem(
                    id=uuid4(),
                    report_id=report.id,
                    shift_id=shift.id,
                    updated_at=now,
                    **draft.model_dump(),
                )
                tx.insert(action)
                actions.append(action)
                remember_findings(
                    tx,
                    (
                        rules.missing_owner(action, report, now),
                        rules.overdue_action(action, report, now),
                    ),
                )
            return complete(
                tx, scope, command, ReportDetails(report=report, actions=tuple(actions))
            )

    def report(self, report_id: UUID) -> ReportDetails:
        with self.store.transaction() as tx:
            report = require(tx, OperationalReport, report_id)
            actions = tuple(
                item for item in tx.all(ActionItem) if item.report_id == report_id
            )
            return ReportDetails(report=report, actions=actions)

    def update_action(self, action_id: UUID, command: ActionUpdate) -> ActionItem:
        scope = f"action.update:{action_id}"
        with self.store.transaction(write=True) as tx:
            if previous := replay(tx, scope, command, ActionItem):
                return previous
            action = require(tx, ActionItem, action_id)
            shift = require(tx, Shift, action.shift_id)
            if command.actor_id != (action.owner_id or shift.operator_id):
                raise Forbidden(
                    "Only the owner or the custodian of unassigned work may update it."
                )
            now = self.clock()
            source = require(tx, OperationalReport, action.report_id)
            stale = rules.stale_version(
                action.id, command.expected_version, action.version, (source,), now
            )
            if stale is None:
                updated = action.transition(command.status, now)
                tx.update(updated)
                return complete(tx, scope, command, updated)
            remember_findings(tx, (stale,))
        raise Conflict("stale_version", "Action changed. Refresh and retry.")

    def findings(self) -> list[IntegrityFinding]:
        with self.store.transaction() as tx:
            return sorted(
                tx.all(IntegrityFinding), key=lambda item: (item.created_at, item.id)
            )

    def finding(self, finding_id: UUID) -> IntegrityFinding:
        return self.get(IntegrityFinding, finding_id)

    def review(self, finding_id: UUID, command: ReviewFinding) -> ReviewDecision:
        scope = f"finding.review:{finding_id}"
        with self.store.transaction(write=True) as tx:
            if previous := replay(tx, scope, command, ReviewDecision):
                return previous
            require(tx, Operator, command.reviewer_id)
            finding = require(tx, IntegrityFinding, finding_id)
            if finding.review_status != ReviewStatus.PENDING:
                raise Conflict(
                    "finding_already_reviewed", "This finding already has a review."
                )
            decision = ReviewDecision(
                id=uuid4(),
                finding_id=finding.id,
                reviewer_id=command.reviewer_id,
                outcome=command.outcome,
                reason=command.reason,
                decided_at=self.clock(),
            )
            tx.update(
                finding.model_copy(
                    update={"review_status": ReviewStatus(command.outcome)}
                )
            )
            tx.insert(decision)
            return complete(tx, scope, command, decision)

    def preview(self, command: PreviewHandover) -> Handover:
        scope = "handover.preview"
        with self.store.transaction(write=True) as tx:
            if previous := replay(tx, scope, command, Handover):
                return previous
            outgoing = require(tx, Shift, command.outgoing_shift_id)
            incoming = require(tx, Shift, command.incoming_shift_id)
            if command.actor_id != outgoing.operator_id:
                raise Forbidden("Only the outgoing operator can prepare this handover.")
            if (
                incoming.starts_at != outgoing.ends_at
                or incoming.operator_id == outgoing.operator_id
            ):
                raise InvalidInput(
                    "Handover requires consecutive shifts with different operators."
                )
            actions = self._unresolved(tx, outgoing)
            snapshot = self._snapshot(actions, outgoing)
            if not snapshot:
                raise Conflict(
                    "no_unresolved_actions",
                    "The outgoing shift has no unresolved work.",
                )
            now = self.clock()
            for action in actions:
                source = require(tx, OperationalReport, action.report_id)
                remember_findings(
                    tx,
                    (
                        rules.overdue_action(action, source, now),
                        rules.unresolved_responsibility(
                            action, source, outgoing.operator_id, now
                        ),
                    ),
                )
            handover = Handover(
                id=uuid4(),
                outgoing_shift_id=outgoing.id,
                incoming_shift_id=incoming.id,
                outgoing_operator_id=outgoing.operator_id,
                incoming_operator_id=incoming.operator_id,
                actions=snapshot,
                created_at=now,
            )
            tx.insert(handover)
            return complete(tx, scope, command, handover)

    def accept(self, handover_id: UUID, command: AcceptHandover) -> HandoverReceipt:
        scope = f"handover.accept:{handover_id}"
        with self.store.transaction(write=True) as tx:
            if previous := replay(tx, scope, command, HandoverReceipt):
                return previous
            handover = require(tx, Handover, handover_id)
            if not command.confirmed:
                raise InvalidInput("Acceptance requires explicit confirmation.")
            accepted = handover.accept(command.actor_id)
            outgoing = require(tx, Shift, handover.outgoing_shift_id)
            incoming = require(tx, Shift, handover.incoming_shift_id)
            actions = self._unresolved(tx, outgoing)
            now = self.clock()
            current_snapshot = self._snapshot(actions, outgoing)
            changed = current_snapshot != handover.actions
            if changed or command.expected_version != handover.version:
                sources = tuple(
                    dict.fromkeys(
                        item.report_id
                        for item in (*handover.actions, *current_snapshot)
                    )
                )
                remember_findings(
                    tx,
                    (
                        rules.stale_version(
                            handover.id,
                            command.expected_version,
                            handover.version,
                            tuple(
                                require(tx, OperationalReport, report_id)
                                for report_id in sources
                            ),
                            now,
                            snapshot_changed=changed,
                        ),
                    ),
                )
            else:
                if not any(item.transferable for item in handover.actions):
                    raise Conflict(
                        "no_transferable_actions",
                        "No unresolved work is owned by the outgoing operator.",
                    )
                transferred = []
                outstanding = []
                for action in actions:
                    if action.owner_id == outgoing.operator_id:
                        updated = action.transfer(outgoing, incoming, now)
                        tx.update(updated)
                        transferred.append(updated)
                    else:
                        outstanding.append(action)
                receipt = HandoverReceipt(
                    id=uuid4(),
                    handover_id=handover.id,
                    outgoing_shift_id=outgoing.id,
                    incoming_shift_id=incoming.id,
                    accepted_by=command.actor_id,
                    accepted_at=now,
                    transferred=tuple(transferred),
                    outstanding=tuple(outstanding),
                )
                tx.update(accepted)
                tx.insert(receipt)
                return complete(tx, scope, command, receipt)
        raise Conflict(
            "stale_version", "Handover changed. Create and review a fresh preview."
        )

    def get[T: Record](self, model: type[T], record_id: UUID) -> T:
        with self.store.transaction() as tx:
            return require(tx, model, record_id)

    @staticmethod
    def _unresolved(tx: Session, shift: Shift) -> list[ActionItem]:
        return [
            item
            for item in tx.all(ActionItem)
            if item.shift_id == shift.id and item.status.unresolved
        ]

    @staticmethod
    def _snapshot(
        actions: list[ActionItem], shift: Shift
    ) -> tuple[ActionSnapshot, ...]:
        return tuple(
            ActionSnapshot(
                action_id=item.id,
                report_id=item.report_id,
                description=item.description,
                owner_id=item.owner_id,
                status=item.status,
                due_at=item.due_at,
                version=item.version,
                transferable=item.owner_id == shift.operator_id,
            )
            for item in actions
        )
