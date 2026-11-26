from uuid import uuid4

from fastapi.testclient import TestClient

from relay.api import create_app
from relay.demo import DAY, prepare_wearable
from relay.intelligence.gemini import GeminiProvider
from relay.store import SQLiteStore


def test_unconfigured_ai_is_a_persisted_failure_and_deterministic_api_stays_available(
    tmp_path,
):
    path = tmp_path / "relay.sqlite3"
    prepare_wearable(SQLiteStore(path))
    operation = str(uuid4())
    with TestClient(create_app(path, model_provider=GeminiProvider(None))) as client:
        payload = {"shift_id": str(DAY.id), "operation_id": operation}
        before = client.get("/findings").json()
        response = client.post("/ai/analyses", json=payload)
        assert response.status_code == 200
        result = response.json()
        assert result["failure"] == "not_configured"
        assert result["request_id"] == response.headers["X-Request-ID"]
        assert result["id"] == operation
        assert result["finding_ids"] == []
        assert client.post("/ai/analyses", json=payload).json() == result
        assert client.get(f"/ai/analyses/{operation}").json() == result
        assert client.get("/findings").json() == before
        assert (
            client.post(
                "/ai/analyses", json={**payload, "shift_id": str(uuid4())}
            ).status_code
            == 409
        )
        assert (
            client.post("/ai/analyses", json={**payload, "mutate": True}).status_code
            == 422
        )
        assert client.get("/health").json() == {"status": "ok"}
