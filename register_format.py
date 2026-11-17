"""Shared payment-register row and amount syntax."""

import re
from typing import Optional, Tuple


DATE_PATTERN = r"\d{2}/\d{2}/\d{4}"
ROW_START_RE = re.compile(rf"^\s*(\d{{3,7}})\s+({DATE_PATTERN})\s*(.+)$")
SOURCE_RE = re.compile(r"\b(?:Accounts Payable|Miscellaneous Billing(?: Refund)?)\b")
AMOUNT_RE = re.compile(r"\$?-?\d[\d,]*(?:\.\d{2}|\d{2})$")
_DATED_STATUS = re.compile(
    rf"^((?:Voided(?:/Reissued)?[A-Za-z /]*?|Open|Reconciled|Stopped))"
    rf"\s+{DATE_PATTERN}\s+(.*)$"
)
_STATUS_WITHOUT_SOURCE = re.compile(r"^(Open|Reconciled|Stopped|Voided(?:/Reissued)?)\s+(.*)$")
_TRAILING_DATE = re.compile(rf"\s*{DATE_PATTERN}$")


def split_row_header(line: str) -> Optional[Tuple[str, str, str, str, str]]:
    """Read payment metadata, preserving absent status/source columns as blank."""
    row = ROW_START_RE.match(line)
    if row is None:
        return None
    number, date, tail = row.groups()
    source = SOURCE_RE.search(tail)
    if source:
        status = _TRAILING_DATE.sub("", tail[:source.start()].strip())
        return number, date, status.strip(), source.group(), tail[source.end():].strip()
    status = _DATED_STATUS.match(tail) or _STATUS_WITHOUT_SOURCE.match(tail)
    if status:
        return number, date, status.group(1), "", status.group(2)
    return None
