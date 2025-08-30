from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Set

from .models import CheckEntry
from .stats import payee_totals, sanity


def update_payees(entries: List[CheckEntry], path: Path, threshold: int = 10) -> Dict[str, object]:
    """Merge payees from entries with an existing list and write the result."""
    existing: Set[str] = set()
    if path.exists():
        existing = {
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        }
    current = {e.payee for e in entries}
    merged = sorted(existing | current)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(merged) + ("\n" if merged else ""), encoding="utf-8")

    new_all = sorted(current - existing)
    listed = new_all if len(new_all) < threshold else []
    totals = payee_totals(entries)
    new_amounts: Dict[str, Decimal] = {p: totals[p] for p in listed}
    return {
        "total_payees": len(merged),
        "new_payee_count": len(new_all),
        "new_payees": listed,
        "new_payee_amounts": new_amounts,
    }


def payee_summary(
    entries: List[CheckEntry], path: Path, *, default: bool, threshold: int = 10
) -> List[str]:
    """Update payee file and return summary lines."""
    info = update_payees(entries, path, threshold)
    if default:
        return [f"Payees: {info['total_payees']} (written to {path})"]

    lines: List[str] = []
    cnt = info["new_payee_count"]
    if cnt == 0:
        lines.append(f"No new payees (total {info['total_payees']})")
        return lines

    lines.append(
        f"Added {cnt} new payees to {path} (total {info['total_payees']})"
    )
    if info["new_payees"]:
        total_nonvoid = sanity(entries)["total_nonvoid"]
        for payee in info["new_payees"]:
            amt = info["new_payee_amounts"][payee]
            pct = (amt / total_nonvoid * 100) if total_nonvoid else 0
            lines.append(f"  {payee} ({pct:.2f}%)")
    return lines
