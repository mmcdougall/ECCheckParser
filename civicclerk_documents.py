#!/usr/bin/env python3
"""Discover and cache El Cerrito CivicClerk agenda documents."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
from pathlib import Path
import sys

from check_register import CheckRegisterParser
from check_register.civicclerk import (
    DEFAULT_CATEGORY,
    DEFAULT_CITY_CODE,
    DEFAULT_DOCUMENT_KINDS,
    CivicClerkApiError,
    CivicClerkDocument,
    CivicClerkMeeting,
    fetch_meeting,
    fetch_meetings,
    portal_event_url,
    published_documents,
    select_current_meeting,
    select_document,
)
from check_register.civicclerk_archive import archive_document
from check_register.page_extractor import (
    default_pdf_name,
    extract_check_register_pdf_range,
    find_check_register_page_ranges,
    register_name_prefix,
)
from project_paths import ARTIFACT_PDFS_DIR, ORIGINALS_DIR


@dataclass(frozen=True)
class RegisterScan:
    page_range: tuple[int, int]
    output_name: Path | None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="List and cache El Cerrito CivicClerk agendas and agenda packets.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List meetings and available agenda documents")
    _add_common_options(list_parser)
    _add_date_options(list_parser)

    current_parser = subparsers.add_parser(
        "current",
        help="Cache the next upcoming meeting with agenda documents, or the latest recent one",
    )
    _add_common_options(current_parser)
    current_parser.add_argument("--days-back", type=int, default=45, help="Past days to search when no upcoming document is found")
    current_parser.add_argument("--days-forward", type=int, default=45, help="Upcoming days to search")
    _add_cache_options(current_parser)

    cache_parser = subparsers.add_parser("cache", help="Cache documents for selected meetings")
    _add_common_options(cache_parser)
    _add_date_options(cache_parser)
    cache_parser.add_argument("--event", type=int, action="append", default=[], help="CivicClerk event id to cache")
    _add_cache_options(cache_parser)

    return parser.parse_args(argv)


def _add_common_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--city", default=DEFAULT_CITY_CODE, help="CivicClerk city code")
    parser.add_argument("--category", default=DEFAULT_CATEGORY, help="Meeting category filter")
    parser.add_argument("--api-timeout", type=float, default=30.0, help="CivicClerk API timeout in seconds")


def _add_date_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--year", type=int, action="append", default=[], help="Year to include; repeat for multiple years")
    parser.add_argument("--month", type=int, action="append", default=[], help="Month number to include; repeat for multiple months")
    parser.add_argument("--start", type=_date_arg, help="Start date, inclusive, as YYYY-MM-DD")
    parser.add_argument("--end", type=_date_arg, help="End date, exclusive, as YYYY-MM-DD")


def _add_cache_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--document",
        action="append",
        choices=["agenda", "agenda-packet"],
        help="Document kind to cache; repeat to override the default agenda packet only",
    )
    parser.add_argument("--originals-dir", type=Path, default=ORIGINALS_DIR, help="Local agenda packet cache root")
    parser.add_argument("--artifact-pdf-dir", type=Path, default=ARTIFACT_PDFS_DIR, help="Register PDF output directory")
    parser.add_argument("--dry-run", action="store_true", help="Print planned downloads without writing files")
    parser.add_argument("--overwrite", action="store_true", help="Replace existing cached documents or register PDFs")
    parser.add_argument("--scan-registers", action="store_true", help="Scan cached agenda packets for check register pages")
    parser.add_argument("--extract-registers", action="store_true", help="Extract found check register pages to artifact PDFs")
    parser.add_argument("--download-timeout", type=float, default=60.0, help="Document download timeout in seconds")


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    try:
        if args.command == "list":
            meetings = _meetings_for_date_args(args)
            _print_meetings(meetings)
        elif args.command == "current":
            meeting = _current_meeting(args)
            if meeting is None:
                print("No meeting with agenda documents found in the selected window.")
                return
            _cache_meetings([meeting], args)
        elif args.command == "cache":
            meetings = _meetings_for_cache_args(args)
            _cache_meetings(meetings, args)
        else:
            raise AssertionError(f"Unhandled command: {args.command}")
    except (CivicClerkApiError, OSError, ValueError) as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)


def _meetings_for_cache_args(args: argparse.Namespace) -> list[CivicClerkMeeting]:
    meetings_by_id: dict[int, CivicClerkMeeting] = {}
    for event_id in args.event:
        meeting = fetch_meeting(args.city, event_id, timeout=args.api_timeout)
        meetings_by_id[meeting.id] = meeting
    if _has_date_args(args):
        for meeting in _meetings_for_date_args(args):
            meetings_by_id[meeting.id] = meeting
    if not meetings_by_id:
        raise ValueError("Specify --event, --year, or --start/--end for cache.")
    return sorted(meetings_by_id.values(), key=lambda meeting: (meeting.event_date, meeting.id))


def _has_date_args(args: argparse.Namespace) -> bool:
    return bool(args.year or args.start or args.end)


def _meetings_for_date_args(args: argparse.Namespace) -> list[CivicClerkMeeting]:
    windows = _date_windows(args)
    meetings_by_id: dict[int, CivicClerkMeeting] = {}
    for start, end in windows:
        meetings = fetch_meetings(
            args.city,
            start=start,
            end=end,
            category=args.category,
            timeout=args.api_timeout,
        )
        for meeting in meetings:
            meetings_by_id[meeting.id] = fetch_meeting(args.city, meeting.id, timeout=args.api_timeout)
    return sorted(meetings_by_id.values(), key=lambda meeting: (meeting.event_date, meeting.id))


def _current_meeting(args: argparse.Namespace) -> CivicClerkMeeting | None:
    if args.days_back < 0 or args.days_forward < 0:
        raise ValueError("--days-back and --days-forward must be non-negative")
    today = date.today()
    meetings = fetch_meetings(
        args.city,
        start=date.fromordinal(today.toordinal() - args.days_back),
        end=date.fromordinal(today.toordinal() + args.days_forward + 1),
        category=args.category,
        timeout=args.api_timeout,
    )
    hydrated = [fetch_meeting(args.city, meeting.id, timeout=args.api_timeout) for meeting in meetings]
    return select_current_meeting(hydrated, today=today)


def _date_windows(args: argparse.Namespace) -> list[tuple[date, date]]:
    if args.start or args.end:
        if not args.start or not args.end:
            raise ValueError("--start and --end must be supplied together.")
        if args.end <= args.start:
            raise ValueError("--end must be after --start.")
        return [(args.start, args.end)]

    if not args.year:
        raise ValueError("Specify --year or --start/--end.")

    years = sorted(set(args.year))
    months = sorted(set(args.month))
    if months:
        return [_month_range(year, month) for year in years for month in months]
    return [(date(year, 1, 1), date(year + 1, 1, 1)) for year in years]


def _month_range(year: int, month: int) -> tuple[date, date]:
    if month < 1 or month > 12:
        raise ValueError(f"Month must be between 1 and 12: {month}")
    start = date(year, month, 1)
    if month == 12:
        return start, date(year + 1, 1, 1)
    return start, date(year, month + 1, 1)


def _cache_meetings(meetings: list[CivicClerkMeeting], args: argparse.Namespace) -> None:
    document_kinds = _document_kinds(args)
    if args.extract_registers:
        args.scan_registers = True

    for meeting in meetings:
        print(f"{meeting.event_date.isoformat()}  event {meeting.id}  {meeting.name}")
        print(f"Portal: {portal_event_url(args.city, meeting.id)}")
        documents = published_documents(meeting)
        if not documents:
            print("  No published files.")
            continue

        for kind in document_kinds:
            document = select_document(documents, kind)
            if document is None:
                print(f"  Missing {_document_label(kind)}")
                continue
            _cache_document(meeting, document, args)


def _cache_document(
    meeting: CivicClerkMeeting,
    document: CivicClerkDocument,
    args: argparse.Namespace,
) -> None:
    label = _document_label(document.kind)
    print(f"  {label}: {document.name}")
    archived = archive_document(
        meeting,
        document,
        originals_dir=args.originals_dir,
        dry_run=args.dry_run,
        overwrite=args.overwrite,
        timeout=args.download_timeout,
    )
    print(f"    Local: {archived.path}")
    if args.dry_run:
        print(f"    Dry run; action would be {archived.action}.")
        return
    if archived.action == "unchanged":
        print(f"    Remote metadata unchanged ({archived.bytes_written} bytes)")
    elif archived.action == "metadata-updated":
        print(f"    Existing bytes match; manifest metadata updated ({archived.bytes_written} bytes)")
    else:
        print(f"    {archived.action.title()} {archived.bytes_written} bytes")
        if archived.sha256:
            print(f"    SHA256: {archived.sha256}")
        if archived.revision_path:
            print(f"    Previous revision: {archived.revision_path}")

    if document.kind == "agenda_packet" and args.scan_registers:
        scans = scan_packet_for_registers(
            archived.path,
            artifact_pdf_dir=args.artifact_pdf_dir,
            extract=args.extract_registers,
            overwrite=args.overwrite,
        )
        if not scans:
            print("    No check register pages found.")


def scan_packet_for_registers(
    packet_path: Path,
    *,
    artifact_pdf_dir: Path = ARTIFACT_PDFS_DIR,
    extract: bool = False,
    overwrite: bool = False,
) -> list[RegisterScan]:
    parser = CheckRegisterParser(packet_path)
    scans: list[RegisterScan] = []
    try:
        page_ranges = find_check_register_page_ranges(packet_path)
    except ValueError:
        return scans

    for page_range in page_ranges:
        chunks = parser.extract_raw_chunks(page_range=page_range)
        entries = parser.parse_chunks(chunks)
        output_name = default_pdf_name(entries)
        scans.append(RegisterScan(page_range=page_range, output_name=output_name))
        prefix = register_name_prefix(entries) or "unknown-month"
        print(f"    Check register {prefix}: pages {page_range[0]}-{page_range[1]}")
        if extract:
            out_path = artifact_pdf_dir / (output_name or _fallback_register_name(packet_path, page_range))
            if out_path.exists() and not overwrite:
                print(f"    Register PDF already exists: {out_path}")
                continue
            extract_check_register_pdf_range(packet_path, out_path, *page_range)
            print(f"    Register PDF: {out_path}")
    return scans


def _fallback_register_name(packet_path: Path, page_range: tuple[int, int]) -> Path:
    return Path(f"{packet_path.stem}-pages-{page_range[0]}-{page_range[1]}-register.pdf")


def _print_meetings(meetings: list[CivicClerkMeeting]) -> None:
    if not meetings:
        print("No meetings found.")
        return
    for meeting in meetings:
        documents = published_documents(meeting)
        labels = []
        for kind in ("agenda", "agenda_packet", "minutes", "notice"):
            document = select_document(documents, kind)
            if document:
                labels.append(_document_label(document.kind))
        document_summary = ", ".join(labels) if labels else "no published files"
        print(f"{meeting.event_date.isoformat()}  event {meeting.id}  {meeting.name}  [{document_summary}]")


def _document_kinds(args: argparse.Namespace) -> tuple[str, ...]:
    if not args.document:
        return DEFAULT_DOCUMENT_KINDS
    return tuple(value.replace("-", "_") for value in args.document)


def _document_label(kind: str) -> str:
    return {
        "agenda": "Agenda",
        "agenda_packet": "Agenda Packet",
        "minutes": "Minutes",
        "notice": "Notice",
    }.get(kind, kind.replace("_", " ").title())


def _date_arg(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Expected YYYY-MM-DD: {value}") from exc


if __name__ == "__main__":
    main()
