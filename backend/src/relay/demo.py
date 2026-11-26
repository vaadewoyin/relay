"""Synthetic facilities demo. Seed local reference data, then exercise the HTTP API."""

import argparse
import json
from datetime import UTC, datetime
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import NAMESPACE_URL, UUID, uuid5

from relay.api import database_path
from relay.domain import Asset, AssetStatus, Operator, Shift
from relay.service import NewAction, RelayService, ReportIntake
from relay.store import SQLiteStore


def demo_id(label: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"relay:synthetic:facilities-v1:{label}")


def at(hour: int, minute: int = 0) -> datetime:
    return datetime(2025, 11, 26, hour, minute, tzinfo=UTC)


OUTGOING = Operator(id=demo_id("operator-maintainer"), name="Synthetic maintainer Ada")
INCOMING = Operator(id=demo_id("operator-receiver"), name="Synthetic maintainer Tunde")
DAY = Shift(id=demo_id("day"), operator_id=OUTGOING.id, starts_at=at(6), ends_at=at(14))
EVENING = Shift(
    id=demo_id("evening"), operator_id=INCOMING.id, starts_at=at(14), ends_at=at(22)
)
PUMP = Asset(id=demo_id("pump"), name="Synthetic loading-dock sump pump P-17")


def seed(store: SQLiteStore) -> None:
    store.initialize()
    with store.transaction(write=True) as tx:
        for record in (OUTGOING, INCOMING, DAY, EVENING, PUMP):
            tx.insert(record, ignore_duplicate=True)


def reports() -> tuple[ReportIntake, ...]:
    def observation(
        label: str, text: str, status: AssetStatus, actions: tuple[NewAction, ...] = ()
    ) -> ReportIntake:
        return ReportIntake(
            operation_id=demo_id(f"report:{label}"),
            source_ref=f"synthetic:dock:{label}",
            shift_id=DAY.id,
            author_id=OUTGOING.id,
            asset_id=PUMP.id,
            observed_at=at(13, 30),
            text=text,
            asset_status=status,
            actions=actions,
            synthetic=True,
        )

    fault = "Synthetic report: Pump P-17 tripped twice under load. The dock bypass is active."
    return (
        observation(
            "fault",
            fault,
            AssetStatus.FAULTED,
            (
                NewAction(
                    description="Inspect the overload relay and test pump P-17.",
                    owner_id=OUTGOING.id,
                    due_at=at(13, 50),
                ),
                NewAction(description="Assign someone to inspect the bypass line."),
            ),
        ),
        observation(
            "panel",
            "Synthetic report: The control panel recorded P-17 as available at the same reading.",
            AssetStatus.OPERATIONAL,
        ),
        observation("copied-fault", fault, AssetStatus.FAULTED),
    )


def prepare_wearable(store: SQLiteStore) -> dict[str, str]:
    """Ingest the fixture without reviewing findings or accepting responsibility."""
    seed(store)
    service = RelayService(store)
    for report in reports():
        service.intake(report)
    return wearable_context()


def wearable_context() -> dict[str, str]:
    return {
        "outgoingShiftId": str(DAY.id),
        "incomingShiftId": str(EVENING.id),
        "outgoingOperatorId": str(OUTGOING.id),
        "incomingOperatorId": str(INCOMING.id),
        "incomingName": INCOMING.name,
        "shiftLabel": "Evening shift | Synthetic",
    }


def prepare_intelligence(store: SQLiteStore) -> dict[str, str]:
    context = prepare_wearable(store)
    damper = Asset(id=demo_id("damper"), name="Synthetic east stair smoke damper FD-22")
    with store.transaction(write=True) as tx:
        tx.insert(damper, ignore_duplicate=True)
    service = RelayService(store)
    for label, text in (
        (
            "field",
            "During the 13:35 alarm test, east stair damper FD-22 stayed fully open until the alarm cleared. The linkage did not move.",
        ),
        (
            "panel",
            "For the same 13:35 alarm test, I watched east stair damper FD-22 shut completely when the alarm began. It stayed closed until reset.",
        ),
    ):
        service.intake(
            ReportIntake(
                operation_id=demo_id(f"semantic:{label}"),
                source_ref=f"synthetic:damper:{label}",
                shift_id=DAY.id,
                author_id=OUTGOING.id,
                asset_id=damper.id,
                observed_at=at(13, 35),
                text=f"Synthetic report: {text}",
                synthetic=True,
            )
        )
    return context


def run(base: str) -> dict[str, object]:
    def request(
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        expected: int = 200,
    ) -> Any:
        body = json.dumps(payload).encode() if payload is not None else None
        req = Request(
            f"{base.rstrip('/')}{path}",
            body,
            {"Content-Type": "application/json"},
            method=method,
        )
        try:
            with urlopen(req, timeout=10) as response:
                code, data = response.status, json.load(response)
        except HTTPError as exc:
            with exc:
                code, data = exc.code, json.load(exc)
        if code != expected:
            raise RuntimeError(
                f"{method} {path} returned {code}, expected {expected}: {data}"
            )
        return data

    def verify(condition: bool, message: str) -> None:
        if not condition:
            raise RuntimeError(message)

    request("GET", "/health")
    commands = reports()
    created = [
        request("POST", "/reports", report.model_dump(mode="json"), 201)
        for report in commands
    ]
    initial = created[0]
    retry = request("POST", "/reports", commands[0].model_dump(mode="json"), 201)
    verify(initial == retry, "Report retry returned a different result.")
    report_id = initial["report"]["id"]
    action = next(item for item in initial["actions"] if item["owner_id"])
    action_url = f"/actions/{action['id']}"
    update = {
        "operation_id": str(demo_id("action:start")),
        "actor_id": str(OUTGOING.id),
        "expected_version": action["version"],
        "status": "in_progress",
    }
    request("PATCH", action_url, update)
    current = request("GET", f"/reports/{report_id}")
    current_action = next(
        item for item in current["actions"] if item["id"] == action["id"]
    )
    stale_update = request(
        "PATCH",
        action_url,
        {
            **update,
            "operation_id": str(demo_id("action:stale")),
            "status": "resolved",
            "actor_id": current_action["owner_id"],
            "expected_version": action["version"],
        },
        409,
    )
    verify(
        stale_update["code"] == "stale_version", "Stale action update was not rejected."
    )

    preview = request(
        "POST",
        "/handovers",
        {
            "operation_id": str(demo_id("handover:preview")),
            "outgoing_shift_id": str(DAY.id),
            "incoming_shift_id": str(EVENING.id),
            "actor_id": str(OUTGOING.id),
        },
        201,
    )
    report_ids = {item["report"]["id"] for item in created}
    findings = [
        item
        for item in request("GET", "/findings")
        if any(ref["report_id"] in report_ids for ref in item["evidence"])
    ]
    kinds = {item["type"] for item in findings}
    verify(
        kinds
        == {
            "missing_owner",
            "overdue_action",
            "duplicate_report",
            "stale_version",
            "unresolved_responsibility",
            "contradictory_asset_status",
        },
        f"Unexpected rule results: {sorted(kinds)}",
    )
    for finding in findings:
        for reference in finding["evidence"]:
            source = request("GET", f"/reports/{reference['report_id']}")["report"]
            verify(
                source["text"] == reference["quote"],
                "Evidence differed from stored report.",
            )
            verify(
                source["source_ref"] == reference["source_ref"],
                "Source reference differed.",
            )
    overdue = next(item for item in findings if item["type"] == "overdue_action")
    decision = request(
        "POST",
        f"/findings/{overdue['id']}/reviews",
        {
            "operation_id": str(demo_id("review:overdue")),
            "reviewer_id": str(INCOMING.id),
            "outcome": "confirmed",
            "reason": "Synthetic exercise: the maintenance deadline elapsed with the fault open.",
        },
        201,
    )
    acceptance = {
        "operation_id": str(demo_id("handover:accept")),
        "actor_id": str(INCOMING.id),
        "expected_version": preview["version"],
        "confirmed": True,
    }
    acceptance_url = f"/handovers/{preview['id']}/acceptance"
    receipt = request("POST", acceptance_url, acceptance, 201)
    verify(
        receipt == request("POST", acceptance_url, acceptance, 201),
        "Receipt retry differed.",
    )
    verify(
        receipt == request("GET", f"/handover-receipts/{receipt['id']}"),
        "Receipt was not stored.",
    )
    repeat = request(
        "POST",
        acceptance_url,
        {
            **acceptance,
            "operation_id": str(demo_id("handover:duplicate-accept")),
        },
        409,
    )
    verify(
        repeat["code"] == "handover_already_accepted", "Duplicate acceptance succeeded."
    )
    current = request("GET", f"/reports/{report_id}")
    transferred = next(
        item for item in current["actions"] if item["id"] == action["id"]
    )
    verify(
        transferred["owner_id"] == str(INCOMING.id)
        and transferred["shift_id"] == str(EVENING.id)
        and len(receipt["outstanding"]) == 1,
        "Unexpected transfer or outstanding work.",
    )
    return {
        "synthetic": True,
        "report_count": len(created),
        "finding_types": sorted(kinds),
        "stale_update": stale_update["code"],
        "review_id": decision["id"],
        "receipt_id": receipt["id"],
        "transferred": len(receipt["transferred"]),
        "outstanding": len(receipt["outstanding"]),
        "duplicate_acceptance": repeat["code"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=("seed", "prepare-wearable", "prepare-intelligence", "run")
    )
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    if args.command == "seed":
        seed(SQLiteStore(database_path()))
        print("Seeded synthetic operators, shifts and asset.")
    elif args.command == "prepare-wearable":
        print(json.dumps(prepare_wearable(SQLiteStore(database_path()))))
    elif args.command == "prepare-intelligence":
        print(json.dumps(prepare_intelligence(SQLiteStore(database_path()))))
    else:
        print(json.dumps(run(args.url), indent=2))


if __name__ == "__main__":
    main()
