#!/usr/bin/env python3
"""Move legacy flat agenda PDFs into the canonical archive layout."""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
import hashlib
from pathlib import Path
import re

import pdfplumber

from check_register.civicclerk_archive import SCHEMA_VERSION, write_manifest
from project_paths import ORIGINALS_DIR


_MEETING_DATE = re.compile(
    r"(?:MONDAY|TUESDAY|WEDNESDAY|THURSDAY|FRIDAY|SATURDAY|SUNDAY),\s+"
    r"(?P<month>[A-Z]+)\s+(?P<day>\d{1,2}),\s+(?P<year>\d{4})",
    re.IGNORECASE,
)
_PUBLISHED_DATE = re.compile(
    r"(?:rev\.?\s*)?(?P<month>\d{1,2})\.(?P<day>\d{1,2})\.(?P<year>\d{2,4})",
    re.IGNORECASE,
)
_MONTHS = {
    name: index
    for index, name in enumerate(
        [
            "JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE",
            "JULY", "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER",
        ],
        start=1,
    )
}
_MEETING_DATE_OVERRIDES = {
    "2024/Agenda Packet (rev. 3.21.2024).pdf": date(2024, 3, 19),
    "2025/Agenda Packet (rev. 5.7.2025).pdf": date(2025, 5, 6),
}
_DIRS = {
    "agenda": ("agendas", "agenda-revisions", "Agenda"),
    "agenda_packet": ("agenda-packets", "agenda-packet-revisions", "Agenda Packet"),
}


@dataclass(frozen=True)
class LegacyDocument:
    source: Path
    meeting_date: date
    kind: str
    published_date: date | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--originals-dir", type=Path, default=ORIGINALS_DIR)
    parser.add_argument("--apply", action="store_true", help="Move files and write manifests")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    documents = _legacy_documents(args.originals_dir)
    plans = _migration_plans(documents, args.originals_dir)
    for source, target, _record in plans:
        print(f"{source} -> {target}")
    if not args.apply:
        print(f"Dry run: {len(plans)} files; pass --apply to migrate.")
        return

    _validate_targets(plans, args.originals_dir)
    manifests = _apply_plans(plans, args.originals_dir)
    for year, manifest in manifests.items():
        write_manifest(args.originals_dir / str(year) / "manifest.json", manifest)
    print(f"Migrated {len(plans)} files across {len(manifests)} yearly manifests.")


def _legacy_documents(originals_dir: Path) -> list[LegacyDocument]:
    documents = []
    for source in sorted(originals_dir.glob("[0-9][0-9][0-9][0-9]/*.pdf")):
        relative = source.relative_to(originals_dir).as_posix()
        meeting_date = _MEETING_DATE_OVERRIDES.get(relative) or _pdf_meeting_date(source)
        kind = "agenda_packet" if "agenda packet" in source.name.lower() else "agenda"
        documents.append(
            LegacyDocument(source, meeting_date, kind, _filename_date(source.name)),
        )
    return documents


def _pdf_meeting_date(path: Path) -> date:
    with pdfplumber.open(path) as pdf:
        text = "\n".join((page.extract_text() or "") for page in pdf.pages[:8])
    match = _MEETING_DATE.search(text)
    if not match:
        raise ValueError(f"Could not find meeting date in {path}")
    month = _MONTHS[match.group("month").upper()]
    return date(int(match.group("year")), month, int(match.group("day")))


def _filename_date(filename: str) -> date | None:
    match = _PUBLISHED_DATE.search(filename)
    if not match:
        return None
    year_text = match.group("year")
    year = int(year_text) + (2000 if len(year_text) == 2 else 0)
    return date(year, int(match.group("month")), int(match.group("day")))


def _migration_plans(
    documents: list[LegacyDocument],
    originals_dir: Path,
) -> list[tuple[Path, Path, dict]]:
    groups = defaultdict(list)
    for document in documents:
        groups[(document.meeting_date, document.kind)].append(document)

    plans = []
    for (meeting_date, kind), versions in sorted(groups.items()):
        versions.sort(key=lambda item: (item.published_date or date.min, item.source.name))
        for index, document in enumerate(versions):
            current = index == len(versions) - 1
            target = _target_path(originals_dir, document, current=current)
            record = _record(document, target, originals_dir)
            record["current"] = current
            plans.append((document.source, target, record))
    return plans


def _target_path(
    originals_dir: Path,
    document: LegacyDocument,
    *,
    current: bool,
) -> Path:
    current_dir, revision_dir, label = _DIRS[document.kind]
    year_dir = originals_dir / str(document.meeting_date.year)
    if current:
        return year_dir / current_dir / f"{document.meeting_date.isoformat()} {label}.pdf"
    suffix = document.published_date.isoformat() if document.published_date else "undated"
    return year_dir / revision_dir / f"{document.meeting_date.isoformat()} {label} - {suffix}.pdf"


def _record(document: LegacyDocument, target: Path, originals_dir: Path) -> dict:
    return {
        "meeting_date": document.meeting_date.isoformat(),
        "kind": document.kind,
        "path": target.relative_to(target.parents[1]).as_posix(),
        "file_id": None,
        "official_name": document.source.name,
        "published_at": None,
        "published_date": document.published_date.isoformat() if document.published_date else None,
        "downloaded_at": None,
        "last_checked_at": None,
        "size": document.source.stat().st_size,
        "sha256": _sha256(document.source),
        "source_url": None,
        "migrated_from": document.source.relative_to(originals_dir).as_posix(),
    }


def _validate_targets(
    plans: list[tuple[Path, Path, dict]],
    originals_dir: Path,
) -> None:
    targets = [target for _source, target, _record in plans]
    if len(targets) != len(set(targets)):
        raise ValueError("Migration contains colliding target paths")
    for target in targets:
        if target.exists():
            raise FileExistsError(target)
    for year in {record["meeting_date"][:4] for _source, _target, record in plans}:
        manifest = originals_dir / year / "manifest.json"
        if manifest.exists():
            raise FileExistsError(manifest)


def _apply_plans(
    plans: list[tuple[Path, Path, dict]],
    originals_dir: Path,
) -> dict[int, dict]:
    manifests = {}
    for source, target, record in plans:
        target.parent.mkdir(parents=True, exist_ok=True)
        source.replace(target)
        year = int(record["meeting_date"][:4])
        manifest = manifests.setdefault(year, _empty_manifest(year))
        entry = _manifest_entry(manifest, record["meeting_date"])
        state = entry["documents"].setdefault(
            record["kind"],
            {"current": None, "revisions": []},
        )
        clean_record = {key: value for key, value in record.items() if key not in {"meeting_date", "kind", "current"}}
        if record["current"]:
            state["current"] = clean_record
        else:
            state["revisions"].append(clean_record)
    return manifests


def _manifest_entry(manifest: dict, meeting_date: str) -> dict:
    for entry in manifest["meetings"]:
        if entry["meeting_date"] == meeting_date:
            return entry
    entry = {
        "meeting_date": meeting_date,
        "title": "City Council Meeting",
        "event_id": None,
        "documents": {},
    }
    manifest["meetings"].append(entry)
    return entry


def _empty_manifest(year: int) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "year": year,
        "last_checked_at": None,
        "meetings": [],
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    main()
