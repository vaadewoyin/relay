from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

type Name = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)
]
type Text = Annotated[
    str, StringConstraints(min_length=1, max_length=4000, pattern=r"\S")
]
type Version = Annotated[int, Field(strict=True, ge=1)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Record(Contract):
    id: UUID


class Operator(Record):
    name: Name


class Shift(Record):
    operator_id: UUID
    starts_at: AwareDatetime
    ends_at: AwareDatetime

    @model_validator(mode="after")
    def chronological(self) -> Self:
        if self.ends_at <= self.starts_at:
            raise ValueError("Shift must end after it starts.")
        return self


class Asset(Record):
    name: Name


class AssetStatus(StrEnum):
    OPERATIONAL = "operational"
    FAULTED = "faulted"
    OUT_OF_SERVICE = "out_of_service"


class OperationalReport(Record):
    source_ref: Name
    shift_id: UUID
    author_id: UUID
    asset_id: UUID
    observed_at: AwareDatetime
    text: Text
    asset_status: AssetStatus | None = None
    synthetic: bool = False
    received_at: AwareDatetime


class ActionStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"

    @property
    def unresolved(self) -> bool:
        return self != self.RESOLVED


class Conflict(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class Forbidden(Exception):
    pass


class ActionItem(Record):
    report_id: UUID
    shift_id: UUID
    description: Text
    owner_id: UUID | None = None
    due_at: AwareDatetime | None = None
    status: ActionStatus = ActionStatus.OPEN
    updated_at: AwareDatetime
    version: Version = 1

    def transition(self, target: ActionStatus, now: AwareDatetime) -> Self:
        allowed = {
            ActionStatus.OPEN: {ActionStatus.IN_PROGRESS, ActionStatus.RESOLVED},
            ActionStatus.IN_PROGRESS: {ActionStatus.RESOLVED},
            ActionStatus.RESOLVED: set(),
        }
        if target not in allowed[self.status]:
            raise Conflict(
                "invalid_action_transition", "Action status cannot move to that state."
            )
        return self.model_copy(
            update={"status": target, "version": self.version + 1, "updated_at": now}
        )

    def transfer(self, outgoing: Shift, incoming: Shift, now: AwareDatetime) -> Self:
        if (
            self.shift_id != outgoing.id
            or self.owner_id != outgoing.operator_id
            or not self.status.unresolved
        ):
            raise Conflict(
                "action_not_transferable", "Action is outside the authorized transfer."
            )
        return self.model_copy(
            update={
                "shift_id": incoming.id,
                "owner_id": incoming.operator_id,
                "version": self.version + 1,
                "updated_at": now,
            }
        )


class EvidenceReference(Contract):
    report_id: UUID
    source_ref: Name
    quote: Text

    @classmethod
    def from_report(cls, report: OperationalReport) -> Self:
        return cls(report_id=report.id, source_ref=report.source_ref, quote=report.text)


class FindingType(StrEnum):
    MISSING_OWNER = "missing_owner"
    OVERDUE_ACTION = "overdue_action"
    DUPLICATE_REPORT = "duplicate_report"
    STALE_VERSION = "stale_version"
    UNRESOLVED_RESPONSIBILITY = "unresolved_responsibility"
    CONTRADICTORY_ASSET_STATUS = "contradictory_asset_status"


class SemanticKind(StrEnum):
    CONTRADICTION = "semantic_contradiction"
    UNSUPPORTED_COMPLETION = "unsupported_completion"
    AMBIGUOUS_OWNERSHIP = "ambiguous_ownership"
    MISSING_CONTEXT = "missing_operational_context"
    SAFETY_CONCERN = "unresolved_safety_concern"
    INCONSISTENT_COMPLETION = "inconsistent_completion"
    POTENTIAL_DUPLICATE = "potential_duplicate_incident"


class FindingOrigin(StrEnum):
    DETERMINISTIC = "deterministic"
    AI = "ai"


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    HIGH = "high"


class ReviewStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    DISMISSED = "dismissed"


class ReviewOutcome(StrEnum):
    CONFIRMED = "confirmed"
    DISMISSED = "dismissed"


class IntegrityFinding(Record):
    type: FindingType | SemanticKind
    severity: Severity
    explanation: Text
    evidence: Annotated[tuple[EvidenceReference, ...], Field(min_length=1)]
    recommended_action: Text
    review_status: ReviewStatus = ReviewStatus.PENDING
    created_at: AwareDatetime
    origin: FindingOrigin = FindingOrigin.DETERMINISTIC
    execution_id: UUID | None = None
    uncertainty: Text | None = None

    @model_validator(mode="after")
    def validate_provenance(self) -> Self:
        if self.origin == FindingOrigin.AI:
            if self.execution_id is None or not isinstance(self.type, SemanticKind):
                raise ValueError(
                    "AI findings require a semantic kind and an execution reference."
                )
        elif self.execution_id is not None or isinstance(self.type, SemanticKind):
            raise ValueError(
                "Deterministic findings must use a deterministic finding type."
            )
        return self


class ReviewDecision(Record):
    finding_id: UUID
    reviewer_id: UUID
    outcome: ReviewOutcome
    reason: Text
    decided_at: AwareDatetime


class HandoverStatus(StrEnum):
    PREVIEWED = "previewed"
    ACCEPTED = "accepted"


class ActionSnapshot(Contract):
    action_id: UUID
    report_id: UUID
    description: Text
    owner_id: UUID | None
    status: ActionStatus
    due_at: AwareDatetime | None
    version: Version
    transferable: bool


class Handover(Record):
    outgoing_shift_id: UUID
    incoming_shift_id: UUID
    outgoing_operator_id: UUID
    incoming_operator_id: UUID
    actions: Annotated[tuple[ActionSnapshot, ...], Field(min_length=1)]
    status: HandoverStatus = HandoverStatus.PREVIEWED
    version: Version = 1
    created_at: AwareDatetime

    @model_validator(mode="after")
    def distinct_parties_and_actions(self) -> Self:
        if (
            self.outgoing_shift_id == self.incoming_shift_id
            or self.outgoing_operator_id == self.incoming_operator_id
        ):
            raise ValueError("Transfer requires different shifts and operators.")
        if len({item.action_id for item in self.actions}) != len(self.actions):
            raise ValueError("Handover references the same action more than once.")
        return self

    def accept(self, actor_id: UUID) -> Self:
        if actor_id != self.incoming_operator_id:
            raise Forbidden("Only the incoming operator can accept this handover.")
        if self.status != HandoverStatus.PREVIEWED:
            raise Conflict(
                "handover_already_accepted", "This handover already has a receipt."
            )
        return self.model_copy(
            update={"status": HandoverStatus.ACCEPTED, "version": self.version + 1}
        )


class HandoverReceipt(Record):
    handover_id: UUID
    outgoing_shift_id: UUID
    incoming_shift_id: UUID
    accepted_by: UUID
    accepted_at: AwareDatetime
    transferred: Annotated[tuple[ActionItem, ...], Field(min_length=1)]
    outstanding: tuple[ActionItem, ...]

    @model_validator(mode="after")
    def consistent_custody(self) -> Self:
        items = (*self.transferred, *self.outstanding)
        if self.outgoing_shift_id == self.incoming_shift_id:
            raise ValueError(
                "Receipt must describe a transfer between different shifts."
            )
        if len({item.id for item in items}) != len(items):
            raise ValueError("Receipt lists the same action more than once.")
        if any(
            item.shift_id != self.incoming_shift_id or item.owner_id != self.accepted_by
            for item in self.transferred
        ):
            raise ValueError(
                "Transferred actions must belong to the accepting operator and shift."
            )
        if any(item.shift_id != self.outgoing_shift_id for item in self.outstanding):
            raise ValueError("Outstanding actions must remain on the outgoing shift.")
        return self
