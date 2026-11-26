from uuid import uuid4

import pytest

from relay.demo import PUMP, at, demo_id, reports
from relay.domain import OperationalReport
from relay.intelligence.contracts import (
    Citation,
    Extraction,
    OperationalFact,
    ProposalBatch,
    ProposedFinding,
)
from relay.intelligence.prompts import Sources
from relay.intelligence.validation import EvidenceValidator, Rejection


@pytest.fixture
def sources():
    fixtures = []
    for index, command in enumerate(reports()[:2]):
        fixtures.append(
            OperationalReport(
                id=demo_id(f"grounding-{index}"),
                received_at=at(14),
                **command.model_dump(exclude={"actions", "operation_id"}),
            )
        )
    return Sources(tuple(fixtures))


def candidate(sources):
    return ProposedFinding(
        kind="semantic_contradiction",
        asset_id=PUMP.id,
        action_ids=(),
        explanation="These claims seem to describe incompatible asset states.",
        evidence=tuple(
            Citation(report_id=r.id, quote=r.text[18:45]) for r in sources.reports
        ),
        uncertainty=None,
        severity="high",
        recommended_review="compare_reports",
    )


@pytest.mark.parametrize("issue", list(Rejection))
def test_validator_rejects_unsupported_references(sources, issue):
    draft = candidate(sources)
    first, second = draft.evidence
    match issue:
        case Rejection.UNKNOWN_REPORT:
            changes = {
                "evidence": (Citation(report_id=uuid4(), quote=first.quote), second)
            }
        case Rejection.QUOTE_MISMATCH:
            changes = {
                "evidence": (
                    Citation(report_id=first.report_id, quote="Invented quotation"),
                    second,
                )
            }
        case Rejection.WRONG_ASSET:
            changes = {"asset_id": uuid4()}
        case Rejection.UNLINKED_ACTION:
            changes = {"action_ids": (uuid4(),)}
        case Rejection.INSUFFICIENT_SOURCES:
            changes = {"evidence": (first, first)}
    result = EvidenceValidator(sources).proposals(
        ProposalBatch(proposals=(draft.model_copy(update=changes),), abstention=None)
    )
    assert result.grounded == ()
    assert result.rejected == (issue,)


def test_exact_spans_remain_reviewable_and_duplicate_candidates_collapse(sources):
    draft = candidate(sources)
    result = EvidenceValidator(sources).proposals(
        ProposalBatch(
            proposals=(
                draft,
                draft.model_copy(update={"evidence": draft.evidence[::-1]}),
            ),
            abstention=None,
        )
    )
    assert result.duplicates == 1
    assert not result.rejected
    (grounded,) = result.grounded
    assert grounded.evidence[0].quote == draft.evidence[0].quote
    assert grounded.evidence[0].source_ref == sources.reports[0].source_ref


def test_extraction_drops_unverified_items_before_second_model_call(sources):
    valid = OperationalFact(
        asset_id=PUMP.id,
        statement="Reported pump fault.",
        evidence=(candidate(sources).evidence[0],),
    )
    invalid = valid.model_copy(update={"asset_id": uuid4()})
    verified, count = EvidenceValidator(sources).extraction(
        Extraction(
            facts=(invalid, valid),
            observations=(),
            actions=(),
            ambiguities=(),
        )
    )
    assert count == 1 and verified.facts == (valid,)
