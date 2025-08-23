#!/usr/bin/env python3
"""CLI for parsing El Cerrito agenda packet check registers."""

from __future__ import annotations

import argparse
from pathlib import Path

from check_register import (
    CheckRegisterParser,
    month_rollups,
    sanity,
    write_csv,
    write_json,
    write_payee_quadtree_html,
)
from check_register.page_extractor import extract_check_register_pdf, default_pdf_name


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Parse El Cerrito Agenda Packet check/EFT registers into CSV/JSON or extract pages to PDF."
    )
    ap.add_argument("pdf", type=Path, help="Agenda Packet PDF path")
    ap.add_argument("--csv", type=Path, default=None, help="Output CSV path")
    ap.add_argument("--json", type=Path, default=None, help="Optional JSON output path")
    ap.add_argument("--html", type=Path, default=None, help="Optional payee quadtree HTML path")
    ap.add_argument("--drop-voided", action="store_true", help="Exclude voided/voided-reissued rows from output")
    ap.add_argument("--print-rollups", action="store_true", help="Print per-month rollups after parsing")
    ap.add_argument(
        "--pdf", nargs="?", type=Path, const=True, dest="pdf_out", default=None,
        help=(
            "Write check register pages to a PDF; if no filename is given, "
            "a default archive name is used"
        ),
    )
    args = ap.parse_args()

    entries = None
    need_entries = (
        args.csv or args.json or args.html or args.print_rollups or args.pdf_out is True
    )
    if need_entries:
        parser = CheckRegisterParser(args.pdf, keep_voided=not args.drop_voided)
        entries = parser.extract()

    if entries is not None:
        if args.csv:
            write_csv(entries, args.csv)
        if args.json:
            write_json(entries, args.json)
        if args.html:
            write_payee_quadtree_html(entries, args.html)

        if args.csv or args.json or args.html or args.print_rollups:
            stats = sanity(entries)
            print(
                f"Rows: {stats['count']}  (checks={stats['by_type'].get('check', 0)}, "
                f"efts={stats['by_type'].get('eft', 0)})"
            )
            print(f"Total (non-void): ${stats['total_nonvoid']:.2f}")
            if args.csv:
                print(f"CSV: {args.csv}")
            if args.json:
                print(f"JSON: {args.json}")
            if args.html:
                print(f"HTML: {args.html}")
            if args.print_rollups:
                roll = month_rollups(entries)
                if not roll:
                    print("No month rollups to display.")
                else:
                    print("\nPer-month rollups (non-void totals):")
                    for (m, y), sums in sorted(roll.items(), key=lambda kv: (kv[0][1], kv[0][0])):
                        print(
                            f"  {m:02d}/{y}: checks=${sums['checks']:.2f}  "
                            f"efts=${sums['efts']:.2f}  grand=${sums['grand']:.2f}"
                        )

    if args.pdf_out:
        out_path = default_pdf_name(entries) if args.pdf_out is True else args.pdf_out
        start, end = extract_check_register_pdf(args.pdf, out_path)
        print(f"PDF: {out_path} (pages {start}-{end})")


if __name__ == "__main__":
    main()
