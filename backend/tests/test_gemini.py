import asyncio

import pytest
from google.genai import errors, types

from relay.intelligence.contracts import FailureCategory, ProposalBatch
from relay.intelligence.gemini import DEFAULT_MODEL, GeminiProvider
from relay.intelligence.provider import ProviderFailure


def generate(provider, timeout=3):
    return asyncio.run(
        provider.generate(
            instructions="Only structured read-only findings.",
            data="{}",
            schema=ProposalBatch,
            timeout=timeout,
            output_tokens=400,
        )
    )


def fake_sdk(monkeypatch, responses):
    requests = []

    class Client:
        def __init__(self, **options):
            assert options["http_options"].retry_options.attempts == 1
            self.aio = self
            self.models = self

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            pass

        async def generate_content(self, **options):
            requests.append(options)
            response = responses.pop(0)
            if isinstance(response, Exception):
                raise response
            if response is None:
                await asyncio.sleep(1)
            return response

    monkeypatch.setattr("relay.intelligence.gemini.genai.Client", Client)
    return requests


def response(body):
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                finish_reason="STOP",
                content=types.Content(parts=[types.Part(text=body)]),
            )
        ],
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=100, candidates_token_count=35
        ),
    )


def test_gemini_structured_response_and_bounded_retry(monkeypatch):
    body = '{"proposals":[],"abstention":{"kind":"insufficient_evidence","explanation":"Unclear."}}'
    calls = fake_sdk(monkeypatch, [errors.ServerError(503, {}), response(body)])
    result = generate(GeminiProvider("synthetic-key"))
    assert result.result.abstention
    assert result.usage.output_tokens == 35
    assert result.retry_count == 1
    assert len(calls) == 2
    assert calls[0]["model"] == DEFAULT_MODEL
    assert calls[0]["config"].response_mime_type == "application/json"
    assert calls[0]["config"].max_output_tokens == 400
    assert calls[0]["config"].tools is None


@pytest.mark.parametrize(
    ("reply", "category"),
    [
        (lambda: errors.ClientError(403, {}), FailureCategory.UNAUTHORIZED),
        (lambda: errors.ClientError(400, {}), FailureCategory.INVALID_REQUEST),
        (lambda: response("bad json"), FailureCategory.MALFORMED_OUTPUT),
        (lambda: None, FailureCategory.TIMEOUT),
    ],
)
def test_gemini_failure_categories(monkeypatch, reply, category):
    calls = fake_sdk(monkeypatch, [reply()])
    with pytest.raises(ProviderFailure) as failure:
        generate(GeminiProvider("synthetic-key"), timeout=0.08)
    assert failure.value.category == category
    assert failure.value.http_status == {
        FailureCategory.UNAUTHORIZED: 403,
        FailureCategory.INVALID_REQUEST: 400,
    }.get(category)
    assert len(calls) == 1


def test_missing_credentials_are_an_explicit_provider_failure():
    with pytest.raises(ProviderFailure) as failure:
        generate(GeminiProvider(None))
    assert failure.value.category == FailureCategory.NOT_CONFIGURED


def test_wire_schema_omits_grammar_limits_but_local_contract_remains_strict():
    from relay.intelligence.gemini import supported_schema

    complete = ProposalBatch.model_json_schema()
    wire = str(supported_schema(complete))
    assert "maxItems" in str(complete)
    assert "maxItems" not in wire
    assert "additionalProperties" not in wire
    assert "semantic_contradiction" in wire
