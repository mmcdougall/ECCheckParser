"""Document locations shared by source archivers and the originals audit."""

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class DocumentLayout:
    label: str
    canonical: str
    revisions: str


DOCUMENT_LAYOUTS = {
    "agenda": DocumentLayout("Agenda", "agendas", "agenda-revisions"),
    "agenda_packet": DocumentLayout("Agenda Packet", "agenda-packets", "agenda-packet-revisions"),
    "minutes": DocumentLayout("Minutes", "minutes", "minutes-revisions"),
    "work_plan": DocumentLayout("Work Plan", "work-plans", "work-plan-revisions"),
    "report": DocumentLayout("Report", "reports", "report-revisions"),
}


def validate_meeting_type(value: str) -> str:
    """Require a single lowercase archive folder name, such as city-council."""
    if re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", value) is None:
        raise ValueError(f"Invalid meeting type folder: {value!r}; use a lowercase hyphenated name.")
    return value
