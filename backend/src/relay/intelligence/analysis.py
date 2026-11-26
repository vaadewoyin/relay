import asyncio
import os
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from time import monotonic
from typing import Annotated
from uuid import UUID

from pydantic import Field

from relay.domain import Contract
from relay.intelligence.contracts import (
    Execution,
    Extraction,
    FailureCategory,
    ProposalBatch,
    Uncertainty,
    UncertaintyKind,
    Usage,
)
from relay.intelligence.prompts import EXTRACTION, PROPOSALS, Prompt, Sources
from relay.intelligence.provider import ModelProvider, ProviderFailure
from relay.intelligence.validation import EvidenceValidator, GroundedProposal


class AnalysisBudget(Contract):
    seconds: Annotated[float, Field(gt=0, le=120)] = 35
    reports: Annotated[int, Field(ge=1, le=30)] = 12
    input_bytes: Annotated[int, Field(ge=512, le=100_000)] = 32_000
    output_tokens: Annotated[int, Field(ge=256, le=8192)] = 2600

    @classmethod
    def from_environment(cls) -> "AnalysisBudget":
        defaults = cls()
        return cls.model_validate(
            {
                key: os.getenv(f"RELAY_AI_{key.upper()}", str(value))
                for key, value in defaults.model_dump().items()
            }
        )


@dataclass(frozen=True)
class Analysis:
    execution: Execution
    proposals: tuple[GroundedProposal, ...]


class Analyzer:
    def __init__(
        self, provider: ModelProvider, budget: AnalysisBudget = AnalysisBudget()
    ):
        self.provider = provider
        self.budget = budget

    async def run(
        self, sources: Sources, *, request_id: str, execution_id: UUID, shift_id: UUID
    ) -> Analysis:
        started = datetime.now(UTC)
        start = monotonic()
        usage: Usage | None = None
        retries = extracted_rejections = proposal_count = duplicate_count = 0
        rejection_codes: Counter[str] = Counter()
        stages: dict[str, int] = {}
        failure = None
        failure_stage = None
        provider_http_status = None
        abstention = None
        grounded = ()

        async def generate[T: Contract](
            prompt: Prompt, data: str, schema: type[T]
        ) -> T:
            nonlocal usage, retries, failure_stage
            failure_stage = prompt.version
            if len(data.encode()) > self.budget.input_bytes:
                raise ProviderFailure(FailureCategory.BUDGET)
            remaining = self.budget.seconds - (monotonic() - start)
            if remaining <= 0:
                raise ProviderFailure(FailureCategory.TIMEOUT)
            stage_start = monotonic()
            try:
                async with asyncio.timeout(remaining):
                    result = await self.provider.generate(
                        instructions=prompt.instructions,
                        data=data,
                        schema=schema,
                        timeout=remaining,
                        output_tokens=self.budget.output_tokens,
                    )
            except ProviderFailure as error:
                retries += error.retries
                if error.usage is not None:
                    usage = (
                        usage.aggregate(error.usage)
                        if usage is not None
                        else error.usage
                    )
                raise
            finally:
                stages[prompt.version] = round((monotonic() - stage_start) * 1000)
            usage = usage.aggregate(result.usage) if usage is not None else result.usage
            retries += result.retry_count
            return result.result

        try:
            if len(sources.reports) > self.budget.reports:
                raise ProviderFailure(FailureCategory.BUDGET)
            if not sources.reports:
                abstention = Uncertainty(
                    kind=UncertaintyKind.INSUFFICIENT_EVIDENCE,
                    explanation="No reports exist in the selected shift.",
                )
            else:
                validator = EvidenceValidator(sources)
                draft = await generate(EXTRACTION, sources.payload(), Extraction)
                validate_start = monotonic()
                extracted, extracted_rejections = validator.extraction(draft)
                stages["extraction_validation"] = round(
                    (monotonic() - validate_start) * 1000
                )
                candidates = await generate(
                    PROPOSALS, sources.payload(extracted), ProposalBatch
                )
                proposal_count = len(candidates.proposals)
                validate_start = monotonic()
                result = validator.proposals(candidates)
                stages["proposal_validation"] = round(
                    (monotonic() - validate_start) * 1000
                )
                grounded = result.grounded
                duplicate_count = result.duplicates
                rejection_codes.update(str(code) for code in result.rejected)
                abstention = candidates.abstention
        except ProviderFailure as error:
            failure = error.category
            provider_http_status = error.http_status
        except TimeoutError:
            failure = FailureCategory.TIMEOUT

        rejected_proposals = sum(rejection_codes.values())
        execution = Execution(
            id=execution_id,
            request_id=request_id,
            shift_id=shift_id,
            model=self.provider.model,
            extraction_prompt_version=EXTRACTION.version,
            proposal_prompt_version=PROPOSALS.version,
            started_at=started,
            latency_ms=round((monotonic() - start) * 1000),
            usage=usage or Usage(),
            report_count=len(sources.reports),
            proposal_count=proposal_count,
            rejected_count=rejected_proposals + extracted_rejections,
            rejected_proposal_count=rejected_proposals,
            validation_rejections=dict(rejection_codes),
            duplicate_count=duplicate_count,
            retry_count=retries,
            abstention=abstention,
            failure=failure,
            failure_stage=failure_stage if failure else None,
            provider_http_status=provider_http_status,
            stage_latency_ms=stages,
        )
        return Analysis(execution, grounded)
