"""Evidence structures for motions recorded in FAB minutes."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from pathlib import Path


class MotionOutcome(str, Enum):
    EXPLICIT_PASS = "explicit-pass"
    AFFIRMATIVE_RECORDED_VOTE = "affirmative-recorded-vote"
    EXPLICIT_FAILURE = "explicit-failure"
    NO_DISPOSITION = "no-disposition"
    UNRESOLVED = "unresolved"

    @property
    def is_successful(self) -> bool:
        return self in {
            MotionOutcome.EXPLICIT_PASS,
            MotionOutcome.AFFIRMATIVE_RECORDED_VOTE,
        }


@dataclass(frozen=True)
class PacketSource:
    path: Path
    packet_date: date | None = None
    file_id: int | None = None
    source_url: str | None = None
    sha256: str | None = None


@dataclass(frozen=True)
class MotionRecord:
    source: PacketSource
    held_date: date | None
    held_date_evidence: str
    physical_page_start: int
    physical_page_end: int
    agenda_item: str | None
    full_motion_text: str
    recommendation_text: str | None
    supporting_text: str | None
    vote_text: str | None
    result_text: str | None
    outcome: MotionOutcome
    ayes: int | None
    noes: int | None
    routine: bool
    procedural: bool = False
    procedural_reason: str | None = None
    date_conflicts: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_successful(self) -> bool:
        return self.outcome.is_successful

    @property
    def source_excerpt(self) -> str:
        parts = [
            self.recommendation_text,
            self.full_motion_text,
            self.vote_text,
            self.result_text,
            self.supporting_text,
        ]
        return "\n\n".join(part for part in parts if part)

    def as_dict(self) -> dict[str, object]:
        return {
            "held_date": self.held_date.isoformat() if self.held_date else None,
            "held_date_evidence": self.held_date_evidence,
            "date_conflicts": list(self.date_conflicts),
            "source_packet_date": (
                self.source.packet_date.isoformat() if self.source.packet_date else None
            ),
            "source_path": str(self.source.path),
            "source_file_id": self.source.file_id,
            "source_url": self.source.source_url,
            "source_sha256": self.source.sha256,
            "physical_page_start": self.physical_page_start,
            "physical_page_end": self.physical_page_end,
            "agenda_item": self.agenda_item,
            "full_motion_text": self.full_motion_text,
            "recommendation_text": self.recommendation_text,
            "supporting_text": self.supporting_text,
            "vote_text": self.vote_text,
            "result_text": self.result_text,
            "outcome": self.outcome.value,
            "ayes": self.ayes,
            "noes": self.noes,
            "routine": self.routine,
            "procedural": self.procedural,
            "procedural_reason": self.procedural_reason,
            "is_successful": self.is_successful,
            "source_excerpt": self.source_excerpt,
        }
