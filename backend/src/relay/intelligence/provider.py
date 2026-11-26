from dataclasses import dataclass

from relay.domain import Contract
from relay.intelligence.contracts import FailureCategory, Usage


@dataclass(frozen=True)
class ModelResponse[T: Contract]:
    result: T
    usage: Usage = Usage()
    retry_count: int = 0


class ProviderFailure(Exception):
    def __init__(
        self, category: FailureCategory, *, retries: int = 0, usage: Usage | None = None
    ):
        super().__init__(str(category))
        self.category = category
        self.retries = retries
        self.usage = usage


class ModelProvider:
    model: str

    async def generate[T: Contract](
        self,
        *,
        instructions: str,
        data: str,
        schema: type[T],
        timeout: float,
        output_tokens: int,
    ) -> ModelResponse[T]:
        raise NotImplementedError
