from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from .civicclerk import (
    CachedDocument,
    CivicClerkDocument,
    CivicClerkMeeting,
    download_document,
)


SCHEMA_VERSION = 1
_CANONICAL_DIRS = {
    "agenda": "agendas",
    "agenda_packet": "agenda-packets",
}
_REVISION_DIRS = {
    "agenda": "agenda-revisions",
    "agenda_packet": "agenda-packet-revisions",
}
_DOCUMENT_LABELS = {
    "agenda": "Agenda",
    "agenda_packet": "Agenda Packet",
}


@dataclass(frozen=True)
class ArchivedDocument:
    path: Path
    action: str
    bytes_written: int
    sha256: str | None
    revision_path: Path | None = None


def canonical_document_path(
    meeting: CivicClerkMeeting,
    document: CivicClerkDocument,
    *,
    originals_dir: Path,
) -> Path:
    directory = _CANONICAL_DIRS[document.kind]
    filename = f"{meeting.event_date.isoformat()} {_DOCUMENT_LABELS[document.kind]}.pdf"
    return originals_dir / str(meeting.event_date.year) / directory / filename


def manifest_path(originals_dir: Path, year: int) -> Path:
    return originals_dir / str(year) / "manifest.json"


def load_manifest(path: Path, *, year: int) -> dict[str, Any]:
    if not path.exists():
        return _empty_manifest(year)
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"Unsupported archive manifest schema: {path}")
    if data.get("year") != year or not isinstance(data.get("meetings"), list):
        raise ValueError(f"Invalid archive manifest: {path}")
    return data


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest["meetings"] = sorted(
        manifest["meetings"],
        key=lambda item: (item["meeting_date"], item.get("event_id") or 0),
    )
    payload = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    part_path = path.with_name(path.name + ".part")
    part_path.write_text(payload, encoding="utf-8")
    part_path.replace(path)


def archive_document(
    meeting: CivicClerkMeeting,
    document: CivicClerkDocument,
    *,
    originals_dir: Path,
    dry_run: bool = False,
    overwrite: bool = False,
    timeout: float = 60.0,
) -> ArchivedDocument:
    manifest_file = manifest_path(originals_dir, meeting.event_date.year)
    manifest = load_manifest(manifest_file, year=meeting.event_date.year)
    entry = _meeting_entry(manifest, meeting)
    state = entry["documents"].setdefault(
        document.kind,
        {"current": None, "revisions": []},
    )
    path = _resolved_canonical_path(
        meeting,
        document,
        originals_dir,
        manifest,
        entry,
        state,
    )
    current = state.get("current")
    checked_at = _now()
    manifest["last_checked_at"] = checked_at

    if not overwrite and path.exists() and _remote_unchanged(current, document):
        _refresh_remote_metadata(current, document, checked_at)
        if not dry_run:
            write_manifest(manifest_file, manifest)
        return ArchivedDocument(path, "unchanged", path.stat().st_size, current.get("sha256"))

    if dry_run:
        action = "replace" if path.exists() else "download"
        return ArchivedDocument(path, action, 0, None)

    incoming = path.with_name(path.name + ".download")
    cached = download_document(document, incoming, overwrite=True, timeout=timeout)
    return _install_download(
        meeting,
        document,
        cached,
        path,
        state,
        manifest,
        manifest_file,
        checked_at,
    )


def _install_download(
    meeting: CivicClerkMeeting,
    document: CivicClerkDocument,
    cached: CachedDocument,
    path: Path,
    state: dict[str, Any],
    manifest: dict[str, Any],
    manifest_file: Path,
    checked_at: str,
) -> ArchivedDocument:
    current = state.get("current")
    existing_sha = _existing_sha(path, current)
    if path.exists() and existing_sha == cached.sha256:
        cached.path.unlink()
        state["current"] = _document_record(
            meeting,
            document,
            path,
            cached,
            checked_at,
        )
        write_manifest(manifest_file, manifest)
        return ArchivedDocument(path, "metadata-updated", path.stat().st_size, cached.sha256)

    revision_path = None
    if path.exists():
        revision_path = _archive_current_revision(
            meeting,
            document,
            path,
            current,
            state,
            checked_at,
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    cached.path.replace(path)
    state["current"] = _document_record(
        meeting,
        document,
        path,
        cached,
        checked_at,
    )
    write_manifest(manifest_file, manifest)
    action = "revised" if revision_path else "downloaded"
    return ArchivedDocument(path, action, cached.bytes_written, cached.sha256, revision_path)


def _resolved_canonical_path(
    meeting: CivicClerkMeeting,
    document: CivicClerkDocument,
    originals_dir: Path,
    manifest: dict[str, Any],
    entry: dict[str, Any],
    state: dict[str, Any],
) -> Path:
    year_dir = originals_dir / str(meeting.event_date.year)
    current = state.get("current")
    if current and current.get("path"):
        return year_dir / current["path"]

    default = canonical_document_path(meeting, document, originals_dir=originals_dir)
    used_paths = _other_current_paths(manifest, entry, document.kind)
    if _year_relative(default) not in used_paths:
        return default

    directory = default.parent
    label = _DOCUMENT_LABELS[document.kind]
    time_token = _meeting_time_token(meeting)
    candidates = [
        directory / f"{meeting.event_date.isoformat()} {time_token} {label}.pdf",
        directory / f"{meeting.event_date.isoformat()} {time_token} {label} - e{meeting.id}.pdf",
    ]
    for candidate in candidates:
        if _year_relative(candidate) not in used_paths and not candidate.exists():
            return candidate
    raise ValueError(f"Could not choose canonical filename for event {meeting.id}")


def _other_current_paths(
    manifest: dict[str, Any],
    entry: dict[str, Any],
    kind: str,
) -> set[str]:
    paths = set()
    for candidate in manifest["meetings"]:
        if candidate is entry:
            continue
        current = candidate.get("documents", {}).get(kind, {}).get("current")
        if current and current.get("path"):
            paths.add(current["path"])
    return paths


def _meeting_time_token(meeting: CivicClerkMeeting) -> str:
    match = re.search(r"T(?P<hour>\d{2}):(?P<minute>\d{2})", meeting.event_datetime)
    if not match:
        return "0000"
    return match.group("hour") + match.group("minute")


def _archive_current_revision(
    meeting: CivicClerkMeeting,
    document: CivicClerkDocument,
    path: Path,
    current: dict[str, Any] | None,
    state: dict[str, Any],
    checked_at: str,
) -> Path:
    previous = deepcopy(current) if current else _local_record(path)
    revision_path = _revision_path(meeting, document, previous, path)
    revision_path.parent.mkdir(parents=True, exist_ok=True)
    path.replace(revision_path)
    previous["path"] = _year_relative(revision_path)
    previous["superseded_at"] = checked_at
    state["revisions"].append(previous)
    state["revisions"] = sorted(
        state["revisions"],
        key=lambda item: (item.get("published_at") or "", item["path"]),
    )
    return revision_path


def _revision_path(
    meeting: CivicClerkMeeting,
    document: CivicClerkDocument,
    record: dict[str, Any],
    canonical_path: Path,
) -> Path:
    directory = canonical_path.parents[1] / _REVISION_DIRS[document.kind]
    label = _DOCUMENT_LABELS[document.kind]
    published_at = record.get("published_at") or record.get("published_date")
    suffixes = _revision_suffixes(published_at, record.get("file_id"))
    for suffix in suffixes:
        candidate = directory / f"{meeting.event_date.isoformat()} {label} - {suffix}.pdf"
        if not candidate.exists():
            return candidate
    raise ValueError(f"Could not choose revision filename for {canonical_path}")


def _revision_suffixes(published_at: str | None, file_id: int | None) -> list[str]:
    if published_at:
        parsed = _parse_datetime(published_at)
        if parsed:
            day = parsed.date().isoformat()
            timestamp = parsed.strftime("%Y-%m-%d %H%M%SZ")
            suffixes = [day, timestamp]
            if file_id is not None:
                suffixes.append(f"{timestamp} f{file_id}")
            return suffixes
        return [published_at]
    if file_id is not None:
        return [f"f{file_id}"]
    return ["undated", f"undated {datetime.now().strftime('%Y%m%d%H%M%S')}"]


def _meeting_entry(
    manifest: dict[str, Any],
    meeting: CivicClerkMeeting,
) -> dict[str, Any]:
    for entry in manifest["meetings"]:
        if entry.get("event_id") == meeting.id:
            _refresh_meeting(entry, meeting)
            return entry
    for entry in manifest["meetings"]:
        if entry["meeting_date"] == meeting.event_date.isoformat() and entry.get("event_id") is None:
            _refresh_meeting(entry, meeting)
            return entry
    entry = {
        "meeting_date": meeting.event_date.isoformat(),
        "title": meeting.name,
        "event_id": meeting.id,
        "documents": {},
    }
    manifest["meetings"].append(entry)
    return entry


def _refresh_meeting(entry: dict[str, Any], meeting: CivicClerkMeeting) -> None:
    entry["event_id"] = meeting.id
    entry["title"] = meeting.name


def _document_record(
    meeting: CivicClerkMeeting,
    document: CivicClerkDocument,
    path: Path,
    cached: CachedDocument,
    checked_at: str,
) -> dict[str, Any]:
    return {
        "path": _year_relative(path),
        "file_id": document.file_id,
        "official_name": document.name,
        "published_at": document.publish_on,
        "downloaded_at": checked_at,
        "last_checked_at": checked_at,
        "size": cached.bytes_written,
        "sha256": cached.sha256,
        "source_url": document.stream_url,
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


def _refresh_remote_metadata(
    current: dict[str, Any],
    document: CivicClerkDocument,
    checked_at: str,
) -> None:
    current["official_name"] = document.name
    current["source_url"] = document.stream_url
    current["last_checked_at"] = checked_at


def _remote_unchanged(
    current: dict[str, Any] | None,
    document: CivicClerkDocument,
) -> bool:
    if not current or document.file_id is None or current.get("file_id") is None:
        return False
    return (
        current.get("file_id") == document.file_id
        and current.get("published_at") == document.publish_on
    )


def _existing_sha(path: Path, current: dict[str, Any] | None) -> str | None:
    if not path.exists():
        return None
    if current and current.get("sha256"):
        return current["sha256"]
    return _sha256(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _year_relative(path: Path) -> str:
    return path.relative_to(path.parents[1]).as_posix()


def _empty_manifest(year: int) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "year": year,
        "last_checked_at": None,
        "meetings": [],
    }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc)
