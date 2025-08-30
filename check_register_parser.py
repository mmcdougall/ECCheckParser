#!/usr/bin/env python3
"""CLI for parsing El Cerrito agenda packet check registers."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import sys

from check_register import (
    CheckRegisterParser,
    month_rollups,
    month_totals,
    sanity,
    write_csv,
    write_json,
    write_chunks,
)
from check_register.quadtree import write_payee_quadtree_html
from check_register.page_extractor import (
    extract_check_register_pdf,
    default_pdf_name,
    register_name_prefix,
)
from check_register.payees import payee_summary


@dataclass
class OutputPaths:
    csv: Path | None = None
    json: Path | None = None
    html: Path | None = None
    chunks_json: Path | None = None
    pdf: Path | None = None
    payees_txt: Path | None = None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Parse El Cerrito Agenda Packet check/EFT registers into CSV/JSON or extract pages to PDF.",
    )
    ap.add_argument("pdf", type=Path, help="Agenda Packet PDF path")
    ap.add_argument("--csv", nargs="?", type=Path, const=True, default=None, help="Output CSV path")
    ap.add_argument("--json", nargs="?", type=Path, const=True, default=None, help="Optional JSON output path")
    ap.add_argument("--html", nargs="?", type=Path, const=True, default=None, help="Optional payee quadtree HTML path")
    ap.add_argument("--drop", type=int, default=0, help="Drop the N largest payees from the quadtree")
    ap.add_argument("--drop-voided", action="store_true", help="Exclude voided/voided-reissued rows from output")
    ap.add_argument("--print-rollups", action="store_true", help="Print per-month rollups after parsing")
    ap.add_argument("--totals", action="store_true", help="Print total spent per month")
    ap.add_argument(
        "--chunks-json", nargs="?", type=Path, const=True, default=None, help="Output raw row chunks JSON for tests",
    )
    ap.add_argument(
        "--pdf", nargs="?", type=Path, const=True, dest="pdf_out", default=None, help="Extract check register pages to a PDF",
    )
    ap.add_argument("--payees", nargs="?", type=Path, const=True, default=None, help="Write/update payee list (optionally to PATH)")
    return ap.parse_args(argv)


def derive_output_paths(args: argparse.Namespace, entries: list) -> OutputPaths:
    prefix = register_name_prefix(entries)

    def resolve(opt: Path | bool | None, suffix: str, label: str) -> Path | None:
        if opt is True:
            if prefix is None:
                print(f"No check register entries found; {label} not created")
                raise SystemExit(1)
            return Path(f"{prefix}{suffix}")
        return opt

    csv = resolve(args.csv, ".csv", "CSV")
    json = resolve(args.json, ".json", "JSON")
    html = resolve(args.html, "-payees.html", "HTML")
    chunks_json = resolve(args.chunks_json, "-chunks.json", "chunks JSON")
    pdf = args.pdf_out
    payees_txt = resolve(args.payees, "-payees.txt", "payees list")
    if pdf is True:
        pdf = default_pdf_name(entries)
        if pdf is None:
            print("No check register entries found; PDF not created")
            raise SystemExit(1)
    return OutputPaths(csv, json, html, chunks_json, pdf, payees_txt)


def write_outputs(entries: list, paths: OutputPaths, drop: int) -> None:
    if paths.csv:
        write_csv(entries, paths.csv)
    if paths.json:
        write_json(entries, paths.json)
    if paths.html:
        write_payee_quadtree_html(entries, paths.html, drop=drop)


def print_stats(entries: list, paths: OutputPaths, *, rollups: bool, totals: bool) -> None:
    stats = sanity(entries)
    print(
        f"Rows: {stats['count']}  (checks={stats['by_type'].get('check', 0)}, "
        f"efts={stats['by_type'].get('eft', 0)})",
    )
    print(f"Total (non-void): ${stats['total_nonvoid']:,.2f}")
    if paths.csv:
        print(f"CSV: {paths.csv}")
    if paths.json:
        print(f"JSON: {paths.json}")
    if paths.html:
        print(f"HTML: {paths.html}")
    if rollups:
        roll = month_rollups(entries)
        if not roll:
            print("No month rollups to display.")
        else:
            print("\nPer-month rollups (non-void totals):")
            for (m, y), sums in sorted(roll.items(), key=lambda kv: (kv[0][1], kv[0][0])):
                print(
                    f"  {m:02d}/{y}: checks=${sums['checks']:,.2f}  "
                    f"efts=${sums['efts']:,.2f}  grand=${sums['grand']:,.2f}",
                )
    if totals:
        tot = month_totals(entries)
        if not tot:
            print("No month totals to display.")
        else:
            print("\nPer-month totals (non-void, deduped):")
            for (m, y), total in sorted(tot.items(), key=lambda kv: (kv[0][1], kv[0][0])):
                print(f"  {m:02d}/{y}: ${total:,.2f}")


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)

    need_chunks = bool(args.chunks_json)
    need_entries = (
        args.csv is not None
        or args.json is not None
        or args.html is not None
        or args.print_rollups
        or args.totals
        or args.pdf_out is not None
        or need_chunks
        or args.payees is not None
    )

    chunks = entries = None
    if need_entries or need_chunks:
        parser = CheckRegisterParser(args.pdf, keep_voided=not args.drop_voided)
        chunks = parser.extract_raw_chunks()
        if need_entries:
            entries = parser.parse_chunks(chunks)

    paths = derive_output_paths(args, entries or [])

    if entries:
        write_outputs(entries, paths, args.drop)
        if paths.csv or paths.json or paths.html or args.print_rollups or args.totals:
            print_stats(entries, paths, rollups=args.print_rollups, totals=args.totals)
    if paths.payees_txt and entries is not None:
        lines = payee_summary(entries, paths.payees_txt, default=args.payees is True)
        for line in lines:
            print(line)

    if need_chunks and chunks is not None and paths.chunks_json:
        write_chunks(chunks, paths.chunks_json)

    if paths.pdf:
        try:
            start, end = extract_check_register_pdf(args.pdf, paths.pdf)
        except ValueError as exc:
            print(f"PDF extraction failed: {exc}")
            sys.exit(1)
        print(f"PDF: {paths.pdf} (pages {start}-{end})")


if __name__ == "__main__":
    main()
