from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from relay.domain import EvidenceReference, SemanticKind
from relay.intelligence.contracts import (
    Citation,
    Extraction,
    ProposalBatch,
    ProposedFinding,
)
from relay.intelligence.prompts import Sources


class Rejection(StrEnum):
    UNKNOWN_REPORT = "unknown_report"
    QUOTE_MISMATCH = "quote_mismatch"
    WRONG_ASSET = "wrong_asset"
    UNLINKED_ACTION = "unlinked_action"
    INSUFFICIENT_SOURCES = "insufficient_sources"


CROSS_REPORT = {
    SemanticKind.CONTRADICTION,
    SemanticKind.INCONSISTENT_COMPLETION,
    SemanticKind.POTENTIAL_DUPLICATE,
}


@dataclass(frozen=True)
class GroundedProposal:
    candidate: ProposedFinding
    evidence: tuple[EvidenceReference, ...]

    @property
    def source_ids(self) -> frozenset[UUID]:
        return frozenset(item.report_id for item in self.evidence)

    @property
    def key(self) -> tuple[SemanticKind, UUID, frozenset[UUID]]:
        return (self.candidate.kind, self.candidate.asset_id, self.source_ids)


@dataclass(frozen=True)
class ValidationResult:
    grounded: tuple[GroundedProposal, ...]
    rejected: tuple[Rejection, ...]
    duplicates: int


class EvidenceValidator:
    """Validate referential and quotation integrity. Human review decides entailment."""

    def __init__(self, sources: Sources):
        self.reports = {report.id: report for report in sources.reports}
        self.actions = {action.id: action for action in sources.actions}

    def _resolve(
        self,
        asset_id: UUID,
        citations: tuple[Citation, ...],
        action_ids: tuple[UUID, ...] = (),
    ) -> tuple[EvidenceReference, ...] | Rejection:
        resolved: dict[tuple[UUID, str], EvidenceReference] = {}
        for citation in citations:
            report = self.reports.get(citation.report_id)
            if report is None:
                return Rejection.UNKNOWN_REPORT
            if report.asset_id != asset_id:
                return Rejection.WRONG_ASSET
            if len(citation.quote.strip()) < 8 or citation.quote not in report.text:
                return Rejection.QUOTE_MISMATCH
            resolved[citation.report_id, citation.quote] = EvidenceReference(
                report_id=report.id,
                source_ref=report.source_ref,
                quote=citation.quote,
            )
        cited_reports = {ref.report_id for ref in resolved.values()}
        for action_id in action_ids:
            action = self.actions.get(action_id)
            if action is None or action.report_id not in cited_reports:
                return Rejection.UNLINKED_ACTION
        return tuple(resolved.values())

    def extraction(self, draft: Extraction) -> tuple[Extraction, int]:
        facts = tuple(
            item
            for item in draft.facts
            if not isinstance(self._resolve(item.asset_id, item.evidence), Rejection)
        )
        observations = tuple(
            item
            for item in draft.observations
            if not isinstance(self._resolve(item.asset_id, item.evidence), Rejection)
        )
        actions = tuple(
            item
            for item in draft.actions
            if not isinstance(
                self._resolve(
                    item.asset_id,
                    item.evidence,
                    (item.action_id,) if item.action_id else (),
                ),
                Rejection,
            )
        )
        rejected = (
            len(draft.facts)
            + len(draft.observations)
            + len(draft.actions)
            - len(facts)
            - len(observations)
            - len(actions)
        )
        return Extraction(
            facts=facts,
            observations=observations,
            actions=actions,
            ambiguities=draft.ambiguities,
        ), rejected

    def proposals(self, batch: ProposalBatch) -> ValidationResult:
        accepted: dict[
            tuple[SemanticKind, UUID, frozenset[UUID]], GroundedProposal
        ] = {}
        rejections = []
        duplicates = 0
        for candidate in batch.proposals:
            evidence = self._resolve(
                candidate.asset_id, candidate.evidence, candidate.action_ids
            )
            if isinstance(evidence, Rejection):
                rejections.append(evidence)
                continue
            proposal = GroundedProposal(candidate, evidence)
            if candidate.kind in CROSS_REPORT and len(proposal.source_ids) < 2:
                rejections.append(Rejection.INSUFFICIENT_SOURCES)
            elif proposal.key in accepted:
                duplicates += 1
            else:
                accepted[proposal.key] = proposal
        return ValidationResult(tuple(accepted.values()), tuple(rejections), duplicates)
