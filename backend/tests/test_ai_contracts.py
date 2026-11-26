from uuid import uuid4

import pytest
from pydantic import ValidationError

from relay.intelligence.contracts import ProposalBatch, ProposedFinding, Usage


def proposal():
    return {
        "kind": "semantic_contradiction",
        "asset_id": str(uuid4()),
        "action_ids": [],
        "explanation": "The reports disagree about the pump at the same test.",
        "evidence": [{"report_id": str(uuid4()), "quote": "Pump remained off."}],
        "uncertainty": None,
        "severity": "high",
        "recommended_review": "compare_reports",
    }


@pytest.mark.parametrize(
    "override",
    [
        {"evidence": []},
        {"evidence": [{"report_id": "wrong", "quote": "Pump remained off."}]},
        {"recommended_review": "transfer_ownership"},
        {"severity": "certain"},
        {"confidence": 0.99},
        {"confirmed": True},
    ],
)
def test_proposal_rejects_missing_evidence_and_authority_claims(override):
    with pytest.raises(ValidationError):
        ProposedFinding.model_validate({**proposal(), **override})


def test_batch_requires_candidates_or_explicit_abstention():
    reason = {"kind": "insufficient_evidence", "explanation": "The asset is unclear."}
    assert ProposalBatch.model_validate(
        {"proposals": [], "abstention": reason}
    ).abstention
    for data in (
        {"proposals": [], "abstention": None},
        {"proposals": [proposal()], "abstention": reason},
    ):
        with pytest.raises(ValidationError):
            ProposalBatch.model_validate(data)


def test_unknown_token_usage_stays_unknown():
    measured = Usage(input_tokens=120, output_tokens=90, thinking_tokens=0)
    assert measured.aggregate(measured).input_tokens == 240
    assert measured.aggregate(Usage()).output_tokens is None
