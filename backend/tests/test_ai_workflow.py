import asyncio
from uuid import uuid4

import pytest

from relay.demo import DAY, INCOMING, OUTGOING, at, prepare_wearable
from relay.domain import (
    ActionItem,
    FindingOrigin,
    HandoverReceipt,
    IntegrityFinding,
    OperationalReport,
    ReviewStatus,
)
from relay.intelligence.analysis import AnalysisBudget, Analyzer
from relay.intelligence.contracts import (
    Citation,
    Extraction,
    FailureCategory,
    ProposalBatch,
    ProposedFinding,
)
from relay.intelligence.provider import ModelProvider, ModelResponse, ProviderFailure
from relay.intelligence.workflow import Intelligence
from relay.service import (
    AcceptHandover,
    PreviewHandover,
    RelayService,
    ReviewFinding,
)
from relay.store import SQLiteStore


class FakeProvider(ModelProvider):
    model = "test-fake"

    def __init__(self, replies=(), failure=None, delay=0):
        self.calls = []
        self.replies = iter(replies)
        self.failure = failure
        self.delay = delay

    async def generate(self, **request):
        self.calls.append(request)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.failure:
            raise ProviderFailure(self.failure)
        return ModelResponse(next(self.replies))


@pytest.fixture
def store(tmp_path):
    value = SQLiteStore(tmp_path / "store.sqlite3")
    prepare_wearable(value)
    return value


def scenario(store, *, kind="inconsistent_completion"):
    with store.transaction() as tx:
        first, second = tx.all(OperationalReport)[:2]
    candidate = ProposedFinding(
        kind=kind,
        asset_id=first.asset_id,
        action_ids=(),
        explanation="The two operators report different outcomes.",
        evidence=(
            Citation(report_id=first.id, quote=first.text),
            Citation(report_id=second.id, quote=second.text),
        ),
        severity="high",
        uncertainty=None,
        recommended_review="compare_reports",
    )
    extraction = Extraction(facts=(), actions=(), observations=(), ambiguities=())
    return extraction, ProposalBatch(proposals=(candidate,), abstention=None)


def run(store, provider, operation_id=None, budget=AnalysisBudget()):
    return asyncio.run(
        Intelligence(store, Analyzer(provider, budget)).run(
            DAY.id,
            operation_id or uuid4(),
            "test-request",
        )
    )


def test_analysis_creates_pending_reviews_without_mutating_authoritative_work(store):
    with store.transaction() as tx:
        before = tx.all(ActionItem)
    replies = scenario(store)
    provider = FakeProvider(replies)
    execution = run(store, provider)
    assert execution.failure is None and execution.proposal_count == 1
    assert run(store, provider, execution.id) == execution
    assert len(provider.calls) == 2
    (finding,) = [
        f for f in RelayService(store).findings() if f.origin == FindingOrigin.AI
    ]
    assert (
        finding.review_status == ReviewStatus.PENDING
        and finding.execution_id == execution.id
    )
    assert finding.id in execution.finding_ids
    RelayService(store).review(
        finding.id,
        ReviewFinding(
            operation_id=uuid4(),
            reviewer_id=INCOMING.id,
            outcome="confirmed",
            reason="Reviewed by a human.",
        ),
    )
    assert (
        RelayService(store).finding(finding.id).review_status == ReviewStatus.CONFIRMED
    )
    repeated = run(store, FakeProvider(replies))
    assert repeated.finding_ids == () and repeated.duplicate_count == 1
    with store.transaction() as tx:
        assert before == tx.all(ActionItem)
        assert tx.all(HandoverReceipt) == []


def test_legacy_store_migration_keeps_existing_findings(store):
    # Simulate the previous schema by removing the only Phase 3 table and version.
    import sqlite3

    with sqlite3.connect(store.path) as connection:
        connection.execute("DROP TABLE ai_executions")
        connection.execute("PRAGMA user_version = 1")
    store.initialize()
    with store.transaction() as tx:
        assert tx.all(IntegrityFinding)
    assert run(store, FakeProvider(scenario(store))).finding_ids


def test_deterministic_equivalent_is_deduplicated(store):
    service = RelayService(store)
    pair = next(
        f.evidence for f in service.findings() if f.type == "contradictory_asset_status"
    )
    draft, batch = scenario(store, kind="semantic_contradiction")
    candidate = batch.proposals[0].model_copy(
        update={
            "evidence": tuple(
                Citation(report_id=ref.report_id, quote=ref.quote) for ref in pair
            )
        }
    )
    result = run(
        store,
        FakeProvider((draft, ProposalBatch(proposals=(candidate,), abstention=None))),
    )
    assert result.finding_ids == ()
    assert result.duplicate_count == 1


@pytest.mark.parametrize(
    "failure",
    [
        FailureCategory.UNAVAILABLE,
        FailureCategory.MALFORMED_OUTPUT,
        FailureCategory.TIMEOUT,
    ],
)
def test_provider_failure_preserves_the_deterministic_handover(store, failure):
    result = run(store, FakeProvider(failure=failure))
    assert result.failure == failure and not result.finding_ids
    service = RelayService(store, clock=lambda: at(15))
    from relay.demo import EVENING

    preview = service.preview(
        PreviewHandover(
            outgoing_shift_id=DAY.id,
            incoming_shift_id=EVENING.id,
            actor_id=OUTGOING.id,
            operation_id=uuid4(),
        )
    )
    receipt = service.accept(
        preview.id,
        AcceptHandover(
            actor_id=INCOMING.id,
            expected_version=preview.version,
            confirmed=True,
            operation_id=uuid4(),
        ),
    )
    assert len(receipt.transferred) == 1


def test_analyzer_deadline_and_input_budget(store):
    provider = FakeProvider(delay=1)
    result = run(store, provider, budget=AnalysisBudget(seconds=0.05))
    assert result.failure == FailureCategory.TIMEOUT
    result = run(store, provider, budget=AnalysisBudget(reports=1))
    assert result.failure == FailureCategory.BUDGET
    assert len(provider.calls) == 1


def test_semantic_fixture_leaves_conflicting_free_text_for_model(store):
    from relay.demo import prepare_intelligence

    baseline = RelayService(store).findings()
    prepare_intelligence(store)
    with store.transaction() as tx:
        semantic = [
            report for report in tx.all(OperationalReport) if "FD-22" in report.text
        ]
    assert len(semantic) == 2 and all(
        report.asset_status is None for report in semantic
    )
    assert RelayService(store).findings() == baseline
