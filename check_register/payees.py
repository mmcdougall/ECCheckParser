from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Set, Tuple

from .models import CheckEntry
from .stats import payee_totals, sanity


def merge_payees(
    entries: List[CheckEntry], path: Path
) -> Tuple[List[str], Dict[str, object]]:
    """Return merged payee list and summary info."""
    existing: Set[str] = set()
    if path.exists():
        existing = {
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        }
    current = {e.payee for e in entries}
    merged = sorted(existing | current)
    new_all = sorted(current - existing)
    info = {
        "total_payees": len(merged),
        "new_payees": new_all,
    }
    return merged, info


def write_payees(payees: List[str], path: Path) -> None:
    """Write payees to path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(payees) + ("\n" if payees else ""), encoding="utf-8"
    )


def payee_summary(
    entries: List[CheckEntry],
    path: Path,
    info: Dict[str, object],
    *,
    default: bool,
    threshold: int = 10,
) -> List[str]:
    """Return summary lines for a payee update."""
    if default:
        return [f"Payees: {info['total_payees']} (written to {path})"]

    cnt = len(info["new_payees"])
    if cnt == 0:
        return [f"No new payees (total {info['total_payees']})"]

    lines = [
        f"Added {cnt} new payees to {path} (total {info['total_payees']})"
    ]
    if cnt < threshold:
        totals = payee_totals(entries)
        total_nonvoid = sanity(entries)["total_nonvoid"]
        for payee in info["new_payees"]:
            amt = totals.get(payee, Decimal("0"))
            pct = (amt / total_nonvoid * 100) if total_nonvoid else 0
            lines.append(f"  {payee} ({pct:.2f}%)")
    return lines
