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
    extract_check_register_pdf_range,
    default_pdf_name,
    find_check_register_page_ranges,
    register_name_prefix,
)
from check_register.payees import merge_payees, write_payees, payee_summary
from check_register.archive_audit import audit_register_archive, format_archive_audit
from check_register.originals_audit import audit_originals, format_originals_audit
from project_paths import ARTIFACT_CSV_DIR, ARTIFACT_FUND_UPDATES_DIR, ORIGINALS_DIR


@dataclass
class OutputPaths:
    csv: Path | None = None
    json: Path | None = None
    html: Path | None = None
    chunks_json: Path | None = None
    pdf: Path | None = None
    payees_txt: Path | None = None


@dataclass
class ParsedSection:
    page_range: tuple[int, int]
    chunks: list
    entries: list


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Parse El Cerrito Agenda Packet check/EFT registers into CSV/JSON or extract pages to PDF.",
    )
    ap.add_argument("pdf", nargs="?", type=Path, help="Agenda Packet PDF path")
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
    audit_group = ap.add_mutually_exclusive_group()
    audit_group.add_argument(
        "--audit-archive",
        action="store_true",
        help="Scan generated CSV artifacts and report missing check register months",
    )
    audit_group.add_argument(
        "--audit-originals",
        action="store_true",
        help="Verify the category-first agenda source archive",
    )
    ap.add_argument(
        "--archive-csv-dir",
        type=Path,
        default=ARTIFACT_CSV_DIR,
        help="CSV artifact directory for --audit-archive",
    )
    ap.add_argument(
        "--archive-fund-update-dir",
        type=Path,
        default=ARTIFACT_FUND_UPDATES_DIR,
        help="Fund update artifact directory for --audit-archive",
    )
    ap.add_argument(
        "--originals-dir",
        type=Path,
        default=ORIGINALS_DIR,
        help="Source originals directory for --audit-originals",
    )
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


def derive_output_path_sets(
    args: argparse.Namespace, entry_groups: list[list],
) -> list[OutputPaths]:
    if len(entry_groups) <= 1:
        return [derive_output_paths(args, entry_groups[0] if entry_groups else [])]

    explicit_paths = (
        args.csv, args.json, args.html, args.chunks_json, args.pdf_out, args.payees,
    )
    if any(opt not in (None, True) for opt in explicit_paths):
        print(
            "Packet contains multiple disjoint check register sections; "
            "explicit output paths are not supported",
        )
        raise SystemExit(1)

    prefixes = [register_name_prefix(entries) for entries in entry_groups]
    if len(prefixes) != len(set(prefixes)):
        print(
            "Packet contains multiple disjoint check register sections with "
            "overlapping default output names",
        )
        raise SystemExit(1)

    return [derive_output_paths(args, entries) for entries in entry_groups]


def parse_sections(
    pdf_path: Path, *, keep_voided: bool,
) -> list[ParsedSection]:
    parser = CheckRegisterParser(pdf_path, keep_voided=keep_voided)
    sections: list[ParsedSection] = []
    for page_range in find_check_register_page_ranges(pdf_path):
        chunks = parser.extract_raw_chunks(page_range=page_range)
        entries = parser.parse_chunks(chunks)
        sections.append(ParsedSection(page_range=page_range, chunks=chunks, entries=entries))
    return sections


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

    if args.audit_archive:
        audit = audit_register_archive(args.archive_csv_dir, args.archive_fund_update_dir)
        for line in format_archive_audit(audit):
            print(line)
        if audit.missing_months or audit.missing_quarters or audit.problems:
            sys.exit(1)
        return

    if args.audit_originals:
        audit = audit_originals(args.originals_dir)
        for line in format_originals_audit(audit):
            print(line)
        if audit.problems:
            sys.exit(1)
        return

    if args.pdf is None:
        print("PDF path required unless an archive audit is used")
        sys.exit(2)

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

    sections: list[ParsedSection] = []
    if need_entries or need_chunks:
        try:
            sections = parse_sections(args.pdf, keep_voided=not args.drop_voided)
        except FileNotFoundError as exc:
            print(exc)
            sys.exit(1)
        except ValueError:
            sections = []

    path_sets = derive_output_path_sets(
        args, [section.entries for section in sections],
    )

    for idx, (section, paths) in enumerate(zip(sections, path_sets)):
        if len(sections) > 1:
            if idx:
                print()
            print(f"Section: {register_name_prefix(section.entries)}")

        if section.entries:
            write_outputs(section.entries, paths, args.drop)
            if paths.csv or paths.json or paths.html or args.print_rollups or args.totals:
                print_stats(
                    section.entries, paths, rollups=args.print_rollups, totals=args.totals,
                )
        if paths.payees_txt:
            payees, info = merge_payees(section.entries, paths.payees_txt)
            write_payees(payees, paths.payees_txt)
            lines = payee_summary(
                section.entries, paths.payees_txt, info, default=args.payees is True,
            )
            for line in lines:
                print(line)

        if need_chunks and paths.chunks_json:
            write_chunks(section.chunks, paths.chunks_json)

        if paths.pdf:
            start, end = extract_check_register_pdf_range(
                args.pdf, paths.pdf, *section.page_range,
            )
            print(f"PDF: {paths.pdf} (pages {start}-{end})")


if __name__ == "__main__":
    main()
