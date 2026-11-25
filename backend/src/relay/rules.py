from datetime import datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from relay.domain import (
    ActionItem,
    AssetStatus,
    EvidenceReference,
    FindingType,
    IntegrityFinding,
    OperationalReport,
    Severity,
)


def finding(
    kind: FindingType,
    severity: Severity,
    explanation: str,
    recommendation: str,
    reports: tuple[OperationalReport, ...],
    now: datetime,
    subject: str,
) -> IntegrityFinding:
    return IntegrityFinding(
        id=uuid5(NAMESPACE_URL, f"relay:{kind}:{subject}"),
        type=kind,
        severity=severity,
        explanation=explanation,
        recommended_action=recommendation,
        evidence=tuple(EvidenceReference.from_report(report) for report in reports),
        created_at=now,
    )


def missing_owner(
    action: ActionItem, report: OperationalReport, now: datetime
) -> IntegrityFinding | None:
    if action.status.unresolved and action.owner_id is None:
        return finding(
            FindingType.MISSING_OWNER,
            Severity.WARNING,
            "An unresolved action has no owner.",
            "Assign an operator to the action.",
            (report,),
            now,
            str(action.id),
        )
    return None


def overdue_action(
    action: ActionItem, report: OperationalReport, now: datetime
) -> IntegrityFinding | None:
    if action.status.unresolved and action.due_at is not None and action.due_at < now:
        return finding(
            FindingType.OVERDUE_ACTION,
            Severity.HIGH,
            "An unresolved action is past its due time.",
            "Review and prioritize the action.",
            (report,),
            now,
            str(action.id),
        )
    return None


def duplicate_report(
    latest: OperationalReport, previous: OperationalReport, now: datetime
) -> IntegrityFinding | None:
    same_scope = (
        latest.shift_id == previous.shift_id and latest.asset_id == previous.asset_id
    )
    same_text = latest.text.split() == previous.text.split()
    if same_scope and (latest.source_ref == previous.source_ref or same_text):
        return finding(
            FindingType.DUPLICATE_REPORT,
            Severity.WARNING,
            "Two reports in the same shift and asset share a source reference or normalized text.",
            "Review both source reports before acting on duplicated work.",
            (previous, latest),
            now,
            ":".join(sorted((str(previous.id), str(latest.id)))),
        )
    return None


def contradictory_status(
    latest: OperationalReport, previous: OperationalReport, now: datetime
) -> IntegrityFinding | None:
    blocked = {AssetStatus.FAULTED, AssetStatus.OUT_OF_SERVICE}
    statuses = {latest.asset_status, previous.asset_status}
    same_observation = (
        latest.asset_id == previous.asset_id
        and latest.observed_at == previous.observed_at
    )
    if same_observation and AssetStatus.OPERATIONAL in statuses and statuses & blocked:
        return finding(
            FindingType.CONTRADICTORY_ASSET_STATUS,
            Severity.HIGH,
            "The same asset and observation time were reported as operational and unavailable.",
            "Verify the asset in person before relying on its operational status.",
            (previous, latest),
            now,
            ":".join(sorted((str(previous.id), str(latest.id)))),
        )
    return None


def stale_version(
    record_id: UUID,
    expected: int,
    current: int,
    reports: tuple[OperationalReport, ...],
    now: datetime,
    *,
    snapshot_changed: bool = False,
) -> IntegrityFinding | None:
    if expected == current and not snapshot_changed:
        return None
    explanation = (
        "Work in the handover changed after preview."
        if snapshot_changed
        else f"Update expected version {expected}; the current version is {current}."
    )
    return finding(
        FindingType.STALE_VERSION,
        Severity.WARNING,
        explanation,
        "Refresh the record or preview before submitting a new action.",
        reports,
        now,
        f"{record_id}:{expected}:{current}:{snapshot_changed}",
    )


def unresolved_responsibility(
    action: ActionItem,
    report: OperationalReport,
    outgoing_operator: UUID,
    now: datetime,
) -> IntegrityFinding | None:
    if action.status.unresolved and action.owner_id != outgoing_operator:
        return finding(
            FindingType.UNRESOLVED_RESPONSIBILITY,
            Severity.HIGH,
            "Unresolved work cannot transfer because it is unassigned or assigned to another operator.",
            "Confirm ownership separately and keep this item on the outgoing shift.",
            (report,),
            now,
            f"{action.shift_id}:{action.id}:{action.version}",
        )
    return None
