from datetime import timedelta

import pytest
from pydantic import ValidationError

from relay import rules
from relay.demo import DAY, EVENING, INCOMING, OUTGOING, at, demo_id, reports
from relay.domain import (
    ActionItem,
    ActionSnapshot,
    ActionStatus,
    AssetStatus,
    Conflict,
    FindingType,
    Forbidden,
    Handover,
    HandoverStatus,
    OperationalReport,
    Severity,
)


def report(index: int = 0) -> OperationalReport:
    command = reports()[index]
    return OperationalReport(
        id=demo_id(f"rule-report-{index}"),
        received_at=at(15),
        **command.model_dump(exclude={"actions", "operation_id"}),
    )


def action() -> ActionItem:
    return ActionItem(
        id=demo_id("rule-action"),
        report_id=report().id,
        shift_id=DAY.id,
        owner_id=OUTGOING.id,
        due_at=at(14),
        description="Inspect overload relay",
        updated_at=at(13),
    )


def test_domain_contracts():
    data = DAY.model_dump()
    with pytest.raises(ValidationError):
        type(DAY).model_validate({**data, "ends_at": DAY.starts_at})
    with pytest.raises(ValidationError):
        type(DAY).model_validate({**data, "ends_at": DAY.ends_at.replace(tzinfo=None)})
    with pytest.raises(ValidationError):
        OperationalReport.model_validate({**report().model_dump(), "text": "   "})
    with pytest.raises(ValidationError):
        ActionItem.model_validate({**action().model_dump(), "version": 0})


def test_action_state_and_transfer():
    item = action()
    active = item.transition(ActionStatus.IN_PROGRESS, at(14))
    assert active.version == 2
    transferred = active.transfer(DAY, EVENING, at(15))
    assert (transferred.owner_id, transferred.shift_id, transferred.version) == (
        INCOMING.id,
        EVENING.id,
        3,
    )
    resolved = transferred.transition(ActionStatus.RESOLVED, at(16))
    assert resolved.version == 4
    with pytest.raises(Conflict, match="status"):
        resolved.transition(ActionStatus.OPEN, at(16))
    with pytest.raises(Conflict, match="status"):
        active.transition(ActionStatus.OPEN, at(16))
    with pytest.raises(Conflict, match="authorized"):
        resolved.transfer(EVENING, DAY, at(17))
    with pytest.raises(Conflict, match="authorized"):
        item.transfer(EVENING, DAY, at(17))


def test_preview_acceptance_state_machine():
    item = action()
    snapshot = ActionSnapshot(
        action_id=item.id,
        report_id=item.report_id,
        version=item.version,
        transferable=True,
        description=item.description,
        owner_id=item.owner_id,
        status=item.status,
        due_at=item.due_at,
    )
    preview = Handover(
        id=demo_id("domain-preview"),
        outgoing_shift_id=DAY.id,
        incoming_shift_id=EVENING.id,
        outgoing_operator_id=OUTGOING.id,
        incoming_operator_id=INCOMING.id,
        actions=(snapshot,),
        created_at=at(14),
    )
    with pytest.raises(Forbidden):
        preview.accept(OUTGOING.id)
    with pytest.raises(ValidationError):
        Handover.model_validate(
            {**preview.model_dump(), "actions": (snapshot, snapshot)}
        )
    accepted = preview.accept(INCOMING.id)
    assert (accepted.status, accepted.version) == (HandoverStatus.ACCEPTED, 2)
    with pytest.raises(Conflict, match="receipt"):
        accepted.accept(INCOMING.id)


def test_missing_owner_and_overdue_rules():
    item, source = action(), report()
    unowned = item.model_copy(update={"owner_id": None})
    assert rules.missing_owner(item, source, at(15)) is None
    missing = rules.missing_owner(unowned, source, at(15))
    assert missing is not None and missing.type == FindingType.MISSING_OWNER
    assert missing.evidence[0].quote == source.text
    assert rules.overdue_action(item, source, at(14)) is None
    overdue = rules.overdue_action(item, source, at(15))
    assert overdue is not None and overdue.severity == Severity.HIGH
    resolved = unowned.transition(ActionStatus.RESOLVED, at(15))
    assert rules.overdue_action(resolved, source, at(16)) is None
    assert rules.missing_owner(resolved, source, at(16)) is None


def test_duplicate_and_contradictory_status_rules():
    first, panel, copied = report(), report(1), report(2)
    duplicate = rules.duplicate_report(copied, first, at(15))
    assert duplicate is not None and duplicate.type == FindingType.DUPLICATE_REPORT
    assert {ref.report_id for ref in duplicate.evidence} == {first.id, copied.id}
    assert rules.duplicate_report(panel, first, at(15)) is None
    conflict = rules.contradictory_status(panel, first, at(15))
    assert (
        conflict is not None and conflict.type == FindingType.CONTRADICTORY_ASSET_STATUS
    )
    assert tuple(ref.quote for ref in conflict.evidence) == (first.text, panel.text)
    different_time = panel.model_copy(
        update={"observed_at": first.observed_at + timedelta(minutes=1)}
    )
    assert rules.contradictory_status(different_time, first, at(15)) is None
    unstructured = panel.model_copy(update={"asset_status": None})
    assert rules.contradictory_status(unstructured, first, at(15)) is None
    unavailable = panel.model_copy(update={"asset_status": AssetStatus.OUT_OF_SERVICE})
    assert rules.contradictory_status(unavailable, first, at(15)) is None


def test_stale_and_unresolved_responsibility_rules():
    item, source = action(), report()
    assert rules.stale_version(item.id, 1, 1, (source,), at(15)) is None
    stale = rules.stale_version(item.id, 1, 2, (source,), at(15))
    assert stale is not None and stale.type == FindingType.STALE_VERSION
    assert stale.evidence[0].source_ref == source.source_ref
    changed = rules.stale_version(
        item.id, 1, 1, (source,), at(15), snapshot_changed=True
    )
    assert changed is not None and "after preview" in changed.explanation
    assert rules.unresolved_responsibility(item, source, OUTGOING.id, at(15)) is None
    unresolved = rules.unresolved_responsibility(item, source, INCOMING.id, at(15))
    assert (
        unresolved is not None
        and unresolved.type == FindingType.UNRESOLVED_RESPONSIBILITY
    )
