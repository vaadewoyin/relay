import asyncio
import json
import logging
from datetime import UTC, datetime
from hashlib import sha256
from uuid import NAMESPACE_URL, UUID, uuid5

from relay.domain import (
    ActionItem,
    Conflict,
    FindingOrigin,
    FindingType,
    IntegrityFinding,
    OperationalReport,
    SemanticKind,
    Shift,
)
from relay.intelligence.analysis import Analyzer
from relay.intelligence.contracts import Execution, ReviewAction, Usage
from relay.intelligence.prompts import EXTRACTION, PROPOSALS, Sources
from relay.intelligence.validation import GroundedProposal
from relay.service import Store, require

logger = logging.getLogger("relay.intelligence")

RECOMMENDATIONS = {
    ReviewAction.VERIFY_ON_SITE: "Verify the condition on site.",
    ReviewAction.REQUEST_EVIDENCE: "Request the supporting work record.",
    ReviewAction.CLARIFY_OWNER: "Ask the shifts to clarify responsibility.",
    ReviewAction.CLARIFY_CONTEXT: "Request the missing context before acting.",
    ReviewAction.ESCALATE_TO_SUPERVISOR: "Ask a supervisor to review the safety concern.",
    ReviewAction.COMPARE_REPORTS: "Compare the original reports with the operators.",
}

DETERMINISTIC_EQUIVALENTS = {
    SemanticKind.CONTRADICTION: FindingType.CONTRADICTORY_ASSET_STATUS,
    SemanticKind.POTENTIAL_DUPLICATE: FindingType.DUPLICATE_REPORT,
}


class Intelligence:
    def __init__(
        self, store: Store, analyzer: Analyzer, *, allow_operational_data: bool = False
    ):
        self.store = store
        self.analyzer = analyzer
        self.allow_operational_data = allow_operational_data
        self.lock = asyncio.Lock()

    async def run(
        self, shift_id: UUID, execution_id: UUID, request_id: str
    ) -> Execution:
        if self.lock.locked():
            raise Conflict("analysis_in_progress", "An analysis is already running.")
        async with self.lock:
            with self.store.transaction() as tx:
                if previous := tx.get(Execution, execution_id):
                    if previous.shift_id != shift_id:
                        raise Conflict(
                            "operation_id_reused", "Analysis ID is already in use."
                        )
                    return previous
                require(tx, Shift, shift_id)
                reports = tuple(
                    report
                    for report in tx.all(OperationalReport)
                    if report.shift_id == shift_id
                    and (report.synthetic or self.allow_operational_data)
                )
                ids = {report.id for report in reports}
                actions = tuple(
                    action for action in tx.all(ActionItem) if action.report_id in ids
                )
            sources = Sources(reports, actions)
            fingerprint = None
            if any(
                report.source_ref.startswith("notion:") and report.source_url
                for report in reports
            ):
                fingerprint = sha256(sources.payload().encode()).hexdigest()
                with self.store.transaction(write=True) as tx:
                    cached = next(
                        (
                            item
                            for item in tx.all(Execution)
                            if item.shift_id == shift_id
                            and item.source_fingerprint == fingerprint
                            and item.model == self.analyzer.provider.model
                            and item.extraction_prompt_version == EXTRACTION.version
                            and item.proposal_prompt_version == PROPOSALS.version
                            and item.failure is None
                            and (item.finding_ids or item.abstention)
                            and item.reused_from is None
                        ),
                        None,
                    )
                    if cached is not None:
                        if previous := tx.get(Execution, execution_id):
                            if previous.shift_id != shift_id:
                                raise Conflict(
                                    "operation_id_reused",
                                    "Analysis ID is already in use.",
                                )
                            return previous
                        execution = cached.model_copy(
                            update={
                                "id": execution_id,
                                "request_id": request_id,
                                "latency_ms": 0,
                                "started_at": datetime.now(UTC),
                                "usage": Usage(),
                                "retry_count": 0,
                                "reused_from": cached.id,
                            }
                        )
                        tx.insert(execution)
                        logger.info(
                            json.dumps(
                                {
                                    "event": "ai_execution_reused",
                                    "id": str(execution_id),
                                    "request_id": request_id,
                                    "reused_from": str(cached.id),
                                }
                            )
                        )
                        return execution
            result = await self.analyzer.run(
                sources,
                request_id=request_id,
                execution_id=execution_id,
                shift_id=shift_id,
            )
            with self.store.transaction(write=True) as tx:
                if previous := tx.get(Execution, execution_id):
                    if previous.shift_id != shift_id:
                        raise Conflict(
                            "operation_id_reused", "Analysis ID is already in use."
                        )
                    return previous
                existing = {
                    (
                        finding.type,
                        frozenset(ref.report_id for ref in finding.evidence),
                    ): finding
                    for finding in tx.all(IntegrityFinding)
                }
                ids = []
                duplicates = result.execution.duplicate_count
                for proposal in result.proposals:
                    key = (proposal.candidate.kind, proposal.source_ids)
                    deterministic = DETERMINISTIC_EQUIVALENTS.get(
                        proposal.candidate.kind
                    )
                    if key in existing or (
                        deterministic
                        and (deterministic, proposal.source_ids) in existing
                    ):
                        duplicates += 1
                        continue
                    finding = new_finding(result.execution, proposal)
                    tx.insert(finding)
                    ids.append(finding.id)
                execution = result.execution.model_copy(
                    update={
                        "finding_ids": tuple(ids),
                        "duplicate_count": duplicates,
                        "source_fingerprint": fingerprint,
                    },
                )
                tx.insert(execution)
            logger.info(
                json.dumps(
                    {
                        "event": "ai_execution",
                        **execution.model_dump(mode="json", exclude={"abstention"}),
                        "abstained": execution.abstention is not None,
                    }
                )
            )
            return execution


def new_finding(execution: Execution, proposal: GroundedProposal) -> IntegrityFinding:
    candidate = proposal.candidate
    source_ids = ":".join(sorted(map(str, proposal.source_ids)))
    finding_id = uuid5(
        NAMESPACE_URL,
        f"relay:ai:{candidate.kind}:{candidate.asset_id}:{source_ids}",
    )
    return IntegrityFinding(
        id=finding_id,
        type=candidate.kind,
        origin=FindingOrigin.AI,
        execution_id=execution.id,
        evidence=proposal.evidence,
        severity=candidate.severity,
        explanation=candidate.explanation,
        recommended_action=RECOMMENDATIONS[candidate.recommended_review],
        uncertainty=candidate.uncertainty.explanation
        if candidate.uncertainty
        else None,
        created_at=execution.started_at,
    )
