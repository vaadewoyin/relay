from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, HttpUrl

from relay.notion.client import JSON
from relay.service import NewAction, ReportIntake


class Page(BaseModel):
    id: UUID
    url: HttpUrl
    last_edited_time: str
    properties: dict[str, dict]


def rich_text(text: str, kind: str = "rich_text") -> JSON:
    return {
        kind: [
            {"type": "text", "text": {"content": text[offset : offset + 1800]}}
            for offset in range(0, len(text), 1800)
        ]
    }


def property_text(page: Page, name: str, kind: str = "rich_text") -> str:
    property_value = page.properties[name]
    if property_value.get("type") != kind:
        raise ValueError("Unexpected Notion property type.")
    return "".join(item["plain_text"] for item in property_value[kind])


def map_report(raw: JSON) -> ReportIntake:
    page = Page.model_validate(raw)
    if page.url.scheme != "https":
        raise ValueError("Report link must use HTTPS.")
    action = property_text(page, "Action")
    owner = property_text(page, "Action Owner")
    observed = page.properties["Observed"]
    synthetic = page.properties["Synthetic"]
    if observed.get("type") != "date" or synthetic.get("type") != "checkbox":
        raise ValueError("Unexpected Notion property type.")
    if owner and not action.strip():
        raise ValueError("Action owner requires an action.")
    return ReportIntake(
        operation_id=uuid5(NAMESPACE_URL, f"relay:notion:report:{page.id}"),
        source_ref=f"notion:{page.id}",
        source_url=page.url,
        source_revision=page.last_edited_time,
        shift_id=property_text(page, "Shift ID"),
        author_id=property_text(page, "Operator ID"),
        asset_id=property_text(page, "Asset ID"),
        observed_at=observed["date"]["start"],
        text=property_text(page, "Report"),
        synthetic=synthetic["checkbox"],
        actions=(NewAction(description=action, owner_id=owner or None),)
        if action.strip()
        else (),
    )
