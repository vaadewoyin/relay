from uuid import uuid4

import httpx
import pytest

from relay.demo import DAY, EVENING, INCOMING, OUTGOING, PUMP, at, seed
from relay.domain import ActionItem
from relay.notion.client import API_VERSION, NotionClient, NotionError, Sources
from relay.notion.sync import NotionSync
from relay.service import AcceptHandover, PreviewHandover, RelayService
from relay.store import SQLiteStore


def test_http_query_paginates_retries_429_and_uses_data_source():
    requests = []

    def handler(request):
        requests.append(request)
        assert request.headers["Notion-Version"] == API_VERSION
        if len(requests) == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(
            200,
            json={
                "results": [{"id": str(len(requests))}],
                "has_more": len(requests) == 2,
                "next_cursor": "second",
            },
        )

    source = uuid4()
    client = NotionClient("placeholder", transport=httpx.MockTransport(handler))
    assert len(list(client.pages(source))) == 2
    assert all(
        request.url.path == f"/v1/data_sources/{source}/query" for request in requests
    )
    assert b"start_cursor" in requests[-1].content
    client.close()


def test_ambiguous_create_timeout_is_never_retried_by_transport():
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("test")

    client = NotionClient("placeholder", transport=httpx.MockTransport(handler))
    with pytest.raises(NotionError) as error:
        client.create(uuid4(), {})
    assert error.value.possibly_created and error.value.code == "timeout"
    assert len(calls) == 1
    client.close()


def report_page():
    return {
        "id": str(uuid4()),
        "url": "https://www.notion.so/test",
        "last_edited_time": at(14).isoformat(),
        "properties": {
            name: {"type": "rich_text", "rich_text": [{"plain_text": content}]}
            for name, content in {
                "Shift ID": str(DAY.id),
                "Operator ID": str(OUTGOING.id),
                "Asset ID": str(PUMP.id),
                "Report": "Pump stalled during the test.",
                "Action": "Inspect pump.",
                "Action Owner": str(OUTGOING.id),
            }.items()
        }
        | {
            "Observed": {"type": "date", "date": {"start": at(13).isoformat()}},
            "Synthetic": {"type": "checkbox", "checkbox": True},
        },
    }


class FakeAdapter:
    def __init__(self, reports):
        self.reports = reports
        self.rows = {}
        self.calls = 0
        self.failure = None

    def pages(self, source, key=None):
        if key is None:
            yield from self.reports
        elif (source, key) in self.rows:
            yield self.rows[source, key]

    def create(self, source, properties):
        self.calls += 1
        failure = self.failure
        if failure == "forbidden":
            raise NotionError(failure)
        key = properties["Relay ID"]["rich_text"][0]["text"]["content"]
        row = {"id": str(uuid4())}
        self.rows[source, key] = row
        if failure == "timeout":
            raise NotionError(failure, possibly_created=True)
        return row


def test_import_external_edit_and_publication_keep_local_authority(tmp_path):
    store = SQLiteStore(tmp_path / "relay.sqlite3")
    seed(store)
    page = report_page()
    remote = FakeAdapter([page, {"id": "malformed"}])
    sync = NotionSync(remote, Sources(uuid4(), uuid4(), uuid4()), store)
    result = sync.pull()
    assert (result.imported, result.invalid) == (1, 1)
    assert sync.pull().unchanged == 1
    service = RelayService(store, clock=lambda: at(15))
    local = service.report(result.report_ids[0])
    assert str(local.report.source_url) == page["url"]
    page["properties"]["Report"]["rich_text"][0]["plain_text"] = "Pump was fine."
    assert sync.pull().modified == 1
    assert (
        service.report(local.report.id).report.text == "Pump stalled during the test."
    )
    preview = service.preview(
        PreviewHandover(
            operation_id=uuid4(),
            actor_id=OUTGOING.id,
            outgoing_shift_id=DAY.id,
            incoming_shift_id=EVENING.id,
        )
    )
    receipt = service.accept(
        preview.id,
        AcceptHandover(
            operation_id=uuid4(),
            actor_id=INCOMING.id,
            expected_version=preview.version,
            confirmed=True,
        ),
    )
    assert sync.status(receipt) == "pending"
    remote.failure = "forbidden"
    assert all(item.state == "pending" for item in sync.publish(receipt))
    assert service.get(ActionItem, local.actions[0].id).owner_id == INCOMING.id
    assert not remote.rows
    remote.failure = "timeout"
    assert all(item.state == "uncertain" for item in sync.publish(receipt))
    assert sync.status(receipt) == "uncertain"
    assert len(remote.rows) == 2
    calls = remote.calls
    restarted = NotionSync(remote, sync.sources, SQLiteStore(store.path))
    remote.failure = None
    assert all(item.state == "synced" for item in restarted.publish(receipt))
    assert restarted.status(receipt) == "synced"
    assert remote.calls == calls
    assert restarted.publish(receipt) == restarted.publish(receipt)
    assert len(remote.rows) == 2
