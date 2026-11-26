import json
import logging
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from httpx import Response

from relay.api import create_app
from relay.demo import DAY, EVENING, INCOMING, OUTGOING, at, reports, seed
from relay.store import SQLiteStore


@pytest.fixture
def db(tmp_path: Path) -> Path:
    path = tmp_path / "relay.sqlite3"
    seed(SQLiteStore(path))
    return path


@pytest.fixture
def client(db: Path):
    with TestClient(create_app(db, clock=lambda: at(15))) as test_client:
        yield test_client


def check(response: Response, status: int, code: str | None = None) -> dict:
    assert response.status_code == status, response.text
    payload = response.json()
    if code:
        assert payload["code"] == code
        assert payload["request_id"] == response.headers["X-Request-ID"]
    return payload


def ingest(client: TestClient) -> dict:
    return check(
        client.post("/reports", json=reports()[0].model_dump(mode="json")), 201
    )


def preview(client: TestClient) -> dict:
    return check(
        client.post(
            "/handovers",
            json={
                "operation_id": str(uuid4()),
                "actor_id": str(OUTGOING.id),
                "outgoing_shift_id": str(DAY.id),
                "incoming_shift_id": str(EVENING.id),
            },
        ),
        201,
    )


def acceptance() -> dict:
    return {
        "operation_id": str(uuid4()),
        "actor_id": str(INCOMING.id),
        "expected_version": 1,
        "confirmed": True,
    }


def owned_action(record: dict) -> dict:
    return next(item for item in record["actions"] if item["owner_id"])


def test_report_idempotency_input_errors_and_logs(client: TestClient, caplog):
    caplog.set_level(logging.INFO, logger="relay.api")
    assert check(client.get("/health"), 200) == {"status": "ok"}
    assert (
        "/handovers/{handover_id}/acceptance"
        in client.get("/openapi.json").json()["paths"]
    )
    intake = reports()[0].model_dump(mode="json")
    existing = ingest(client)
    assert existing == ingest(client)
    check(
        client.post("/reports", json={**intake, "text": "Changed"}),
        409,
        "operation_id_reused",
    )
    invalid = check(
        client.post("/reports", json={"text": "private invalid payload"}),
        422,
        "validation_error",
    )
    assert "private invalid payload" not in json.dumps(invalid)
    check(client.get(f"/reports/{uuid4()}"), 404, "not_found")
    bad_owner = {
        **intake,
        "operation_id": str(uuid4()),
        "actions": [
            intake["actions"][0],
            {**intake["actions"][1], "owner_id": str(uuid4())},
        ],
    }
    check(client.post("/reports", json=bad_owner), 404, "not_found")
    bad_owner["actions"][1]["owner_id"] = None
    assert (
        check(client.post("/reports", json=bad_owner), 201)["report"]["id"]
        != existing["report"]["id"]
    )
    events = [
        json.loads(item.message) for item in caplog.records if item.name == "relay.api"
    ]
    assert any(
        event["event"] == "http_request" and event["route"] == "/reports"
        for event in events
    )
    assert reports()[0].text not in caplog.text
    assert "private invalid payload" not in caplog.text


def test_findings_evidence_and_review(client: TestClient):
    for report in reports():
        check(client.post("/reports", json=report.model_dump(mode="json")), 201)
    findings = client.get("/findings").json()
    assert {item["type"] for item in findings} == {
        "missing_owner",
        "overdue_action",
        "duplicate_report",
        "contradictory_asset_status",
    }
    for finding in findings:
        for evidence in finding["evidence"]:
            source = client.get(f"/reports/{evidence['report_id']}").json()["report"]
            assert (source["source_ref"], source["text"]) == (
                evidence["source_ref"],
                evidence["quote"],
            )
    finding_url = f"/findings/{findings[0]['id']}"
    review = {
        "operation_id": str(uuid4()),
        "reviewer_id": str(INCOMING.id),
        "outcome": "confirmed",
        "reason": "Synthetic report independently verified.",
    }
    review_url = f"{finding_url}/reviews"
    decision = check(client.post(review_url, json=review), 201)
    assert check(client.post(review_url, json=review), 201) == decision
    assert check(client.get(f"/reviews/{decision['id']}"), 200) == decision
    assert check(client.get(finding_url), 200)["review_status"] == "confirmed"
    check(
        client.post(review_url, json={**review, "operation_id": str(uuid4())}),
        409,
        "finding_already_reviewed",
    )


def test_stale_action_and_handover_rejection(client: TestClient):
    report = ingest(client)
    handover = preview(client)
    action_id = owned_action(report)["id"]
    update = {
        "operation_id": str(uuid4()),
        "actor_id": str(OUTGOING.id),
        "expected_version": 1,
        "status": "in_progress",
    }
    action_url = f"/actions/{action_id}"
    updated = check(client.patch(action_url, json=update), 200)
    assert updated["version"] == 2
    assert check(client.patch(action_url, json=update), 200) == updated
    check(
        client.patch(
            action_url,
            json={**update, "operation_id": str(uuid4()), "status": "resolved"},
        ),
        409,
        "stale_version",
    )
    check(
        client.patch(
            action_url,
            json={
                **update,
                "operation_id": str(uuid4()),
                "expected_version": 2,
                "status": "open",
            },
        ),
        409,
        "invalid_action_transition",
    )
    accept_url = f"/handovers/{handover['id']}/acceptance"
    check(client.post(accept_url, json=acceptance()), 409, "stale_version")
    assert (
        check(client.get(f"/handovers/{handover['id']}"), 200)["status"] == "previewed"
    )
    assert (
        owned_action(check(client.get(f"/reports/{report['report']['id']}"), 200))
        == updated
    )
    stale = [
        finding
        for finding in client.get("/findings").json()
        if finding["type"] == "stale_version"
    ]
    assert len(stale) == 2
    assert all(
        finding["evidence"][0]["report_id"] == report["report"]["id"]
        for finding in stale
    )
    new_preview = preview(client)
    assert (
        check(
            client.post(
                f"/handovers/{new_preview['id']}/acceptance", json=acceptance()
            ),
            201,
        )["transferred"][0]["version"]
        == 3
    )


def test_acceptance_authorization_idempotency_and_database_reopen(
    client: TestClient, db: Path
):
    report = ingest(client)
    handover = preview(client)
    payload = acceptance()
    path = f"/handovers/{handover['id']}/acceptance"
    check(
        client.post(path, json={**payload, "actor_id": str(OUTGOING.id)}),
        403,
        "forbidden",
    )
    check(
        client.post(path, json={**payload, "confirmed": False}),
        422,
        "invalid_operation",
    )
    check(
        client.post(path, json={**payload, "expected_version": 99}),
        409,
        "stale_version",
    )
    receipt = check(client.post(path, json=payload), 201)
    assert len(receipt["transferred"]) == len(receipt["outstanding"]) == 1
    assert receipt["transferred"][0]["owner_id"] == str(INCOMING.id)
    assert receipt["transferred"][0]["shift_id"] == str(EVENING.id)
    assert receipt["outstanding"][0]["owner_id"] is None
    assert receipt["outstanding"][0]["shift_id"] == str(DAY.id)
    check(
        client.post(path, json={**payload, "operation_id": str(uuid4())}),
        409,
        "handover_already_accepted",
    )
    with TestClient(create_app(db)) as reopened:
        assert (
            check(reopened.get(f"/handover-receipts/{receipt['id']}"), 200) == receipt
        )
        assert check(reopened.post(path, json=payload), 201) == receipt
        assert check(reopened.get(f"/handovers/{handover['id']}"), 200)["version"] == 2
        persisted = check(reopened.get(f"/reports/{report['report']['id']}"), 200)
        assert owned_action(persisted) == receipt["transferred"][0]


def test_handover_rolls_back_all_writes_on_receipt_failure(
    client: TestClient, db: Path
):
    report = ingest(client)
    handover = preview(client)
    accept_url = f"/handovers/{handover['id']}/acceptance"
    payload = acceptance()
    with sqlite3.connect(db) as connection:
        connection.execute("""
            CREATE TRIGGER fail_receipt BEFORE INSERT ON receipts
            BEGIN SELECT RAISE(ABORT, 'synthetic test failure'); END
        """)
    check(client.post(accept_url, json=payload), 500, "internal_error")
    current = check(client.get(f"/reports/{report['report']['id']}"), 200)
    assert owned_action(current) == owned_action(report)
    assert (
        check(client.get(f"/handovers/{handover['id']}"), 200)["status"] == "previewed"
    )
    with sqlite3.connect(db) as connection:
        assert connection.execute("SELECT COUNT(*) FROM receipts").fetchone()[0] == 0
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM operations WHERE id = ?",
                (payload["operation_id"],),
            ).fetchone()[0]
            == 0
        )
        connection.execute("DROP TRIGGER fail_receipt")
    check(client.post(accept_url, json=payload), 201)


def test_competing_acceptances_create_only_one_receipt(client: TestClient, db: Path):
    ingest(client)
    handover = preview(client)
    path = f"/handovers/{handover['id']}/acceptance"

    def submit(payload: dict) -> int:
        return client.post(path, json=payload).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = sorted(pool.map(submit, [acceptance(), acceptance()]))
    assert statuses == [201, 409]
    with sqlite3.connect(db) as connection:
        assert connection.execute("SELECT COUNT(*) FROM receipts").fetchone()[0] == 1


def test_preview_includes_unassigned_work_without_allowing_empty_transfer(
    client: TestClient,
):
    report = reports()[0]
    command = report.model_copy(update={"actions": (report.actions[1],)})
    check(client.post("/reports", json=command.model_dump(mode="json")), 201)
    handover = preview(client)
    assert not handover["actions"][0]["transferable"]
    check(
        client.post(f"/handovers/{handover['id']}/acceptance", json=acceptance()),
        409,
        "no_transferable_actions",
    )
    assert {f["type"] for f in client.get("/findings").json()} == {
        "missing_owner",
        "unresolved_responsibility",
    }


def test_new_work_invalidates_preview_and_supplies_stale_evidence(client: TestClient):
    original = ingest(client)
    handover = preview(client)
    late = reports()[0].model_copy(
        update={
            "operation_id": uuid4(),
            "source_ref": "synthetic:dock:late",
            "text": "Synthetic report: the bypass alarm tripped during turnover.",
            "actions": (reports()[0].actions[0],),
        }
    )
    new_report = check(client.post("/reports", json=late.model_dump(mode="json")), 201)
    path = f"/handovers/{handover['id']}/acceptance"
    check(client.post(path, json=acceptance()), 409, "stale_version")
    finding = next(
        f for f in client.get("/findings").json() if f["type"] == "stale_version"
    )
    assert {item["report_id"] for item in finding["evidence"]} == {
        original["report"]["id"],
        new_report["report"]["id"],
    }
    current = check(client.get(f"/actions/{owned_action(original)['id']}"), 200)
    assert current["owner_id"] == str(OUTGOING.id)


def test_wearable_fixture_leaves_reviewer_and_receiver_actions_pending(tmp_path: Path):
    from relay.demo import prepare_wearable

    path = tmp_path / "wearable.sqlite3"
    store = SQLiteStore(path)
    context = prepare_wearable(store)
    assert prepare_wearable(store) == context
    assert context["incomingOperatorId"] == str(INCOMING.id)
    with TestClient(create_app(path)) as client:
        findings = check(client.get("/findings"), 200)
        assert len(findings) == 5
        assert all(finding["review_status"] == "pending" for finding in findings)
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM reports").fetchone()[0] == 3
        assert connection.execute("SELECT COUNT(*) FROM receipts").fetchone()[0] == 0


def test_remote_browser_origins_cannot_mutate_loopback_api(client: TestClient):
    body = reports()[0].model_dump(mode="json")
    for origin in (
        "https://outside.example",
        "null",
        "http://localhost@outside.example",
    ):
        response = client.post("/reports", json=body, headers={"Origin": origin})
        assert response.status_code == 403
        assert response.json()["code"] == "forbidden_origin"
    local = client.post(
        "/reports", json=body, headers={"Origin": "http://127.0.0.1:5173"}
    )
    assert local.status_code == 201
