"""Provision a dedicated Notion demo parent and seed synthetic report rows."""

import argparse
import json
import os
from uuid import UUID

from relay.api import database_path
from relay.demo import DAY, OUTGOING, PUMP, at, seed, wearable_context
from relay.notion.client import NotionClient, Sources
from relay.notion.mapping import rich_text
from relay.store import SQLiteStore

SCHEMA = {
    "Shift Reports": {
        "Name": "title",
        "Relay ID": "rich_text",
        "Shift ID": "rich_text",
        "Operator ID": "rich_text",
        "Asset ID": "rich_text",
        "Observed": "date",
        "Report": "rich_text",
        "Action": "rich_text",
        "Action Owner": "rich_text",
        "Synthetic": "checkbox",
    },
    "Action Register": {
        "Name": "title",
        "Relay ID": "rich_text",
        "Action ID": "rich_text",
        "Receipt ID": "rich_text",
        "Owner": "rich_text",
        "Owner ID": "rich_text",
        "Status": "rich_text",
        "Version": "number",
        "Source": "url",
        "Sync Status": "rich_text",
    },
    "Handover Receipts": {
        "Name": "title",
        "Relay ID": "rich_text",
        "Accepted": "date",
        "Outcome": "rich_text",
        "Accepted By": "rich_text",
        "Outgoing Shift": "rich_text",
        "Incoming Shift": "rich_text",
        "Sync Status": "rich_text",
    },
}


def provision(client: NotionClient, parent: UUID) -> None:
    for (name, schema), kind in zip(
        SCHEMA.items(), ("REPORTS", "ACTIONS", "RECEIPTS"), strict=True
    ):
        variable = f"NOTION_{kind}_SOURCE_ID"
        if existing := os.getenv(variable):
            client.verify(UUID(existing))
            continue
        database = client.request(
            "POST",
            "databases",
            {
                "parent": {"type": "page_id", "page_id": str(parent)},
                "title": rich_text(name, "title")["title"],
                "is_inline": True,
                "initial_data_source": {
                    "properties": {
                        field: {
                            type_name: {"format": "number"}
                            if type_name == "number"
                            else {}
                        }
                        for field, type_name in schema.items()
                    }
                },
            },
            create=True,
        )
        print(f"{variable}={UUID(database['data_sources'][0]['id'])}", flush=True)


def seed_remote(client: NotionClient, sources: Sources) -> None:
    for key, report, action in (
        (
            "synthetic-pump-field",
            "Synthetic: During the 13:35 test I watched sump pump P-17 stall without moving any water.",
            "Inspect the overload relay and test pump P-17.",
        ),
        (
            "synthetic-pump-panel",
            "Synthetic: During the same 13:35 test, I watched P-17 sustain a strong discharge throughout.",
            "",
        ),
        (
            "synthetic-bypass",
            "Synthetic: The bypass inspection remains open and neither crew accepted it.",
            "Inspect the bypass line.",
        ),
    ):
        if list(client.pages(sources.reports, key)):
            continue
        client.create(
            sources.reports,
            {
                "Name": rich_text(key, "title"),
                "Relay ID": rich_text(key),
                "Shift ID": rich_text(str(DAY.id)),
                "Operator ID": rich_text(str(OUTGOING.id)),
                "Asset ID": rich_text(str(PUMP.id)),
                "Observed": {"date": {"start": at(13, 35).isoformat()}},
                "Report": rich_text(report),
                "Action": rich_text(action),
                "Action Owner": rich_text(
                    str(OUTGOING.id) if key == "synthetic-pump-field" else ""
                ),
                "Synthetic": {"checkbox": True},
            },
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("provision", "seed"))
    args = parser.parse_args()
    client = NotionClient(os.environ["NOTION_TOKEN"])
    try:
        if args.command == "provision":
            provision(client, UUID(os.environ["NOTION_PARENT_PAGE_ID"]))
        else:
            seed(SQLiteStore(database_path()))
            seed_remote(client, Sources.from_environment())
            print(json.dumps(wearable_context()))
    finally:
        client.close()


if __name__ == "__main__":
    main()
