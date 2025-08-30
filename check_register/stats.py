from __future__ import annotations

from decimal import Decimal
from datetime import datetime
from typing import Dict, Iterable, List, Set, Tuple

from .models import CheckEntry


def dedupe_by_number(entries: Iterable[CheckEntry]) -> List[CheckEntry]:
    """Return the first entry for each unique check number."""
    seen: Set[str] = set()
    out: List[CheckEntry] = []
    for e in entries:
        if e.number in seen:
            continue
        seen.add(e.number)
        out.append(e)
    return out


def sanity(entries: List[CheckEntry]) -> Dict[str, object]:
    """Basic stats by type, and total excluding voided rows."""
    cnt = len(entries)
    by_type = {"check": 0, "eft": 0}
    for e in entries:
        by_type[e.ap_type] = by_type.get(e.ap_type, 0) + 1
    nonvoid = [e for e in entries if not e.voided]
    total = sum(e.amount for e in dedupe_by_number(nonvoid))
    return {"count": cnt, "by_type": by_type, "total_nonvoid": total}


def month_rollups(entries: List[CheckEntry]) -> Dict[Tuple[int, int], Dict[str, Decimal]]:
    """Returns {(month, year): {"checks": Decimal, "efts": Decimal, "grand": Decimal}}
    excluding voided rows in sums."""
    out: Dict[Tuple[int, int], Dict[str, Decimal]] = {}
    for e in entries:
        key = (e.section_month, e.section_year)
        if key not in out:
            out[key] = {"checks": Decimal("0.00"), "efts": Decimal("0.00"), "grand": Decimal("0.00")}
        if not e.voided:
            if e.ap_type == "check":
                out[key]["checks"] += e.amount
            elif e.ap_type == "eft":
                out[key]["efts"] += e.amount
            out[key]["grand"] += e.amount
    return out


def month_totals(entries: List[CheckEntry]) -> Dict[Tuple[int, int], Decimal]:
    """Return non-void monthly totals, deduplicating overlapping registers by check number.

    Totals are grouped by the check's own date rather than the PDF section
    headers.  This prevents double counting when a check appears in multiple
    overlapping registers.
    """

    out: Dict[Tuple[int, int], Decimal] = {}
    nonvoid = [e for e in entries if not e.voided]
    for e in dedupe_by_number(nonvoid):
        dt = datetime.strptime(e.date, "%m/%d/%Y")
        month_key = (dt.month, dt.year)
        out[month_key] = out.get(month_key, Decimal("0.00")) + e.amount
    return out

def payee_totals(entries: List[CheckEntry]) -> Dict[str, Decimal]:
    """Return summed amounts per payee, skipping voided rows."""
    out: Dict[str, Decimal] = {}
    nonvoid = [e for e in entries if not e.voided]
    for e in dedupe_by_number(nonvoid):
        out[e.payee] = out.get(e.payee, Decimal("0.00")) + e.amount
    return out
