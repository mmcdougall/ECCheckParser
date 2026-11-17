#!/usr/bin/env python3
"""Discover and cache El Cerrito records from selected Archive Center indexes."""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
import sys

from check_register.archivecenter import ArchiveCenterDocument, ArchiveCenterError, fetch_documents
from check_register.archivecenter_archive import archive_document
from check_register.civicclerk import FINANCIAL_ADVISORY_BOARD_MEETING_TYPE
from check_register.originals_layout import DOCUMENT_LAYOUTS, validate_meeting_type
from project_paths import ORIGINALS_DIR


LEGACY_FAB_INDEXES = {"agenda": 62, "agenda_packet": 93}


@dataclass(frozen=True)
class CachePlan:
    documents: list[ArchiveCenterDocument]
    skipped: list[str]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="List and cache El Cerrito records from the City Archive Center.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List records from selected Archive Center indexes")
    _add_date_options(list_parser)
    _add_network_options(list_parser)
    _add_archive_options(list_parser)

    cache_parser = subparsers.add_parser("cache", help="Cache unambiguous dated PDFs")
    _add_date_options(cache_parser)
    _add_network_options(cache_parser)
    _add_archive_options(cache_parser)
    cache_parser.add_argument(
        "--document",
        action="append",
        choices=[kind.replace("_", "-") for kind in DOCUMENT_LAYOUTS],
        help="Document kind to cache; defaults to all selected index kinds",
    )
    cache_parser.add_argument(
        "--require-matching-agenda",
        action="store_true",
        help="Cache packets only with one same-date agenda; automatic for the legacy FAB indexes",
    )
    cache_parser.add_argument(
        "--include-variants",
        action="store_true",
        help="Preserve differing Archive Center copies as revisions beside CivicClerk canonicals",
    )
    cache_parser.add_argument("--originals-dir", type=Path, default=ORIGINALS_DIR, help="Local originals archive root")
    cache_parser.add_argument("--dry-run", action="store_true", help="Print planned cache actions without writing files")

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    try:
        if args.command == "cache" and not _has_date_selection(args):
            raise ValueError("Specify --date, --year, or --start/--end for cache.")
        indexes = _selected_indexes(args)
        _selected_dates_and_windows(args)
        documents = _selected_documents(fetch_documents(indexes, timeout=args.index_timeout), args)
        if args.command == "list":
            _print_documents(documents)
        elif args.command == "cache":
            _cache_documents(documents, args)
        else:
            raise AssertionError(f"Unhandled command: {args.command}")
    except (ArchiveCenterError, OSError, ValueError) as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)


def _add_date_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--date", type=_date_arg, action="append", default=[], help="Listing date as YYYY-MM-DD; repeat for multiple dates")
    parser.add_argument("--year", type=int, action="append", default=[], help="Year to include; repeat for multiple years")
    parser.add_argument("--month", type=int, action="append", default=[], help="Month number to include; repeat for multiple months")
    parser.add_argument("--start", type=_date_arg, help="Start date, inclusive, as YYYY-MM-DD")
    parser.add_argument("--end", type=_date_arg, help="End date, exclusive, as YYYY-MM-DD")


def _add_network_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--index-timeout", type=float, default=30.0, help="Archive Center index request timeout in seconds")
    parser.add_argument("--download-timeout", type=float, default=60.0, help="Document download timeout in seconds")


def _add_archive_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--index", type=_index_arg, action="append", default=[], metavar="KIND=AMID",
        help="Map a document kind to an Archive Center index ID; repeat for multiple kinds. Defaults to legacy FAB indexes.",
    )
    parser.add_argument(
        "--meeting-type", type=validate_meeting_type,
        help="Originals folder, such as subdivision-committee; required to cache custom indexes",
    )


def _index_arg(value: str) -> tuple[str, int]:
    kind, separator, archive_id = value.partition("=")
    kind = kind.replace("-", "_")
    if not separator or kind not in DOCUMENT_LAYOUTS or not archive_id.isdigit() or int(archive_id) <= 0:
        raise argparse.ArgumentTypeError(
            "Expected KIND=AMID with a positive index ID; kinds: "
            + ", ".join(kind.replace("_", "-") for kind in DOCUMENT_LAYOUTS),
        )
    return kind, int(archive_id)


def _selected_indexes(args: argparse.Namespace) -> dict[str, int]:
    if not args.index:
        if args.meeting_type not in (None, FINANCIAL_ADVISORY_BOARD_MEETING_TYPE):
            raise ValueError("Specify --index KIND=AMID for the selected meeting type.")
        indexes = LEGACY_FAB_INDEXES.copy()
    else:
        if args.command == "cache" and args.meeting_type is None:
            raise ValueError("Specify --meeting-type when caching custom indexes.")
        indexes = dict(args.index)
        if len(indexes) != len(args.index):
            raise ValueError("Specify only one --index per document kind.")
    if args.command == "cache" and not set(_document_kinds(args)).issubset(indexes):
        raise ValueError("Each --document kind must have a selected --index.")
    return indexes


def _selected_documents(
    documents: list[ArchiveCenterDocument],
    args: argparse.Namespace,
) -> list[ArchiveCenterDocument]:
    dates, windows = _selected_dates_and_windows(args)
    if not dates and not windows:
        return documents
    return [
        document
        for document in documents
        if document.listing_date in dates or _date_in_windows(document.listing_date, windows)
    ]


def _selected_dates_and_windows(args: argparse.Namespace) -> tuple[set[date], list[tuple[date, date]]]:
    if (args.start is None) != (args.end is None):
        raise ValueError("--start and --end must be supplied together.")
    if args.start and args.end and args.end <= args.start:
        raise ValueError("--end must be after --start.")

    windows: list[tuple[date, date]] = []
    if args.start and args.end:
        windows.append((args.start, args.end))
    years = sorted(set(args.year))
    months = sorted(set(args.month))
    if months and not years:
        raise ValueError("--month requires --year.")
    if months:
        windows.extend(_month_range(year, month) for year in years for month in months)
    elif years:
        windows.extend((date(year, 1, 1), date(year + 1, 1, 1)) for year in years)
    return set(args.date), windows


def _has_date_selection(args: argparse.Namespace) -> bool:
    return bool(args.date or args.year or args.start or args.end)


def _cache_documents(documents: list[ArchiveCenterDocument], args: argparse.Namespace) -> None:
    plan = cache_plan(
        documents, document_kinds=_document_kinds(args),
        require_matching_agenda=not args.index or args.require_matching_agenda,
    )
    for message in plan.skipped:
        print(f"Skipped: {message}")
    if not plan.documents:
        print("No unambiguous Archive Center documents selected for caching.")
        return

    for document in plan.documents:
        print(
            f"{document.listing_date.isoformat()}  item {document.archive_id}  "
            f"{_document_label(document.kind)}: {document.listing_title}",
        )
        archived = archive_document(
            document,
            originals_dir=args.originals_dir,
            meeting_type=args.meeting_type or FINANCIAL_ADVISORY_BOARD_MEETING_TYPE,
            dry_run=args.dry_run,
            include_variants=args.include_variants,
            timeout=args.download_timeout,
        )
        print(f"  Local: {archived.path}")
        if args.dry_run:
            print(f"  Dry run; action would be {archived.action}.")
        elif archived.action == "skipped-existing":
            print("  Existing canonical source retained; use --include-variants to retain a differing copy.")
        elif archived.action == "unchanged":
            print(f"  Archive Center identity unchanged ({archived.bytes_written} bytes)")
        elif archived.action == "identical-to-current":
            print(f"  Identical to the canonical source ({archived.bytes_written} bytes)")
        else:
            print(f"  {archived.action.replace('-', ' ').title()} {archived.bytes_written} bytes")
            if archived.sha256:
                print(f"  SHA256: {archived.sha256}")
            if archived.revision_path:
                print(f"  Previous revision: {archived.revision_path}")


def cache_plan(
    documents: list[ArchiveCenterDocument],
    *,
    document_kinds: tuple[str, ...],
    require_matching_agenda: bool = False,
) -> CachePlan:
    by_date: dict[date, dict[str, list[ArchiveCenterDocument]]] = defaultdict(
        lambda: defaultdict(list),
    )
    skipped: list[str] = []
    for document in documents:
        if document.listing_date is None:
            skipped.append(f"item {document.archive_id} has no parseable listing date")
            continue
        if not document.is_pdf:
            skipped.append(
                f"{document.listing_date.isoformat()} item {document.archive_id} is {document.document_format or 'an unknown format'}, not PDF",
            )
            continue
        by_date[document.listing_date][document.kind].append(document)

    selected: list[ArchiveCenterDocument] = []
    for meeting_date in sorted(by_date):
        for kind in document_kinds:
            candidates = by_date[meeting_date][kind]
            if len(candidates) > 1:
                skipped.append(f"{meeting_date.isoformat()} has ambiguous {kind} listings ({len(candidates)})")
            elif len(candidates) == 1:
                if kind == "agenda_packet" and require_matching_agenda and len(by_date[meeting_date]["agenda"]) != 1:
                    skipped.append(
                        f"{meeting_date.isoformat()} packet item {candidates[0].archive_id} has no matching indexed agenda",
                    )
                    continue
                selected.append(candidates[0])
    return CachePlan(selected, skipped)


def _print_documents(documents: list[ArchiveCenterDocument]) -> None:
    if not documents:
        print("No Archive Center documents found.")
        return
    for document in documents:
        meeting_date = document.listing_date.isoformat() if document.listing_date else "unparsed-date"
        format_label = document.document_format or "unknown"
        print(
            f"{meeting_date}  item {document.archive_id}  "
            f"{_document_label(document.kind)} [{format_label}]  {document.listing_title}",
        )


def _document_kinds(args: argparse.Namespace) -> tuple[str, ...]:
    if not args.document:
        return tuple(dict(args.index)) if args.index else tuple(LEGACY_FAB_INDEXES)
    return tuple(value.replace("-", "_") for value in args.document)


def _document_label(kind: str) -> str:
    return DOCUMENT_LAYOUTS[kind].label


def _date_in_windows(value: date | None, windows: list[tuple[date, date]]) -> bool:
    return value is not None and any(start <= value < end for start, end in windows)


def _month_range(year: int, month: int) -> tuple[date, date]:
    if month < 1 or month > 12:
        raise ValueError(f"Month must be between 1 and 12: {month}")
    start = date(year, month, 1)
    if month == 12:
        return start, date(year + 1, 1, 1)
    return start, date(year, month + 1, 1)


def _date_arg(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Expected YYYY-MM-DD: {value}") from exc


if __name__ == "__main__":
    main()
