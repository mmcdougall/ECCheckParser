"""Store Archive Center documents under a selected originals category."""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone
import hashlib
from pathlib import Path
import re
from typing import Any

from .archivecenter import ArchiveCenterDocument, ArchiveCenterError, CachedArchiveCenterDocument, download_document
from .civicclerk_archive import ArchivedDocument, load_manifest, manifest_path, write_manifest
from .originals_layout import DOCUMENT_LAYOUTS, validate_meeting_type


_ARCHIVE_ITEM_URL = re.compile(r"/ArchiveCenter/ViewFile/Item/(?P<archive_id>\d+)", re.IGNORECASE)
_NUMERIC_FILENAME_DATE = re.compile(
    r"(?<!\d)(?P<month>\d{1,2})[ _-](?P<day>\d{1,2})[ _-](?P<year>\d{2,4})(?!\d)",
)


def archive_document(
    document: ArchiveCenterDocument,
    *,
    originals_dir: Path,
    meeting_type: str,
    dry_run: bool = False,
    include_variants: bool = False,
    timeout: float = 60.0,
) -> ArchivedDocument:
    """Cache one PDF and preserve Archive Center provenance in its manifest."""
    validate_meeting_type(meeting_type)
    if document.kind not in DOCUMENT_LAYOUTS:
        raise ValueError(f"Unsupported Archive Center document kind: {document.kind}")
    if document.listing_date is None:
        raise ArchiveCenterError(
            f"Archive Center item {document.archive_id} has no parseable listing date",
        )
    if not document.is_pdf:
        raise ArchiveCenterError(
            f"Archive Center item {document.archive_id} is not marked as a PDF",
        )

    meeting_date = document.listing_date
    manifest_file = manifest_path(originals_dir, meeting_type, meeting_date.year)
    manifest = load_manifest(manifest_file, year=meeting_date.year)
    entry = _meeting_entry(manifest, meeting_date, meeting_type)
    state = entry["documents"].setdefault(
        document.kind,
        {"current": None, "revisions": []},
    )
    state.setdefault("revisions", [])
    checked_at = _now()
    manifest["last_checked_at"] = checked_at
    year_dir = manifest_file.parent
    current = state.get("current")
    known = _known_archive_record(state, document.archive_id)

    if known is not None:
        return _use_known_document(
            document, known, state, manifest, manifest_file, checked_at,
            dry_run=dry_run, timeout=timeout,
        )

    canonical_path = year_dir / DOCUMENT_LAYOUTS[document.kind].canonical / (
        f"{meeting_date.isoformat()} {DOCUMENT_LAYOUTS[document.kind].label}.pdf"
    )
    if current and _is_archive_record(current) and isinstance(current.get("path"), str):
        canonical_path = year_dir / current["path"]
    if current and not _is_archive_record(current):
        if not include_variants:
            path = year_dir / current["path"]
            return ArchivedDocument(
                path,
                "skipped-existing",
                path.stat().st_size if path.exists() else 0,
                current.get("sha256"),
            )
        if dry_run:
            return ArchivedDocument(
                _variant_path(year_dir, meeting_date, document),
                "variant-download",
                0,
                None,
            )
        cached = _download_checked(document, canonical_path, timeout=timeout)
        return _install_variant(
            document,
            cached,
            year_dir,
            meeting_date,
            state,
            manifest,
            manifest_file,
            checked_at,
        )

    if dry_run:
        action = "replace" if current else "download"
        return ArchivedDocument(canonical_path, action, 0, None)

    cached = _download_checked(document, canonical_path, timeout=timeout)
    if current:
        return _replace_archive_current(
            document,
            cached,
            canonical_path,
            meeting_date,
            state,
            manifest,
            manifest_file,
            checked_at,
        )
    return _install_current(
        document,
        cached,
        canonical_path,
        state,
        manifest,
        manifest_file,
        checked_at,
    )


def _use_known_document(
    document: ArchiveCenterDocument,
    known: dict[str, Any],
    state: dict[str, Any],
    manifest: dict[str, Any],
    manifest_file: Path,
    checked_at: str,
    *,
    dry_run: bool,
    timeout: float,
) -> ArchivedDocument:
    path = _known_path(manifest_file.parent, state, known)
    action = "unchanged"
    if not path.exists():
        if dry_run:
            return ArchivedDocument(path, "download", 0, None)
        cached = _download_checked(document, path, timeout=timeout)
        record = known if "path" in known else state["current"]
        if record.get("sha256") != cached.sha256:
            _remove_file(cached.path)
            raise ArchiveCenterError(
                f"Archive Center item {document.archive_id} cannot restore the missing "
                f"cached document: downloaded SHA-256 differs from the manifest",
            )
        cached.path.replace(path)
        action = "downloaded"
    _refresh_archive_metadata(known, document, checked_at)
    if not dry_run:
        write_manifest(manifest_file, manifest)
    return ArchivedDocument(path, action, path.stat().st_size, known.get("sha256"))


def _download_checked(
    document: ArchiveCenterDocument,
    canonical_path: Path,
    *,
    timeout: float,
) -> CachedArchiveCenterDocument:
    incoming = canonical_path.with_name(canonical_path.name + ".download")
    cached = download_document(document, incoming, timeout=timeout)
    filename_date = _filename_date(cached.source_filename)
    if filename_date is not None and filename_date != document.listing_date:
        _remove_file(cached.path)
        raise ArchiveCenterError(
            f"Archive Center item {document.archive_id} listing date "
            f"{document.listing_date.isoformat()} conflicts with downloaded filename "
            f"{cached.source_filename!r} ({filename_date.isoformat()})",
        )
    return cached


def _install_current(
    document: ArchiveCenterDocument,
    cached: CachedArchiveCenterDocument,
    path: Path,
    state: dict[str, Any],
    manifest: dict[str, Any],
    manifest_file: Path,
    checked_at: str,
) -> ArchivedDocument:
    path.parent.mkdir(parents=True, exist_ok=True)
    cached.path.replace(path)
    state["current"] = _document_record(document, path, cached, checked_at)
    write_manifest(manifest_file, manifest)
    return ArchivedDocument(path, "downloaded", cached.bytes_written, cached.sha256)


def _replace_archive_current(
    document: ArchiveCenterDocument,
    cached: CachedArchiveCenterDocument,
    canonical_path: Path,
    meeting_date: date,
    state: dict[str, Any],
    manifest: dict[str, Any],
    manifest_file: Path,
    checked_at: str,
) -> ArchivedDocument:
    current = state.get("current")
    existing_sha = _existing_sha(canonical_path, current)
    if existing_sha == cached.sha256:
        _remove_file(cached.path)
        state["current"] = _document_record(document, canonical_path, cached, checked_at)
        write_manifest(manifest_file, manifest)
        return ArchivedDocument(
            canonical_path,
            "metadata-updated",
            canonical_path.stat().st_size,
            cached.sha256,
        )

    revision_path = _archive_current_revision(
        canonical_path,
        meeting_date,
        document.kind,
        current,
        state,
        checked_at,
    )
    cached.path.replace(canonical_path)
    state["current"] = _document_record(document, canonical_path, cached, checked_at)
    write_manifest(manifest_file, manifest)
    return ArchivedDocument(
        canonical_path,
        "revised",
        cached.bytes_written,
        cached.sha256,
        revision_path,
    )


def _install_variant(
    document: ArchiveCenterDocument,
    cached: CachedArchiveCenterDocument,
    year_dir: Path,
    meeting_date: date,
    state: dict[str, Any],
    manifest: dict[str, Any],
    manifest_file: Path,
    checked_at: str,
) -> ArchivedDocument:
    current = state["current"]
    current_path = year_dir / current["path"]
    if _existing_sha(current_path, current) == cached.sha256:
        _remove_file(cached.path)
        equivalent = _equivalent_source_record(document, cached, checked_at)
        state.setdefault("equivalent_sources", []).append(equivalent)
        write_manifest(manifest_file, manifest)
        return ArchivedDocument(
            current_path,
            "identical-to-current",
            current_path.stat().st_size,
            cached.sha256,
        )

    revision_path = _variant_path(year_dir, meeting_date, document)
    revision_path.parent.mkdir(parents=True, exist_ok=True)
    cached.path.replace(revision_path)
    state["revisions"].append(
        _document_record(document, revision_path, cached, checked_at),
    )
    state["revisions"] = sorted(
        state["revisions"],
        key=lambda record: record["path"],
    )
    write_manifest(manifest_file, manifest)
    return ArchivedDocument(
        revision_path,
        "variant-downloaded",
        cached.bytes_written,
        cached.sha256,
    )


def _meeting_entry(
    manifest: dict[str, Any], meeting_date: date, meeting_type: str,
) -> dict[str, Any]:
    matches = [
        entry
        for entry in manifest["meetings"]
        if entry.get("meeting_date") == meeting_date.isoformat()
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ArchiveCenterError(
            f"Archive Center date {meeting_date.isoformat()} matches multiple local {meeting_type} entries",
        )
    entry = {
        "meeting_date": meeting_date.isoformat(),
        "title": meeting_type.replace("-", " ").title(),
        "event_id": None,
        "documents": {},
    }
    manifest["meetings"].append(entry)
    return entry


def _variant_path(year_dir: Path, meeting_date: date, document: ArchiveCenterDocument) -> Path:
    layout = DOCUMENT_LAYOUTS[document.kind]
    directory = year_dir / layout.revisions
    stem = f"{meeting_date.isoformat()} {layout.label} - ArchiveCenter {document.archive_id}"
    candidate = directory / f"{stem}.pdf"
    if not candidate.exists():
        return candidate
    index = 2
    while True:
        candidate = directory / f"{stem} ({index}).pdf"
        if not candidate.exists():
            return candidate
        index += 1


def _archive_current_revision(
    canonical_path: Path,
    meeting_date: date,
    kind: str,
    current: dict[str, Any] | None,
    state: dict[str, Any],
    checked_at: str,
) -> Path:
    previous = deepcopy(current) if current else _local_record(canonical_path)
    previous_id = _archive_id(previous)
    suffix = f"ArchiveCenter {previous_id}" if previous_id is not None else "ArchiveCenter prior"
    layout = DOCUMENT_LAYOUTS[kind]
    directory = canonical_path.parents[1] / layout.revisions
    stem = f"{meeting_date.isoformat()} {layout.label} - {suffix}"
    revision_path = directory / f"{stem}.pdf"
    index = 2
    while revision_path.exists():
        revision_path = directory / f"{stem} ({index}).pdf"
        index += 1
    revision_path.parent.mkdir(parents=True, exist_ok=True)
    canonical_path.replace(revision_path)
    previous["path"] = _year_relative(revision_path)
    previous["superseded_at"] = checked_at
    state["revisions"].append(previous)
    state["revisions"] = sorted(state["revisions"], key=lambda record: record["path"])
    return revision_path


def _known_archive_record(state: dict[str, Any], archive_id: int) -> dict[str, Any] | None:
    current = state.get("current")
    if isinstance(current, dict) and _archive_id(current) == archive_id:
        return current
    for record in state.get("revisions", []):
        if isinstance(record, dict) and _archive_id(record) == archive_id:
            return record
    for record in state.get("equivalent_sources", []):
        if isinstance(record, dict) and _archive_id(record) == archive_id:
            return record
    return None


def _known_path(year_dir: Path, state: dict[str, Any], record: dict[str, Any]) -> Path:
    path = record.get("path")
    if isinstance(path, str):
        return year_dir / path
    current = state.get("current")
    if isinstance(current, dict) and isinstance(current.get("path"), str):
        return year_dir / current["path"]
    raise ArchiveCenterError("Archive Center provenance does not resolve to a cached document")


def _is_archive_record(record: dict[str, Any]) -> bool:
    return _archive_id(record) is not None


def _archive_id(record: dict[str, Any]) -> int | None:
    value = record.get("archive_id")
    if isinstance(value, int):
        return value
    source_url = record.get("source_url")
    if not isinstance(source_url, str):
        return None
    match = _ARCHIVE_ITEM_URL.search(source_url)
    return int(match.group("archive_id")) if match else None


def _refresh_archive_metadata(
    record: dict[str, Any],
    document: ArchiveCenterDocument,
    checked_at: str,
) -> None:
    record["source_system"] = "archivecenter"
    record["archive_id"] = document.archive_id
    if _archive_id(record) == document.archive_id and record.get("file_id") == document.archive_id:
        record["file_id"] = None
    record["official_name"] = document.listing_title
    record["listing_title"] = document.listing_title
    record["listing_description"] = document.listing_description
    record["listing_date"] = document.listing_date.isoformat() if document.listing_date else None
    record["archive_listing_url"] = document.listing_url
    record["source_url"] = document.source_url
    record["last_checked_at"] = checked_at


def _document_record(
    document: ArchiveCenterDocument,
    path: Path,
    cached: CachedArchiveCenterDocument,
    checked_at: str,
) -> dict[str, Any]:
    return {
        "path": _year_relative(path),
        "source_system": "archivecenter",
        "file_id": None,
        "archive_id": document.archive_id,
        "official_name": document.listing_title,
        "listing_title": document.listing_title,
        "listing_description": document.listing_description,
        "listing_date": document.listing_date.isoformat() if document.listing_date else None,
        "archive_listing_url": document.listing_url,
        "published_at": None,
        "downloaded_at": checked_at,
        "last_checked_at": checked_at,
        "size": cached.bytes_written,
        "sha256": cached.sha256,
        "source_url": document.source_url,
        "source_filename": cached.source_filename,
    }


def _equivalent_source_record(
    document: ArchiveCenterDocument,
    cached: CachedArchiveCenterDocument,
    checked_at: str,
) -> dict[str, Any]:
    return {
        "source_system": "archivecenter",
        "file_id": None,
        "archive_id": document.archive_id,
        "official_name": document.listing_title,
        "listing_title": document.listing_title,
        "listing_description": document.listing_description,
        "listing_date": document.listing_date.isoformat() if document.listing_date else None,
        "archive_listing_url": document.listing_url,
        "published_at": None,
        "downloaded_at": checked_at,
        "last_checked_at": checked_at,
        "size": cached.bytes_written,
        "sha256": cached.sha256,
        "source_url": document.source_url,
        "source_filename": cached.source_filename,
    }


def _local_record(path: Path) -> dict[str, Any]:
    return {
        "path": _year_relative(path),
        "file_id": None,
        "official_name": path.name,
        "published_at": None,
        "downloaded_at": None,
        "last_checked_at": None,
        "size": path.stat().st_size,
        "sha256": _sha256(path),
        "source_url": None,
    }


def _existing_sha(path: Path, current: dict[str, Any] | None) -> str | None:
    if not path.exists():
        return None
    if current and current.get("sha256"):
        return current["sha256"]
    return _sha256(path)


def _filename_date(value: str | None) -> date | None:
    if not value:
        return None
    match = _NUMERIC_FILENAME_DATE.search(value)
    if not match:
        return None
    year = int(match.group("year"))
    if year < 100:
        year += 2000
    try:
        return date(year, int(match.group("month")), int(match.group("day")))
    except ValueError:
        return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _year_relative(path: Path) -> str:
    return path.relative_to(path.parents[1]).as_posix()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _remove_file(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
