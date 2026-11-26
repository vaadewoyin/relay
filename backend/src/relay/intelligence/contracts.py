"""Wire contracts for untrusted model output and Relay-owned execution records."""

from enum import StrEnum
from typing import Annotated, Self
from uuid import UUID

from pydantic import AwareDatetime, Field, StringConstraints, model_validator

from relay.domain import Contract, Record, SemanticKind, Severity

type Statement = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=350)
]
type Quote = Annotated[
    str, StringConstraints(min_length=1, max_length=500, pattern=r"\S")
]
type Count = Annotated[int, Field(ge=0)]


class ReviewAction(StrEnum):
    VERIFY_ON_SITE = "verify_on_site"
    REQUEST_EVIDENCE = "request_evidence"
    CLARIFY_OWNER = "clarify_owner"
    CLARIFY_CONTEXT = "clarify_context"
    ESCALATE_TO_SUPERVISOR = "escalate_to_supervisor"
    COMPARE_REPORTS = "compare_reports"


class UncertaintyKind(StrEnum):
    IMPLICIT_REFERENCE = "implicit_reference"
    UNKNOWN_TIMING = "unknown_timing"
    INCOMPLETE_RECORD = "incomplete_record"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class Uncertainty(Contract):
    kind: UncertaintyKind
    explanation: Statement


class Citation(Contract):
    report_id: UUID
    quote: Quote


type Citations = Annotated[tuple[Citation, ...], Field(min_length=1, max_length=5)]


class OperationalFact(Contract):
    asset_id: UUID
    statement: Statement
    evidence: Citations


class AssetObservation(Contract):
    asset_id: UUID
    reported_condition: Statement
    time_context: Statement | None
    evidence: Citations


class ActionClaim(StrEnum):
    REQUESTED = "requested"
    IN_PROGRESS = "in_progress"
    REPORTED_COMPLETE = "reported_complete"
    UNCLEAR = "unclear"


class ReportedAction(Contract):
    asset_id: UUID
    action_id: UUID | None
    description: Statement
    claim: ActionClaim
    evidence: Citations


class Extraction(Contract):
    facts: Annotated[tuple[OperationalFact, ...], Field(max_length=12)]
    observations: Annotated[tuple[AssetObservation, ...], Field(max_length=12)]
    actions: Annotated[tuple[ReportedAction, ...], Field(max_length=12)]
    ambiguities: Annotated[tuple[Uncertainty, ...], Field(max_length=8)]


class ProposedFinding(Contract):
    kind: SemanticKind
    asset_id: UUID
    action_ids: Annotated[tuple[UUID, ...], Field(max_length=5)]
    explanation: Statement
    evidence: Citations
    uncertainty: Uncertainty | None
    severity: Severity
    recommended_review: ReviewAction


class ProposalBatch(Contract):
    proposals: Annotated[tuple[ProposedFinding, ...], Field(max_length=8)]
    abstention: Uncertainty | None

    @model_validator(mode="after")
    def require_proposals_or_abstention(self) -> Self:
        if bool(self.proposals) == (self.abstention is not None):
            raise ValueError("Return proposals or an explicit abstention.")
        return self


class FailureCategory(StrEnum):
    NOT_CONFIGURED = "not_configured"
    UNAUTHORIZED = "unauthorized"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"
    BLOCKED_RESPONSE = "blocked_response"
    MALFORMED_OUTPUT = "malformed_output"
    INVALID_REQUEST = "invalid_request"
    BUDGET = "budget_exceeded"


class Usage(Contract):
    input_tokens: Count | None = None
    output_tokens: Count | None = None
    thinking_tokens: Count | None = None

    def aggregate(self, other: Self) -> Self:
        def add(a: int | None, b: int | None) -> int | None:
            return None if a is None or b is None else a + b

        return type(self)(
            input_tokens=add(self.input_tokens, other.input_tokens),
            output_tokens=add(self.output_tokens, other.output_tokens),
            thinking_tokens=add(self.thinking_tokens, other.thinking_tokens),
        )


class Execution(Record):
    request_id: str
    shift_id: UUID
    model: str
    extraction_prompt_version: str
    proposal_prompt_version: str
    started_at: AwareDatetime
    latency_ms: Count
    usage: Usage
    report_count: Count
    proposal_count: Count
    rejected_count: Count
    duplicate_count: Count
    rejected_proposal_count: Count = 0
    validation_rejections: dict[str, Count] = Field(default_factory=dict)
    retry_count: Count
    finding_ids: tuple[UUID, ...] = ()
    abstention: Uncertainty | None = None
    failure: FailureCategory | None = None
    stage_latency_ms: dict[str, Count] = Field(default_factory=dict)
    source_fingerprint: str | None = None
    reused_from: UUID | None = None
