from pathlib import Path
from uuid import uuid4

from relay.demo import DAY, at
from relay.intelligence.analysis import Analysis
from relay.intelligence.contracts import Execution, FailureCategory, Usage
from relay.intelligence.evaluate import Suite, aggregate, grade, validation_result
from relay.intelligence.gemini import DEFAULT_MODEL


def suite():
    path = Path(__file__).resolve().parents[1] / "evals/facilities-v1.json"
    return Suite.model_validate_json(path.read_text())


def test_dataset_has_grounded_gold_anchors_and_distinct_cases():
    data = suite()
    assert len(data.positive) == len(data.negative) == 11
    assert (
        len({case.id for case in (*data.positive, *data.negative, *data.validation)})
        == 24
    )
    for case in data.positive:
        assert case.expected and not case.allow_abstention
        for expected in case.expected:
            assert expected.evidence
            for reference in expected.evidence:
                assert reference.anchor in case.reports[reference.report]
    assert all(not case.expected and case.allow_abstention for case in data.negative)
    assert all(validation_result(case)["passed"] for case in data.validation)


def test_evaluation_reports_misses_and_keeps_infrastructure_failures_out_of_semantic_scores():
    positive = suite().positive[0]
    negative = suite().negative[0]
    execution = Execution(
        id=uuid4(),
        request_id="test",
        shift_id=DAY.id,
        model=DEFAULT_MODEL,
        extraction_prompt_version="extract-v1",
        proposal_prompt_version="semantic-review-v1",
        started_at=at(14),
        latency_ms=50,
        usage=Usage(input_tokens=200, output_tokens=100),
        report_count=2,
        proposal_count=0,
        rejected_count=0,
        duplicate_count=0,
        retry_count=0,
    )
    no_match = grade(positive, positive.sources(), Analysis(execution, ()))
    no_match["execution"]["abstention"] = None
    failed = grade(
        negative,
        negative.sources(),
        Analysis(
            execution.model_copy(
                update={"failure": FailureCategory.UNAVAILABLE, "usage": Usage()}
            ),
            (),
        ),
    )
    result = aggregate([no_match, failed])
    assert result["attempted"] == 2 and result["evaluated"] == 1
    assert result["precision"] is None and result["recall"] == 0
    assert result["false_positive_rate"] is None
    assert result["estimated_standard_usd"] == 0.0002
