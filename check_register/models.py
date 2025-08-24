from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import List


@dataclass
class CheckEntry:
    section_month: int           # e.g., 6 for June, 7 for July
    section_year: int            # e.g., 2025
    ap_type: str                 # "check" or "eft"
    number: str                  # keep as str to preserve leading zeros
    date: str                    # MM/DD/YYYY as text (packet uses this)
    status: str                  # Open / Voided / Voided/Reissued / etc.
    source: str                  # usually "Accounts Payable"
    payee: str
    description: str
    amount: Decimal
    voided: bool                 # True if VOID/Voided appears


@dataclass
class RowChunk:
    """Raw lines for a single check/EFT entry prior to full parsing."""

    section_month: int
    section_year: int
    ap_type: str                 # "check" or "eft"
    lines: List[str]             # original PDF text lines belonging to the row

    # TODO: Explore migrating away from line-based parsing. These positioned
    # words capture x-coordinates for each token so that future column
    # detection can rely on geometry rather than normalized spaces.
    line_words: List[List["PositionedWord"]] = field(default_factory=list)


@dataclass
class PositionedWord:
    """A single word extracted from the PDF with its starting x position."""

    text: str
    x0: float
