from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime

from relay.domain import Contract, Record

type SyncStatus = Literal["pending", "synced", "uncertain"]


class Publication(Record):
    state: SyncStatus
    remote_id: UUID | None = None
    updated_at: AwareDatetime
    remote_revision: str | None = None
    remote_fingerprint: str | None = None
    failure: str | None = None


class ImportResult(Contract):
    imported: int = 0
    unchanged: int = 0
    modified: int = 0
    invalid: int = 0
    report_ids: tuple[UUID, ...] = ()
    failures: dict[str, str] = {}
    failure: str | None = None
