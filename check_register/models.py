from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


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
