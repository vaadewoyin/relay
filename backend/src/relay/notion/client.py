"""The Notion data source REST boundary."""

import os
from collections.abc import Iterator
from dataclasses import dataclass
from time import sleep
from typing import Protocol
from uuid import UUID

import httpx

API_VERSION = "2026-03-11"

type JSON = dict[str, object]


class NotionError(Exception):
    def __init__(self, code: str, *, possibly_created: bool = False):
        super().__init__(code)
        self.code = code
        self.possibly_created = possibly_created


@dataclass(frozen=True)
class Sources:
    reports: UUID
    actions: UUID
    receipts: UUID

    @classmethod
    def from_environment(cls) -> "Sources":
        return cls(
            *(
                UUID(os.environ[f"NOTION_{kind}_SOURCE_ID"])
                for kind in ("REPORTS", "ACTIONS", "RECEIPTS")
            )
        )


class NotionAdapter(Protocol):
    def verify(self, source: UUID) -> None: ...
    def pages(self, source: UUID, key: str | None = None) -> Iterator[JSON]: ...
    def update(self, page: UUID, properties: JSON) -> JSON: ...
    def create(self, source: UUID, properties: JSON) -> JSON: ...


class NotionClient:
    def __init__(self, token: str, *, transport: httpx.BaseTransport | None = None):
        self.client = httpx.Client(
            base_url="https://api.notion.com/v1/",
            timeout=httpx.Timeout(8, connect=3),
            headers={"Authorization": f"Bearer {token}", "Notion-Version": API_VERSION},
            transport=transport,
        )

    def close(self) -> None:
        self.client.close()

    def request(
        self, method: str, path: str, body: JSON | None = None, *, create: bool = False
    ) -> JSON:
        for attempt in range(3):
            try:
                response = self.client.request(method, path, json=body)
            except httpx.TransportError as error:
                if not create and attempt < 2:
                    sleep(0.25 * (attempt + 1))
                    continue
                code = (
                    "timeout"
                    if isinstance(error, httpx.TimeoutException)
                    else "unavailable"
                )
                raise NotionError(code, possibly_created=create) from None
            if response.status_code == 429:
                try:
                    delay = max(0.0, float(response.headers.get("Retry-After", "1")))
                except ValueError:
                    delay = 1
                if attempt < 2 and delay <= 5:
                    sleep(delay)
                    continue
                raise NotionError("rate_limited")
            if response.status_code >= 500:
                if not create and attempt < 2:
                    sleep(0.25 * (attempt + 1))
                    continue
                raise NotionError("unavailable", possibly_created=create)
            if response.is_error:
                raise NotionError(
                    {
                        401: "unauthorized",
                        403: "forbidden",
                        404: "not_found",
                        409: "remote_conflict",
                    }.get(response.status_code, "invalid_request")
                )
            try:
                data = response.json()
            except ValueError:
                data = None
            if not isinstance(data, dict):
                raise NotionError("invalid_response", possibly_created=create)
            return data
        raise AssertionError("Retry bound exhausted.")

    def verify(self, source: UUID) -> None:
        self.request("GET", f"data_sources/{source}")

    def pages(self, source: UUID, key: str | None = None) -> Iterator[JSON]:
        body: JSON = {"page_size": 100}
        if key is not None:
            body["filter"] = {"property": "Relay ID", "rich_text": {"equals": key}}
        seen: set[str] = set()
        for _ in range(100):
            data = self.request("POST", f"data_sources/{source}/query", body)
            rows = data.get("results")
            if not isinstance(rows, list) or not all(
                isinstance(row, dict) for row in rows
            ):
                raise NotionError("invalid_response")
            yield from rows
            if data.get("has_more") is False:
                return
            cursor = data.get("next_cursor")
            if not isinstance(cursor, str) or cursor in seen:
                raise NotionError("invalid_cursor")
            seen.add(cursor)
            body["start_cursor"] = cursor
        raise NotionError("pagination_limit")

    def create(self, source: UUID, properties: JSON) -> JSON:
        return self.request(
            "POST",
            "pages",
            {
                "parent": {"type": "data_source_id", "data_source_id": str(source)},
                "properties": properties,
            },
            create=True,
        )

    def update(self, page: UUID, properties: JSON) -> JSON:
        # Re-read the page before retrying an ambiguous write.
        return self.request(
            "PATCH", f"pages/{page}", {"properties": properties}, create=True
        )
