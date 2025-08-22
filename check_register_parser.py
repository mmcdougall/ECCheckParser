#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_register_parser.py

Extracts "Monthly Disbursement and Check Register" entries from City of El Cerrito
Agenda Packet PDFs and writes a CSV.

Key features
- Robust header detection even when "City of El Cerrito / Payment Register" is split across lines.
- Parses both Accounts Payable Checks and EFTs subsections.
- Handles wrapped descriptions and amounts that land on the next line.
- Flags VOID / Voided / Voided/Reissued rows and excludes them from subtotal by default.
- Emits CSV with explicit schema, plus prints basic sanity totals.

Usage:
    python check_register_parser.py "Agenda Packet (8.19.2025).pdf" --csv out.csv

Dependencies:
    pip install pdfplumber
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import logging
from dataclasses import dataclass, asdict
from decimal import Decimal
from pathlib import Path
from typing import List, Optional, Tuple, Dict

import pdfplumber


# ------------------------------
# Data model
# ------------------------------
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


# ------------------------------
# Parser
# ------------------------------
class CheckRegisterParser:
    # Match the single line that contains both From/To dates.
    # Example: "From Payment Date: 6/1/2025 - To Payment Date: 6/30/2025"
    _block_hdr = re.compile(
        r"^From Payment Date:\s*(\d{1,2})/(\d{1,2})/(\d{4})\s*-\s*To Payment Date:\s*(\d{1,2})/(\d{1,2})/(\d{4})$",
        re.IGNORECASE
    )

    # Subsection headings can vary slightly in punctuation/spacing
    _checks_hdr = re.compile(r"^Accounts Payable\s*-?\s*Checks$", re.IGNORECASE)
    _efts_hdr   = re.compile(r"^Accounts Payable\s*-?\s*EFT'?s$", re.IGNORECASE)

    # Typical data row start pattern:
    # "<num> <MM/DD/YYYY> <Status> Accounts Payable <tail>"
    # Example:
    # "93336 06/12/2025 Open Accounts Payable Dixon Resources Unlimited ... $6,847.50"
    _row_start = re.compile(
        r"^\s*(\d{3,7})\s+(\d{2}/\d{2}/\d{4})\s+([A-Za-z /]+?)\s+(Accounts Payable)\s+(.*)$"
    )

    # Lines containing a VOID marker anywhere
    _void_marker = re.compile(r"\bVOID(?:ED|ED/REISSUED)?\b", re.IGNORECASE)

    # Amount is last token (with optional minus) like $12,345.67
    _amount_tail = re.compile(r"\$-?\d{1,3}(?:,\d{3})*(?:\.\d{2})?$")

    # Obvious non-data lines to skip
    _skip_line = re.compile(
        r"^(?:TOTAL CHECKS|TOTAL EFT|TOTAL EFT'S|TOTAL EFT’S|Checks & EFT'?s|All Status|GRAND TOTAL|"
        r"ACCOUNTS PAYABLE|PAYROLL|City of El Cerrito|Payment Register|Open\s+\d+|Voided|Total\s+\d+)$",
        re.IGNORECASE
    )

    def __init__(self, pdf_path: Path, keep_voided: bool = True):
        self.pdf_path = Path(pdf_path)
        self.keep_voided = keep_voided

    # ---------- helpers ----------
    @staticmethod
    def _money_to_decimal(s: str) -> Decimal:
        s = s.strip().replace("$", "").replace(",", "")
        if s == "":
            return Decimal("0.00")
        return Decimal(s)

    @staticmethod
    def _split_payee_desc_block(block: str) -> Tuple[str, str]:
        """Split a block containing payee and description using weighted votes.

        Each heuristic returns a token boundary index and is assigned a weight.
        Boundaries accumulate votes and the highest scoring split wins.  Some
        heuristics may abstain by returning ``None``.
        """
        block = block.replace("\r", " ").replace("\n", " ").strip()
        block = re.sub(r",(?=[A-Za-z])", ", ", block)
        if not block:
            return "", ""

        STOPWORDS = {
            "MERCHANT", "OFFICE", "SUPPLIES", "SERVICE", "EXPENSE",
            "FEE", "FEES", "PAYMENT", "RE", "RE:", "TOTAL",
            "REIMBURSEMENT", "PERFORMANCE", "CONTRACT", "RENTAL",
            "PROGRAM", "TRAINING", "PER", "DIEM", "INVOICE", "PROFESSIONAL",
        }

        KNOWN_PREFIXES = [
            "ALAMEDA COUNTY FIRE DEPARTMENT",
            "BAY AREA NEWS GROUP",
            "DIEGO TRUCK REPAIR",
            "L.N. CURTIS & SONS",
            "J & O'S COMMERCIAL TIRE CENTER",
            "MUNICIPAL POOLING AUTHORITY",
            "KAISER FOUNDATION HEALTH PLAN",
            "EAST BAY REGIONAL COMMUNICATIONS SYSTEM",
            "CONTRA COSTA HEALTH SERVICES",
            "GHIRARDELLI ASSOCIATES",
            "FLOCK SAFETY",
            "PERS",
        ]

        SUFFIXES = {
            "LLP",
            "LLC",
            "INC",
            "CORP",
            "CORPORATION",
            "CO",
            "COMPANY",
            "LTD",
            "ASSOCIATES",
        }
        MONTHS = {
            "JAN", "JANUARY", "FEB", "FEBRUARY", "MAR", "MARCH", "APR",
            "APRIL", "MAY", "JUN", "JUNE", "JUL", "JULY", "AUG",
            "AUGUST", "SEP", "SEPT", "SEPTEMBER", "OCT", "OCTOBER",
            "NOV", "NOVEMBER", "DEC", "DECEMBER",
        }
        PREFIX_SET = {p.upper() for p in KNOWN_PREFIXES}

        tokens = block.split()
        if not tokens:
            return "", ""

        i = 0
        letters: List[str] = []
        while i < len(tokens):
            tok = tokens[i]
            stripped = tok.rstrip(".,")
            if len(stripped) == 1 and stripped.isalpha():
                letters.append(stripped.upper())
                i += 1
            else:
                break
        if len(letters) > 1:
            joined = "".join(letters)
            if joined in PREFIX_SET:
                tokens = [joined] + tokens[i:]

        if len(tokens) == 1:
            return tokens[0], ""

        # Helper to accumulate weighted votes for boundaries between tokens.
        scores = [0] * (len(tokens))  # index == boundary after tokens[i-1]

        def vote(idx: int, weight: int) -> None:
            if 1 <= idx < len(tokens):
                scores[idx] += weight

        # ----- heuristics (left-to-right unless noted) -----
        def h_known_prefix(toks: List[str], text: str) -> Optional[int]:
            """Known multi-word vendors (LTR)."""
            upper_toks = [t.upper().rstrip(".,") for t in toks]
            for prefix in KNOWN_PREFIXES:
                parts = prefix.split()
                if upper_toks[:len(parts)] == parts:
                    return len(parts)
            return None

        def h_fd_number(toks: List[str], text: str) -> Optional[int]:
            """Split before tokens like 'FD 32' (LTR)."""
            for i in range(len(toks) - 1):
                if toks[i].upper() == "FD" and toks[i + 1].isdigit():
                    return i
            return None

        def h_middle_initial(toks: List[str], text: str) -> Optional[int]:
            """Handle person names with an optional middle initial (LTR)."""
            if len(toks) >= 3:
                first, middle, last = toks[0], toks[1], toks[2]
                if (
                    re.fullmatch(r"[A-Za-z]+", first.rstrip(".,"))
                    and re.fullmatch(r"[A-Za-z]\.?", middle.rstrip(","))
                    and re.fullmatch(r"[A-Za-z]+", last.rstrip(".,"))
                ):
                    return 3
            return None

        def h_year(toks: List[str], text: str) -> Optional[int]:
            """Split before a 4-digit year (LTR)."""
            for i in range(1, len(toks)):
                if re.fullmatch(r"\d{4}", toks[i]):
                    if any(
                        t.rstrip(".,").upper() in SUFFIXES for t in toks[:i]
                    ):
                        continue
                    if i == len(toks) - 1:
                        continue
                    return i
            return None

        def h_stopword(toks: List[str], text: str) -> Optional[int]:
            """First stopword marks description start (LTR)."""
            for i in range(1, len(toks)):
                tok = toks[i]
                if tok.strip(",").upper() in STOPWORDS:
                    if tok.endswith(","):
                        continue
                    if i + 1 < len(toks) and toks[i + 1].rstrip(".,").upper() in SUFFIXES:
                        continue
                    return i
            return None

        def h_date_or_month(toks: List[str], text: str) -> Optional[int]:
            """Dates or month names anchor the description (LTR)."""
            for i in range(1, len(toks)):
                tok = toks[i].rstrip(",.")
                if re.fullmatch(r"\d{1,2}/\d{1,2}/\d{2,4}", tok):
                    return i
                up = tok.upper()
                if up in MONTHS:
                    return i
            return None

        def h_alphanum(toks: List[str], text: str) -> Optional[int]:
            """Token containing both letters and digits marks description (LTR)."""
            for i in range(1, len(toks)):
                tok = toks[i].rstrip(",.")
                if tok.startswith("#"):
                    continue
                if re.search(r"[A-Za-z]", tok) and re.search(r"\d", tok):
                    return i
            return None

        def h_column_alignment(toks: List[str], text: str) -> Optional[int]:
            """Approximate fixed column break around 45 chars (LTR)."""
            pos = 0
            for i, tok in enumerate(toks):
                pos += len(tok) + 1
                if pos >= 45:
                    return i + 1
            return None

        def h_last_comma(toks: List[str], text: str) -> Optional[int]:
            """Bias toward splitting after the last comma (LTR)."""
            last = None
            for i, tok in enumerate(toks):
                if tok.endswith(','):
                    last = i + 1
            return last

        def h_city_of(toks: List[str], text: str) -> Optional[int]:
            """Handle 'City of ...' payees (LTR)."""
            if len(toks) >= 3 and toks[0].upper() == "CITY" and toks[1].upper() == "OF":
                if len(toks) >= 4 and toks[2].upper() == "SAN":
                    return 4
                return 3
            return None

        def h_double_space(toks: List[str], text: str) -> Optional[int]:
            """Detect large gaps that visually separate columns (LTR)."""
            m = re.search(r"\s{2,}", text)
            if m:
                return len(text[: m.start()].split())
            return None

        def h_suffix(toks: List[str], text: str) -> Optional[int]:
            """Company suffix from the right (RTL)."""
            for i in range(len(toks) - 1, -1, -1):
                if toks[i].rstrip(".,").upper() in SUFFIXES:
                    return i + 1
            return None

        def h_default(toks: List[str], text: str) -> Optional[int]:
            """Fallback: split after first token."""
            return 1

        heuristics = [
            ("known_prefix", 5, h_known_prefix),
            ("fd_number", 4, h_fd_number),
            ("middle_initial", 4, h_middle_initial),
            ("year", 4, h_year),
            ("date_or_month", 5, h_date_or_month),
            ("alphanum", 5, h_alphanum),
            ("stopword", 4, h_stopword),
            ("column_alignment", 4, h_column_alignment),
            ("last_comma", 2, h_last_comma),
            ("city_of", 3, h_city_of),
            ("double_space", 1, h_double_space),
            ("suffix", 5, h_suffix),
            ("default", 1, h_default),
        ]

        for _name, weight, func in heuristics:
            idx = func(tokens, block)
            if idx is not None:
                vote(idx, weight)

        best_idx = max(range(1, len(tokens)), key=lambda i: (scores[i], -i))
        suffix_pos = next(
            (i for i, tok in enumerate(tokens) if tok.rstrip(".,").upper() in SUFFIXES),
            None,
        )
        if suffix_pos is not None and best_idx > suffix_pos + 1:
            best_idx = suffix_pos + 1

        payee = " ".join(tokens[:best_idx])
        desc = " ".join(tokens[best_idx:])

        while payee.endswith(",") and desc:
            first, *rest = desc.split(" ")
            payee = f"{payee} {first}".rstrip()
            desc = " ".join(rest)
        payee = payee.strip()
        desc = desc.strip()
        if not desc and len(tokens) > 3:
            payee = " ".join(tokens[:3]).strip()
            desc = " ".join(tokens[3:]).strip()
        if re.fullmatch(r"\d{4}", desc):
            payee = f"{payee} {desc}".strip()
            desc = ""

        # Repair: if the payee captured obvious description tokens or no
        # description was found, split before the first keyword/date/month.
        payee_tokens = tokens[:best_idx]
        desc_tokens = tokens[best_idx:]
        repair_needed = not desc_tokens
        for i in range(1, len(payee_tokens)):
            tok = payee_tokens[i]
            stripped = tok.rstrip(",.")
            if stripped.upper() in STOPWORDS:
                if tok.endswith(','):
                    continue
                if i + 1 < len(payee_tokens) and payee_tokens[i + 1].rstrip(".,").upper() in SUFFIXES:
                    continue
                repair_needed = True
                break
            if (
                stripped.upper() in MONTHS
                or re.fullmatch(r"\d{1,2}/\d{1,2}/\d{2,4}", stripped)
                or (re.search(r"\d", stripped) and not stripped.startswith("#"))
            ):
                repair_needed = True
                break

        if repair_needed:
            for i in range(1, len(tokens)):
                tok = tokens[i]
                stripped = tok.rstrip(",.")
                if stripped.upper() in STOPWORDS:
                    if tok.endswith(','):
                        continue
                    if i + 1 < len(tokens) and tokens[i + 1].rstrip(".,").upper() in SUFFIXES:
                        continue
                    payee = " ".join(tokens[:i]).strip()
                    desc = " ".join(tokens[i:]).strip()
                    break
                if (
                    stripped.upper() in MONTHS
                    or re.fullmatch(r"\d{1,2}/\d{1,2}/\d{2,4}", stripped)
                    or (re.search(r"\d", stripped) and not stripped.startswith("#"))
                ):
                    payee = " ".join(tokens[:i]).strip()
                    desc = " ".join(tokens[i:]).strip()
                    break

        return payee, desc

    # ---------- main extraction ----------
    def extract(self) -> List[CheckEntry]:
        entries: List[CheckEntry] = []

        current_month: Optional[int] = None
        current_year: Optional[int] = None
        mode: Optional[str] = None  # "check" or "eft"
        current_row: Optional[CheckEntry] = None
        current_block: str = ""

        logging.getLogger("pdfminer").setLevel(logging.ERROR)
        with pdfplumber.open(self.pdf_path) as pdf:
            for page in pdf.pages:
                lines = (page.extract_text() or "").splitlines()
                for line in lines:
                    line = line.rstrip()

                    if not line or self._skip_line.match(line):
                        continue

                    # Section boundary with explicit dates
                    b = self._block_hdr.match(line)
                    if b:
                        # Use the "To Payment Date" month/year as section label
                        current_month = int(b.group(4))
                        current_year = int(b.group(6))
                        mode = "check"  # checks typically listed first; will switch when EFT header appears
                        current_row = None
                        continue

                    # Subsection switches
                    if self._checks_hdr.match(line):
                        mode = "check"
                        current_row = None
                        continue

                    if self._efts_hdr.match(line):
                        mode = "eft"
                        current_row = None
                        continue

                    # If we're not inside a recognized section, ignore lines
                    if current_month is None or current_year is None:
                        continue

                    # New data row?
                    m = self._row_start.match(line)
                    if m:
                        if current_row and current_row.amount is not None:
                            entries.append(current_row)
                            current_row = None

        
                        number, date, status, source, rest = m.groups()
                        voided = bool(self._void_marker.search(line)) or "VOID" in status.upper() or "VOIDED" in status.upper()

                        m_amt = self._amount_tail.search(rest)
                        amt = None
                        block = rest.strip()
                        if m_amt:
                            amt = self._money_to_decimal(m_amt.group())
                            block = rest[: m_amt.start()].rstrip()

                        this_mode = mode or "check"

                        payee = desc = ""
                        if amt is not None:
                            payee, desc = self._split_payee_desc_block(block)

                        current_row = CheckEntry(
                            section_month=current_month,
                            section_year=current_year,
                            ap_type=this_mode,
                            number=number.strip(),
                            date=date.strip(),
                            status=status.strip(),
                            source=source.strip(),
                            payee=payee,
                            description=desc,
                            amount=amt if amt is not None else Decimal("0.00"),
                            voided=voided,
                        )

                        if amt is not None:
                            entries.append(current_row)
                            current_row = None
                        else:
                            current_block = block
                        continue

                    if current_row is not None:
                        m_amt = self._amount_tail.search(line)
                        if m_amt:
                            lead = line[: m_amt.start()].strip()
                            if lead:
                                current_block = (current_block + " " + lead).strip()
                            current_row.amount = self._money_to_decimal(m_amt.group())
                            payee, desc = self._split_payee_desc_block(current_block)
                            current_row.payee = payee
                            current_row.description = desc
                            entries.append(current_row)
                            current_row = None
                            current_block = ""
                        else:
                            if line and not self._row_start.match(line):
                                current_block = (current_block + " " + line.strip()).strip()

            # Flush dangling row if it somehow has an amount already
            if current_row and current_row.amount is not None:
                entries.append(current_row)

        # Optionally drop voided entries from the dataset (but keep them by default)
        if not self.keep_voided:
            entries = [e for e in entries if not e.voided]

        return entries

    # ---------- output utilities ----------
    @staticmethod
    def write_csv(entries: List[CheckEntry], out_path: Path) -> None:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow([
                "section_month", "section_year", "ap_type", "number", "date",
                "status", "source", "payee", "description", "amount", "voided"
            ])
            for e in entries:
                w.writerow([
                    e.section_month, e.section_year, e.ap_type, e.number, e.date,
                    e.status, e.source, e.payee, e.description,
                    f"{e.amount:.2f}", "Y" if e.voided else "N"
                ])

    @staticmethod
    def write_json(entries: List[CheckEntry], out_path: Path) -> None:
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as f:
            json.dump(
                [
                    {
                        **asdict(e),
                        "amount": float(e.amount)  # JSON-friendly
                    } for e in entries
                ],
                f,
                ensure_ascii=False,
                indent=2
            )

    @staticmethod
    def write_payee_quadtree_html(entries: List[CheckEntry], out_path: Path) -> None:
        """Write an HTML quadtree of payees sized by total dollar amount.

        Rectangles are colored using a linear ramp so larger dollar amounts
        stand out.
        """

        from bokeh.plotting import figure, output_file, save
        from bokeh.models import ColumnDataSource, HoverTool
        from bokeh.transform import linear_cmap
        from bokeh.palettes import Viridis256

        totals: Dict[str, Decimal] = {}
        for e in entries:
            if e.voided:
                continue
            totals[e.payee] = totals.get(e.payee, Decimal("0.00")) + e.amount

        items = [(name, float(amount)) for name, amount in totals.items() if float(amount) > 0]

        def greedy_split_2(items):
            left_group, right_group, sum_left, sum_right = [], [], 0.0, 0.0
            for label, weight in sorted(items, key=lambda t: t[1], reverse=True):
                if sum_left <= sum_right:
                    left_group.append((label, weight))
                    sum_left += weight
                else:
                    right_group.append((label, weight))
                    sum_right += weight
            return left_group, right_group, sum_left, sum_right

        def greedy_split_4(items):
            left_items, right_items, sum_left, sum_right = greedy_split_2(items)
            top_left, bottom_left, sum_top_left, sum_bottom_left = (
                greedy_split_2(left_items) if left_items else ([], [], 0, 0)
            )
            top_right, bottom_right, sum_top_right, sum_bottom_right = (
                greedy_split_2(right_items) if right_items else ([], [], 0, 0)
            )
            return {
                "NW": (top_left, sum_top_left),
                "SW": (bottom_left, sum_bottom_left),
                "NE": (top_right, sum_top_right),
                "SE": (bottom_right, sum_bottom_right),
            }, (sum_left, sum_right)

        rects: List[Dict[str, float]] = []

        def draw(items, x, y, width, height):
            total = sum(value for _, value in items)
            if not items or total <= 0:
                return
            if len(items) == 1:
                label, val = items[0]
                rects.append({"label": label, "value": val, "x": x, "y": y, "w": width, "h": height})
                return
            groups, (sum_left, sum_right) = greedy_split_4(items)
            left_fraction = sum_left / total if total else 0.5
            split_x = width * left_fraction
            top_fraction_left = groups["NW"][1] / sum_left if sum_left else 0.5
            top_fraction_right = groups["NE"][1] / sum_right if sum_right else 0.5
            top_height_left = height * top_fraction_left
            bottom_height_left = height - top_height_left
            top_height_right = height * top_fraction_right
            bottom_height_right = height - top_height_right
            draw(groups["NW"][0], x, y + height - top_height_left, split_x, top_height_left)
            draw(groups["SW"][0], x, y, split_x, bottom_height_left)
            draw(
                groups["NE"][0],
                x + split_x,
                y + height - top_height_right,
                width - split_x,
                top_height_right,
            )
            draw(groups["SE"][0], x + split_x, y, width - split_x, bottom_height_right)

        draw(items, 0.0, 0.0, 1.0, 1.0)

        data = {
            "cx": [r["x"] + r["w"] / 2 for r in rects],
            "cy": [r["y"] + r["h"] / 2 for r in rects],
            "w": [r["w"] for r in rects],
            "h": [r["h"] for r in rects],
            "payee": [r["label"] for r in rects],
            "amount": [r["value"] for r in rects],
        }
        total_amount = sum(data["amount"])
        data["percent"] = [v / total_amount * 100 if total_amount else 0 for v in data["amount"]]

        source = ColumnDataSource(data)
        low = min(data["amount"]) if data["amount"] else 0
        high = max(data["amount"]) if data["amount"] else 1
        color_map = linear_cmap("amount", Viridis256, low, high)
        p = figure(width=960, height=600, x_range=(0, 1), y_range=(0, 1),
                   toolbar_location="above", tools="pan,wheel_zoom,reset,save",
                   outline_line_color=None, title=None)
        p.rect(x="cx", y="cy", width="w", height="h", source=source,
               line_color="white", line_width=1, fill_color=color_map, fill_alpha=0.9)
        hover = HoverTool(tooltips=[("Payee", "@payee"),
                                    ("Total", "@amount{$0,0}"),
                                    ("% of total", "@percent{0.0}%")])
        p.add_tools(hover)
        p.xgrid.grid_line_color = None
        p.ygrid.grid_line_color = None

        output_file(out_path, title="Payees by Dollar Amount")
        save(p)

    @staticmethod
    def sanity(entries: List[CheckEntry]) -> Dict[str, object]:
        """
        Basic stats by type, and total excluding voided rows.
        """
        cnt = len(entries)
        by_type = {"check": 0, "eft": 0}
        total = Decimal("0.00")
        for e in entries:
            by_type[e.ap_type] = by_type.get(e.ap_type, 0) + 1
            if not e.voided:
                total += e.amount
        return {"count": cnt, "by_type": by_type, "total_nonvoid": total}

    @staticmethod
    def month_rollups(entries: List[CheckEntry]) -> Dict[Tuple[int, int], Dict[str, Decimal]]:
        """
        Returns {(month, year): {"checks": Decimal, "efts": Decimal, "grand": Decimal}}
        excluding voided rows in sums.
        """
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


# ------------------------------
# CLI
# ------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description="Parse El Cerrito Agenda Packet check/EFT registers into CSV/JSON.")
    ap.add_argument("pdf", type=Path, help="Agenda Packet PDF path")
    ap.add_argument("--csv", type=Path, default=Path("checks.csv"), help="Output CSV path")
    ap.add_argument("--json", type=Path, default=None, help="Optional JSON output path")
    ap.add_argument(
        "--html", type=Path, default=None,
        help="Optional payee quadtree HTML path"
    )
    ap.add_argument("--drop-voided", action="store_true", help="Exclude voided/voided-reissued rows from output")
    ap.add_argument("--print-rollups", action="store_true", help="Print per-month rollups after parsing")
    args = ap.parse_args()

    parser = CheckRegisterParser(args.pdf, keep_voided=not args.drop_voided)
    entries = parser.extract()

    # Write outputs
    CheckRegisterParser.write_csv(entries, args.csv)
    if args.json:
        CheckRegisterParser.write_json(entries, args.json)
    if args.html:
        CheckRegisterParser.write_payee_quadtree_html(entries, args.html)

    # Stats
    stats = CheckRegisterParser.sanity(entries)
    print(f"Rows: {stats['count']}  (checks={stats['by_type'].get('check', 0)}, efts={stats['by_type'].get('eft', 0)})")
    print(f"Total (non-void): ${stats['total_nonvoid']:.2f}")
    print(f"CSV: {args.csv}")
    if args.json:
        print(f"JSON: {args.json}")
    if args.html:
        print(f"HTML: {args.html}")

    if args.print_rollups:
        roll = CheckRegisterParser.month_rollups(entries)
        if not roll:
            print("No month rollups to display.")
        else:
            print("\nPer-month rollups (non-void totals):")
            for (m, y), sums in sorted(roll.items(), key=lambda kv: (kv[0][1], kv[0][0])):
                print(f"  {m:02d}/{y}: checks=${sums['checks']:.2f}  efts=${sums['efts']:.2f}  grand=${sums['grand']:.2f}")


if __name__ == "__main__":
    main()
