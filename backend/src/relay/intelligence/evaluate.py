"""Evaluate synthetic handover cases with opt-in live Gemini calls."""

import argparse
import asyncio
import json
from datetime import timedelta
from itertools import chain, zip_longest
from pathlib import Path
from statistics import mean, median
from uuid import uuid4

from pydantic import BaseModel

from relay.demo import DAY, OUTGOING, PUMP, at, demo_id
from relay.domain import OperationalReport, SemanticKind
from relay.intelligence.analysis import Analysis, AnalysisBudget, Analyzer
from relay.intelligence.contracts import (
    Citation,
    FailureCategory,
    ProposalBatch,
    ProposedFinding,
)
from relay.intelligence.cost import estimate_cost
from relay.intelligence.gemini import GeminiProvider
from relay.intelligence.prompts import Sources
from relay.intelligence.validation import EvidenceValidator, GroundedProposal


class ExpectedEvidence(BaseModel):
    report: int
    anchor: str


class ExpectedFinding(BaseModel):
    kind: SemanticKind
    evidence: tuple[ExpectedEvidence, ...]


class Case(BaseModel):
    id: str
    reports: tuple[str, ...]
    expected: tuple[ExpectedFinding, ...]
    allow_abstention: bool

    def sources(self) -> Sources:
        return Sources(
            tuple(
                OperationalReport(
                    id=demo_id(f"eval:{self.id}:{index}"),
                    source_ref=f"synthetic:eval:{self.id}:{index}",
                    shift_id=DAY.id,
                    author_id=OUTGOING.id,
                    asset_id=PUMP.id,
                    observed_at=at(13) + timedelta(seconds=index),
                    received_at=at(14),
                    text=text,
                    synthetic=True,
                )
                for index, text in enumerate(self.reports)
            )
        )


class ValidationCase(BaseModel):
    id: str
    report: str
    invalid: str
    expected: str


class Suite(BaseModel):
    version: str
    positive: tuple[Case, ...]
    negative: tuple[Case, ...]
    validation: tuple[ValidationCase, ...]


def rating(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def matches(
    proposal: GroundedProposal, expected: ExpectedFinding, sources: Sources
) -> bool:
    return proposal.candidate.kind == expected.kind and all(
        any(
            citation.report_id == sources.reports[anchor.report].id
            and anchor.anchor.casefold() in citation.quote.casefold()
            for citation in proposal.evidence
        )
        for anchor in expected.evidence
    )


def grade(case: Case, sources: Sources, analysis: Analysis) -> dict:
    unmatched = list(case.expected)
    true_positives = 0
    for proposal in analysis.proposals:
        for expected in unmatched:
            if matches(proposal, expected, sources):
                true_positives += 1
                unmatched.remove(expected)
                break
    execution = analysis.execution
    return {
        "case": case.id,
        "positive": bool(case.expected),
        "expected": [str(item.kind) for item in case.expected],
        "observed": [str(item.candidate.kind) for item in analysis.proposals],
        "matched": true_positives,
        "missed": [str(item.kind) for item in unmatched],
        "abstention_allowed": case.allow_abstention,
        "abstained": execution.abstention is not None,
        "estimated_standard_usd": estimate_cost(execution.model, execution.usage),
        "execution": execution.model_dump(mode="json"),
    }


def validation_result(case: ValidationCase) -> dict:
    sources = Case(
        id=case.id, reports=(case.report,), expected=(), allow_abstention=True
    ).sources()
    (report,) = sources.reports
    proposal = ProposedFinding(
        kind=SemanticKind.MISSING_CONTEXT,
        asset_id=report.asset_id,
        action_ids=(),
        explanation="Deliberately invalid test candidate.",
        severity="warning",
        uncertainty=None,
        evidence=(
            Citation(
                report_id=uuid4() if case.invalid == "unknown_report_id" else report.id,
                quote="This quote was fabricated."
                if case.invalid == "invented_quote"
                else report.text,
            ),
        ),
        recommended_review="clarify_context",
    )
    result = EvidenceValidator(sources).proposals(
        ProposalBatch(proposals=(proposal,), abstention=None)
    )
    return {
        "case": case.id,
        "passed": not result.grounded and result.rejected == (case.expected,),
        "rejections": result.rejected,
    }


def aggregate(rows: list[dict]) -> dict:
    successes = [row for row in rows if row["execution"]["failure"] is None]
    negative = [row for row in successes if not row["positive"]]
    malformed = sum(
        row["execution"]["failure"] == FailureCategory.MALFORMED_OUTPUT for row in rows
    )
    true_positives = sum(row["matched"] for row in successes)
    observed = sum(len(row["observed"]) for row in successes)
    expected = sum(len(row["expected"]) for row in successes)
    expected_attempted = sum(len(row["expected"]) for row in rows)
    proposals = sum(row["execution"]["proposal_count"] for row in successes)
    rejected = sum(row["execution"]["rejected_proposal_count"] for row in successes)
    latencies = [row["execution"]["latency_ms"] for row in successes]
    costs = [
        row["estimated_standard_usd"]
        for row in rows
        if row["estimated_standard_usd"] is not None
    ]
    return {
        "attempted": len(rows),
        "evaluated": len(successes),
        "semantic_only_on_successful_cases": True,
        "true_positives": true_positives,
        "validated_findings": observed,
        "expected_findings": expected,
        "precision": rating(true_positives, observed),
        "recall": rating(true_positives, expected),
        "attempted_expected_findings": expected_attempted,
        "end_to_end_recall": rating(true_positives, expected_attempted),
        "failed_cases": len(rows) - len(successes),
        "negative_cases": len(negative),
        "false_positive_rate": rating(
            sum(bool(row["observed"]) for row in negative), len(negative)
        ),
        "emitted_candidates": proposals,
        "rejected_candidates": rejected,
        "evidence_validity": rating(proposals - rejected, proposals),
        "schema_validity_per_case": rating(len(successes), len(successes) + malformed),
        "negative_abstention_rate": rating(
            sum(row["abstained"] for row in negative), len(negative)
        ),
        "positive_abstentions": sum(
            row["abstained"] and row["positive"] for row in successes
        ),
        "median_latency_ms": median(latencies) if latencies else None,
        "mean_latency_ms": round(mean(latencies), 1) if latencies else None,
        "estimated_standard_usd": round(sum(costs), 7) if costs else None,
        "costed_cases": len(costs),
    }


async def live_cases(
    suite: Suite, limit: int, pause: float, offset: int = 0
) -> list[dict]:
    provider = GeminiProvider.from_environment()
    analyzer = Analyzer(provider, AnalysisBudget.from_environment())
    cases = [
        case
        for case in chain.from_iterable(zip_longest(suite.positive, suite.negative))
        if case
    ]
    rows: list[dict] = []
    for index, case in enumerate(cases[offset : offset + limit]):
        if index:
            await asyncio.sleep(pause)
        sources = case.sources()
        result = await analyzer.run(
            sources, request_id=f"eval:{case.id}", execution_id=uuid4(), shift_id=DAY.id
        )
        rows.append(grade(case, sources, result))
        if result.execution.failure in {
            FailureCategory.NOT_CONFIGURED,
            FailureCategory.UNAUTHORIZED,
            FailureCategory.RATE_LIMITED,
            FailureCategory.INVALID_REQUEST,
        }:
            break
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset", type=Path, default=Path("evals/facilities-v1.json")
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Opt in to Gemini calls for the synthetic cases.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=22,
        help="Maximum live cases, alternating positive and negative.",
    )
    parser.add_argument(
        "--pause", type=float, default=1.5, help="Seconds between live cases."
    )
    parser.add_argument(
        "--offset", type=int, default=0, help="Skip previously attempted cases."
    )
    args = parser.parse_args()
    if args.limit < 1 or args.pause < 0 or args.offset < 0:
        parser.error(
            "Limit must be positive, and pause and offset must be non-negative."
        )
    suite = Suite.model_validate_json(args.dataset.read_text())
    rows = (
        asyncio.run(live_cases(suite, args.limit, args.pause, args.offset))
        if args.live
        else []
    )
    report = {
        "dataset": suite.version,
        "live": args.live,
        "offset": args.offset,
        "dataset_cases": len(suite.positive)
        + len(suite.negative)
        + len(suite.validation),
        "metrics": aggregate(rows),
        "cases": rows,
        "deterministic_validation": [
            validation_result(case) for case in suite.validation
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["metrics"], indent=2))
    if not all(row["passed"] for row in report["deterministic_validation"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
