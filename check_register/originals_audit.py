"""Audit integrity of the category-first source originals archive."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any

from .civicclerk import (
    CITY_COUNCIL_MEETING_TYPE,
    FINANCIAL_ADVISORY_BOARD_MEETING_TYPE,
)
from .civicclerk_archive import SCHEMA_VERSION


MEETING_TYPES = (
    CITY_COUNCIL_MEETING_TYPE,
    FINANCIAL_ADVISORY_BOARD_MEETING_TYPE,
)
_DOCUMENT_DIRECTORIES = {
    "agenda": ("agendas", "agenda-revisions"),
    "agenda_packet": ("agenda-packets", "agenda-packet-revisions"),
}
_IGNORED_ENTRY_NAMES = {".DS_Store"}
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


@dataclass
class OriginalsAudit:
    originals_dir: Path
    manifest_counts: dict[str, int]
    pdf_counts: dict[str, int]
    record_counts: dict[str, int]
    problems: list[str]


@dataclass(frozen=True)
class ManifestRecord:
    kind: str
    revision: bool
    data: dict[str, Any]
    context: str


def audit_originals(originals_dir: Path) -> OriginalsAudit:
    manifest_counts = {meeting_type: 0 for meeting_type in MEETING_TYPES}
    pdf_counts = {meeting_type: 0 for meeting_type in MEETING_TYPES}
    record_counts = {meeting_type: 0 for meeting_type in MEETING_TYPES}
    problems: list[str] = []

    if not originals_dir.is_dir():
        problems.append(f"Originals directory not found: {originals_dir}")
        return OriginalsAudit(originals_dir, manifest_counts, pdf_counts, record_counts, problems)

    _audit_root_entries(originals_dir, problems)
    for meeting_type in MEETING_TYPES:
        meeting_root = originals_dir / meeting_type
        if not meeting_root.is_dir():
            problems.append(f"Meeting type directory not found: {meeting_root}")
            continue
        manifests, pdfs, records = _audit_meeting_type(meeting_root, problems)
        manifest_counts[meeting_type] = manifests
        pdf_counts[meeting_type] = pdfs
        record_counts[meeting_type] = records

    return OriginalsAudit(originals_dir, manifest_counts, pdf_counts, record_counts, problems)


def format_originals_audit(audit: OriginalsAudit) -> list[str]:
    lines = [f"Originals archive: {audit.originals_dir}"]
    for meeting_type in MEETING_TYPES:
        lines.append(
            f"{meeting_type}: {audit.manifest_counts[meeting_type]} manifests, "
            f"{audit.pdf_counts[meeting_type]} PDFs, "
            f"{audit.record_counts[meeting_type]} manifest records",
        )
    if audit.problems:
        lines.append("Originals problems:")
        lines.extend(f"  {problem}" for problem in audit.problems)
    else:
        lines.append("Originals problems: none")
    return lines


def _audit_root_entries(originals_dir: Path, problems: list[str]) -> None:
    for entry in sorted(originals_dir.iterdir()):
        if entry.name not in MEETING_TYPES and not _is_ignored_entry(entry):
            problems.append(f"Unexpected originals root entry: {entry}")


def _audit_meeting_type(meeting_root: Path, problems: list[str]) -> tuple[int, int, int]:
    year_directories: list[Path] = []
    for entry in sorted(meeting_root.iterdir()):
        if entry.is_dir() and _is_year_directory(entry):
            year_directories.append(entry)
        elif not _is_ignored_entry(entry):
            problems.append(f"Unexpected meeting type entry: {entry}")

    if not year_directories:
        problems.append(f"No yearly directories found under {meeting_root}")

    pdf_count = 0
    record_count = 0
    for year_dir in year_directories:
        pdfs, records = _audit_year(year_dir, problems)
        pdf_count += pdfs
        record_count += records
    return len(year_directories), pdf_count, record_count


def _is_year_directory(path: Path) -> bool:
    return path.name.isdigit() and len(path.name) == 4


def _is_ignored_entry(path: Path) -> bool:
    return path.name in _IGNORED_ENTRY_NAMES


def _audit_year(year_dir: Path, problems: list[str]) -> tuple[int, int]:
    physical_pdfs = set(year_dir.rglob("*.pdf"))
    _audit_unexpected_year_files(year_dir, problems)
    manifest_path = year_dir / "manifest.json"
    manifest = _load_manifest(manifest_path, year_dir, problems)
    if manifest is None:
        return len(physical_pdfs), 0

    referenced: set[Path] = set()
    records = _manifest_records(manifest, manifest_path, year_dir, problems)
    for record in records:
        target = _audit_record(record, year_dir, problems)
        if target is None:
            continue
        if target in referenced:
            problems.append(f"Manifest path referenced more than once: {target}")
        referenced.add(target)

    for path in sorted(physical_pdfs - referenced):
        problems.append(f"Unreferenced PDF: {path}")
    return len(physical_pdfs), len(records)


def _audit_unexpected_year_files(year_dir: Path, problems: list[str]) -> None:
    manifest_path = year_dir / "manifest.json"
    for path in sorted(path for path in year_dir.rglob("*") if path.is_file()):
        if path != manifest_path and path.suffix.lower() != ".pdf" and not _is_ignored_entry(path):
            problems.append(f"Unexpected file under yearly originals directory: {path}")


def _load_manifest(
    manifest_path: Path,
    year_dir: Path,
    problems: list[str],
) -> dict[str, Any] | None:
    if not manifest_path.is_file():
        problems.append(f"Manifest not found: {manifest_path}")
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        problems.append(f"Unable to read manifest {manifest_path}: {exc}")
        return None
    if not isinstance(manifest, dict):
        problems.append(f"Invalid manifest object: {manifest_path}")
        return None
    if manifest.get("schema_version") != SCHEMA_VERSION:
        problems.append(f"Unsupported manifest schema: {manifest_path}")
    if manifest.get("year") != int(year_dir.name):
        problems.append(f"Manifest year does not match directory: {manifest_path}")
    if not isinstance(manifest.get("meetings"), list):
        problems.append(f"Manifest meetings are invalid: {manifest_path}")
        return None
    return manifest


def _manifest_records(
    manifest: dict[str, Any],
    manifest_path: Path,
    year_dir: Path,
    problems: list[str],
) -> list[ManifestRecord]:
    records: list[ManifestRecord] = []
    for index, meeting in enumerate(manifest["meetings"], start=1):
        context = f"{manifest_path}: meeting {index}"
        if not isinstance(meeting, dict):
            problems.append(f"Invalid meeting entry: {context}")
            continue
        _audit_meeting_date(meeting, context, year_dir, problems)
        documents = meeting.get("documents")
        if not isinstance(documents, dict):
            problems.append(f"Invalid documents entry: {context}")
            continue
        for kind, state in documents.items():
            record_context = f"{context} {kind}"
            if kind not in _DOCUMENT_DIRECTORIES:
                problems.append(f"Unsupported document kind: {record_context}")
                continue
            if not isinstance(state, dict):
                problems.append(f"Invalid document state: {record_context}")
                continue
            current = state.get("current")
            if current is not None:
                if isinstance(current, dict):
                    records.append(ManifestRecord(kind, False, current, record_context))
                else:
                    problems.append(f"Invalid current document record: {record_context}")
            revisions = state.get("revisions")
            if not isinstance(revisions, list):
                problems.append(f"Invalid document revisions: {record_context}")
                continue
            for revision_index, revision in enumerate(revisions, start=1):
                if isinstance(revision, dict):
                    records.append(
                        ManifestRecord(kind, True, revision, f"{record_context} revision {revision_index}"),
                    )
                else:
                    problems.append(f"Invalid revision document record: {record_context}")
    return records


def _audit_meeting_date(
    meeting: dict[str, Any],
    context: str,
    year_dir: Path,
    problems: list[str],
) -> None:
    value = meeting.get("meeting_date")
    if not isinstance(value, str):
        problems.append(f"Meeting date is invalid: {context}")
        return
    try:
        meeting_date = date.fromisoformat(value)
    except ValueError:
        problems.append(f"Meeting date is invalid: {context}")
        return
    if meeting_date.year != int(year_dir.name):
        problems.append(f"Meeting date is outside its yearly directory: {context}")


def _audit_record(record: ManifestRecord, year_dir: Path, problems: list[str]) -> Path | None:
    value = record.data.get("path")
    if not isinstance(value, str) or not value:
        problems.append(f"Document path is invalid: {record.context}")
        return None
    relative_path = PurePosixPath(value)
    if "\\" in value or relative_path.is_absolute() or ".." in relative_path.parts:
        problems.append(f"Unsafe document path: {record.context}")
        return None

    expected_directory = _DOCUMENT_DIRECTORIES[record.kind][int(record.revision)]
    if len(relative_path.parts) != 2 or relative_path.parts[0] != expected_directory:
        problems.append(f"Document path is in the wrong directory: {record.context}")
        return None
    if relative_path.suffix.lower() != ".pdf":
        problems.append(f"Document path is not a PDF: {record.context}")
        return None

    target = year_dir / Path(*relative_path.parts)
    if not target.is_file():
        problems.append(f"Manifest PDF not found: {target}")
        return None
    if target.is_symlink():
        problems.append(f"Manifest PDF is a symlink: {target}")
        return target
    if not _has_pdf_header(target):
        problems.append(f"Manifest PDF header is invalid: {target}")
    _audit_sha256(record, target, problems)
    return target


def _has_pdf_header(path: Path) -> bool:
    with path.open("rb") as handle:
        return handle.read(5) == b"%PDF-"


def _audit_sha256(record: ManifestRecord, path: Path, problems: list[str]) -> None:
    expected = record.data.get("sha256")
    if not isinstance(expected, str) or not _SHA256_PATTERN.fullmatch(expected):
        problems.append(f"Manifest SHA-256 is invalid: {record.context}")
        return
    if _sha256(path) != expected:
        problems.append(f"SHA-256 mismatch: {path}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
