#!/usr/bin/env python3
"""Search Financial Advisory Board packet minutes for recorded motions."""

from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import sys
from typing import Iterable

from fab_motions import (
    MotionRecord,
    deduplicate_motion_records,
    filter_motion_records,
    scan_fab_archive,
    scan_minutes_packet,
)
from project_paths import ORIGINALS_DIR


DEFAULT_FAB_ORIGINALS_DIR = ORIGINALS_DIR / "financial-advisory-board"


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Search canonical FAB minutes for recorded motion outcomes.",
    )
    parser.add_argument(
        "--packet",
        type=Path,
        action="append",
        default=[],
        help="Agenda packet PDF to scan; repeat to scan selected files instead of the archive",
    )
    parser.add_argument(
        "--originals-dir",
        type=Path,
        default=DEFAULT_FAB_ORIGINALS_DIR,
        help="Canonical Financial Advisory Board source root",
    )
    parser.add_argument(
        "--from",
        dest="start",
        type=_date_arg,
        help="First held meeting date to include, as YYYY-MM-DD",
    )
    parser.add_argument(
        "--through",
        type=_date_arg,
        help="Last held meeting date to include, as YYYY-MM-DD",
    )
    parser.add_argument(
        "--successful-only",
        action="store_true",
        help="Keep explicit passes and affirmative recorded votes only",
    )
    parser.add_argument(
        "--exclude-routine",
        action="store_true",
        help="Exclude minutes approvals, appointments, elections, and adjournments",
    )
    parser.add_argument(
        "--exclude-procedural",
        action="store_true",
        help="Exclude deferrals, tabling actions, and meeting-calendar actions",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json", "markdown"),
        default="text",
        help="Output format",
    )
    parser.add_argument("--out", type=Path, help="Write output to this path instead of stdout")
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Iterable[str] | None = None) -> None:
    args = parse_args(argv)
    try:
        records = _records_for_args(args)
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1) from exc

    output = _render_records(records, args.format)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(output, encoding="utf-8")
    else:
        print(output, end="")


def _records_for_args(args: argparse.Namespace) -> list[MotionRecord]:
    if not args.packet:
        return scan_fab_archive(
            args.originals_dir,
            start=args.start,
            through=args.through,
            successful_only=args.successful_only,
            exclude_routine=args.exclude_routine,
            exclude_procedural=args.exclude_procedural,
        )

    records = [
        record
        for packet_path in args.packet
        for record in scan_minutes_packet(packet_path)
    ]
    records = deduplicate_motion_records(records)
    return filter_motion_records(
        records,
        start=args.start,
        through=args.through,
        successful_only=args.successful_only,
        exclude_routine=args.exclude_routine,
        exclude_procedural=args.exclude_procedural,
    )


def _render_records(records: list[MotionRecord], output_format: str) -> str:
    if output_format == "json":
        return json.dumps([record.as_dict() for record in records], indent=2, ensure_ascii=False) + "\n"
    if output_format == "markdown":
        return _render_markdown_records(records)
    if not records:
        return "No recorded motion outcomes found.\n"
    return "\n\n".join(_format_record(record) for record in records) + "\n"


def _render_markdown_records(records: list[MotionRecord]) -> str:
    if not records:
        return "No recorded motion outcomes found.\n"
    return "\n".join(_format_markdown_record(record) for record in records) + "\n"


def _format_markdown_record(record: MotionRecord) -> str:
    held_date = record.held_date.isoformat() if record.held_date else "Held date unavailable"
    action = record.recommendation_text or record.supporting_text or record.full_motion_text
    action = " ".join(action.split())
    source = _markdown_source(record)
    return f"- **{held_date}** — {action} {source}"


def _markdown_source(record: MotionRecord) -> str:
    page = _page_label(record)
    if record.source.source_url:
        url = record.source.source_url.replace("(", "%28").replace(")", "%29")
        return f"[Minutes packet, {page}]({url})."
    return f"Minutes packet: `{record.source.path}`, {page}."


def _format_record(record: MotionRecord) -> str:
    held_date = record.held_date.isoformat() if record.held_date else "held date unavailable"
    page = _page_label(record)
    source = f"{record.source.path.name}, {page}"
    if record.source.file_id is not None:
        source += f", CivicClerk file {record.source.file_id}"
    lines = [f"{held_date} | {record.outcome.value}", f"Source: {source}"]
    if record.agenda_item:
        lines.append(f"Agenda item: {record.agenda_item}")
    if record.recommendation_text:
        lines.append(f"Recommendation: {record.recommendation_text}")
    lines.append(f"Motion: {record.full_motion_text}")
    if record.vote_text:
        lines.append(f"Vote: {record.vote_text}")
    if record.result_text and record.result_text != record.vote_text:
        lines.append(f"Result: {record.result_text}")
    if record.supporting_text:
        lines.append(f"Supporting text: {record.supporting_text}")
    if record.date_conflicts:
        lines.extend(f"Warning: {warning}" for warning in record.date_conflicts)
    if record.procedural_reason:
        lines.append(f"Procedural classification: {record.procedural_reason}")
    return "\n".join(lines)


def _page_label(record: MotionRecord) -> str:
    if record.physical_page_start == record.physical_page_end:
        return f"p. {record.physical_page_start}"
    return f"pp. {record.physical_page_start}-{record.physical_page_end}"


def _date_arg(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid date: {value}") from exc


if __name__ == "__main__":
    main()
