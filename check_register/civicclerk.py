from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import hashlib
import json
from pathlib import Path
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from project_paths import ORIGINALS_DIR


DEFAULT_CITY_CODE = "elcerritoca"
DEFAULT_CATEGORY = "City Council"
DEFAULT_DOCUMENT_KINDS = ("agenda_packet",)


class CivicClerkApiError(RuntimeError):
    """Raised when CivicClerk data cannot be fetched or interpreted."""


@dataclass(frozen=True)
class CivicClerkDocument:
    file_id: int | None
    kind: str
    name: str
    stream_url: str
    url: str | None = None
    publish_on: str | None = None
    file_type: int | None = None


@dataclass(frozen=True)
class CivicClerkMeeting:
    id: int
    city_code: str
    event_date: date
    event_datetime: str
    name: str
    category: str | None
    city_name: str
    raw: dict[str, Any]


@dataclass(frozen=True)
class CachedDocument:
    path: Path
    bytes_written: int
    sha256: str | None
    content_type: str | None = None
    skipped: bool = False


_SPACES = re.compile(r"\s+")
CITY_COUNCIL_MEETING_TYPE = "city-council"
FINANCIAL_ADVISORY_BOARD_MEETING_TYPE = "financial-advisory-board"
_MEETING_TYPE_SLUGS = {
    "city council": CITY_COUNCIL_MEETING_TYPE,
    "financial advisory board": FINANCIAL_ADVISORY_BOARD_MEETING_TYPE,
}
_KIND_ALIASES = {
    "agenda": "agenda",
    "agenda packet": "agenda_packet",
    "agenda-packet": "agenda_packet",
    "agenda_packet": "agenda_packet",
    "packet": "agenda_packet",
    "minutes": "minutes",
    "notice": "notice",
}
_FILE_TYPE_KINDS = {
    1: "agenda",
    2: "agenda_packet",
    4: "minutes",
    5: "notice",
}


def events_api_url(city_code: str) -> str:
    return f"https://{city_code}.api.civicclerk.com/v1/Events"


def event_api_url(city_code: str, event_id: int) -> str:
    return f"{events_api_url(city_code)}/{event_id}"


def meeting_file_stream_url(city_code: str, file_id: int) -> str:
    return (
        f"https://{city_code}.api.civicclerk.com/v1/Meetings/"
        f"GetMeetingFileStream(fileId={file_id},plainText=false)"
    )


def portal_event_url(city_code: str, event_id: int) -> str:
    return f"https://{city_code}.portal.civicclerk.com/event/{event_id}"


def fetch_meeting(
    city_code: str,
    event_id: int,
    *,
    timeout: float = 30.0,
) -> CivicClerkMeeting:
    return parse_meeting(
        _fetch_json(event_api_url(city_code, event_id), timeout=timeout),
        city_code=city_code,
    )


def fetch_meetings(
    city_code: str,
    *,
    start: date,
    end: date,
    category: str | None = DEFAULT_CATEGORY,
    timeout: float = 30.0,
) -> list[CivicClerkMeeting]:
    meetings: list[CivicClerkMeeting] = []
    filter_parts = [
        f"eventDate ge {start.isoformat()}T00:00:00Z",
        f"eventDate lt {end.isoformat()}T00:00:00Z",
    ]
    if category:
        filter_parts.append(f"categoryName eq '{_odata_quote(category)}'")

    params = {
        "$filter": " and ".join(filter_parts),
        "$orderby": "eventDate asc",
        "$top": "50",
    }
    url = events_api_url(city_code) + "?" + urlencode(params)

    while url:
        data = _fetch_json(url, timeout=timeout)
        values = data.get("value")
        if not isinstance(values, list):
            raise CivicClerkApiError(f"Expected event list from {url}")
        for item in values:
            if isinstance(item, dict) and item.get("isDeleted") is not True:
                meetings.append(parse_meeting(item, city_code=city_code))
        next_url = data.get("@odata.nextLink")
        url = next_url if isinstance(next_url, str) else ""

    return sorted(meetings, key=lambda meeting: (meeting.event_datetime, meeting.id))


def parse_meeting(
    event: dict[str, Any],
    *,
    city_code: str = DEFAULT_CITY_CODE,
) -> CivicClerkMeeting:
    event_id = _int_value(event.get("id"))
    if event_id is None:
        raise CivicClerkApiError("Event metadata does not include an id")
    event_datetime = _string_value(event, "eventDate") or _string_value(event, "startDateTime")
    if not event_datetime:
        raise CivicClerkApiError(f"Event {event_id} does not include eventDate or startDateTime")

    return CivicClerkMeeting(
        id=event_id,
        city_code=city_code,
        event_date=_parse_event_date(event_datetime),
        event_datetime=event_datetime,
        name=_string_value(event, "eventName") or _string_value(event, "agendaName") or "Meeting",
        category=_string_value(event, "categoryName") or _string_value(event, "eventCategoryName"),
        city_name=_city_name(event, "El Cerrito"),
        raw=event,
    )


def fetch_current_meeting(
    city_code: str = DEFAULT_CITY_CODE,
    *,
    today: date | None = None,
    days_back: int = 45,
    days_forward: int = 45,
    category: str | None = DEFAULT_CATEGORY,
    timeout: float = 30.0,
) -> CivicClerkMeeting | None:
    anchor = today or date.today()
    start = anchor - timedelta(days=days_back)
    end = anchor + timedelta(days=days_forward + 1)
    meetings = fetch_meetings(
        city_code,
        start=start,
        end=end,
        category=category,
        timeout=timeout,
    )
    hydrated = [fetch_meeting(city_code, meeting.id, timeout=timeout) for meeting in meetings]
    return select_current_meeting(hydrated, today=anchor)


def select_current_meeting(
    meetings: list[CivicClerkMeeting],
    *,
    today: date | None = None,
    document_kinds: tuple[str, ...] = DEFAULT_DOCUMENT_KINDS,
) -> CivicClerkMeeting | None:
    anchor = today or date.today()
    with_documents = [
        meeting for meeting in meetings
        if meeting_has_any_document(meeting, document_kinds=document_kinds)
    ]
    upcoming = [meeting for meeting in with_documents if meeting.event_date >= anchor]
    if upcoming:
        return sorted(upcoming, key=lambda meeting: (meeting.event_date, meeting.id))[0]
    if with_documents:
        return sorted(with_documents, key=lambda meeting: (meeting.event_date, meeting.id))[-1]
    return None


def meeting_has_any_document(
    meeting: CivicClerkMeeting,
    *,
    document_kinds: tuple[str, ...] = DEFAULT_DOCUMENT_KINDS,
) -> bool:
    documents = published_documents(meeting)
    return any(select_document(documents, kind) is not None for kind in document_kinds)


def published_documents(meeting: CivicClerkMeeting) -> list[CivicClerkDocument]:
    files = meeting.raw.get("publishedFiles")
    if not isinstance(files, list):
        return []

    documents: list[CivicClerkDocument] = []
    for item in files:
        if not isinstance(item, dict):
            continue
        file_type = _int_value(item.get("fileType"))
        file_id = _int_value(item.get("fileId"))
        stream_url = _document_stream_url(meeting.city_code, item, file_id)
        if not stream_url:
            continue
        kind = _document_kind(
            _string_value(item, "type"),
            _string_value(item, "name"),
            file_type,
        )
        documents.append(
            CivicClerkDocument(
                file_id=file_id,
                kind=kind,
                name=_string_value(item, "name") or _string_value(item, "type") or "Document",
                stream_url=stream_url,
                url=_string_value(item, "url"),
                publish_on=_string_value(item, "publishOn"),
                file_type=file_type,
            ),
        )
    return sorted(documents, key=_document_sort_key)


def select_document(
    documents: list[CivicClerkDocument],
    kind: str,
) -> CivicClerkDocument | None:
    normalized = normalize_document_kind(kind)
    matches = [document for document in documents if document.kind == normalized]
    if not matches:
        return None
    return sorted(matches, key=_document_sort_key)[-1]


def normalize_document_kind(kind: str) -> str:
    normalized = _SPACES.sub(" ", kind.strip().lower().replace("_", " ")).strip()
    return _KIND_ALIASES.get(normalized, normalized.replace(" ", "_"))


def meeting_type_slug(category: str | None) -> str:
    if not category:
        raise ValueError("CivicClerk meeting category is required for the originals archive")
    normalized = _SPACES.sub(" ", category.strip().lower()).strip()
    try:
        return _MEETING_TYPE_SLUGS[normalized]
    except KeyError as exc:
        raise ValueError(
            f"Unsupported CivicClerk meeting category for the originals archive: {category}",
        ) from exc


def document_cache_path(
    meeting: CivicClerkMeeting,
    document: CivicClerkDocument,
    *,
    originals_dir: Path = ORIGINALS_DIR,
) -> Path:
    directory = {
        "agenda": "agendas",
        "agenda_packet": "agenda-packets",
    }[document.kind]
    return (
        originals_dir
        / meeting_type_slug(meeting.category)
        / str(meeting.event_date.year)
        / directory
        / document_cache_filename(meeting, document)
    )


def document_cache_filename(
    meeting: CivicClerkMeeting,
    document: CivicClerkDocument,
) -> str:
    label = {
        "agenda": "Agenda",
        "agenda_packet": "Agenda Packet",
    }[document.kind]
    return f"{meeting.event_date.isoformat()} {label}.pdf"


def download_document(
    document: CivicClerkDocument,
    output_path: Path,
    *,
    overwrite: bool = False,
    timeout: float = 60.0,
) -> CachedDocument:
    if output_path.exists() and not overwrite:
        return CachedDocument(output_path, output_path.stat().st_size, None, skipped=True)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    part_path = output_path.with_name(output_path.name + ".part")
    try:
        part_path.unlink()
    except FileNotFoundError:
        pass

    request = Request(
        document.stream_url,
        headers={
            "Accept": "application/pdf,*/*",
            "User-Agent": "ECCheckParser/1.0",
        },
    )
    sha256 = hashlib.sha256()
    bytes_written = 0
    content_type: str | None = None

    try:
        with urlopen(request, timeout=timeout) as response:
            content_type = response.headers.get("content-type")
            with part_path.open("wb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
                    sha256.update(chunk)
                    bytes_written += len(chunk)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        try:
            part_path.unlink()
        except FileNotFoundError:
            pass
        raise CivicClerkApiError(f"Could not download {document.stream_url}: {exc}") from exc

    part_path.replace(output_path)
    return CachedDocument(
        output_path,
        bytes_written,
        sha256.hexdigest(),
        content_type=content_type,
    )


def normalize_document_url(
    city_code: str,
    value: str,
    *,
    file_id: int | None = None,
) -> str:
    cleaned = value.strip()
    if cleaned.startswith(("http://", "https://")):
        return cleaned
    if file_id is not None:
        return meeting_file_stream_url(city_code, file_id)
    prefix = "stream/"
    if cleaned.startswith(prefix):
        parts = cleaned.split("/")
        if len(parts) >= 3:
            return f"https://cpmedia.azureedge.net/{city_code.lower()}/{'/'.join(parts[2:])}"
    return cleaned


def _fetch_json(url: str, *, timeout: float) -> dict[str, Any]:
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "ECCheckParser/1.0",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = response.read()
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise CivicClerkApiError(f"Could not fetch {url}: {exc}") from exc

    try:
        data = json.loads(payload.decode("utf-8"))
    except ValueError as exc:
        raise CivicClerkApiError(f"Response was not JSON: {url}") from exc
    if not isinstance(data, dict):
        raise CivicClerkApiError(f"Expected JSON object from {url}")
    return data


def _document_stream_url(
    city_code: str,
    item: dict[str, Any],
    file_id: int | None,
) -> str | None:
    for key in ("streamUrl", "url"):
        value = _string_value(item, key)
        if value:
            return normalize_document_url(city_code, value, file_id=file_id)
    if file_id is not None:
        return meeting_file_stream_url(city_code, file_id)
    return None


def _document_kind(type_value: str | None, name: str | None, file_type: int | None) -> str:
    if file_type in _FILE_TYPE_KINDS:
        return _FILE_TYPE_KINDS[file_type]
    for value in (type_value, name):
        if not value:
            continue
        normalized = normalize_document_kind(value)
        if normalized in _KIND_ALIASES.values():
            return normalized
        if "agenda_packet" in normalized:
            return "agenda_packet"
        if normalized == "agenda":
            return "agenda"
    return normalize_document_kind(type_value or name or "document")


def _document_sort_key(document: CivicClerkDocument) -> tuple[str, int, int]:
    return (
        document.publish_on or "",
        document.file_id or 0,
        document.file_type or 0,
    )


def _parse_event_date(value: str) -> date:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError as exc:
        raise CivicClerkApiError(f"Could not parse event date: {value}") from exc


def _city_name(event: dict[str, Any], fallback: str) -> str:
    location = event.get("eventLocation")
    if isinstance(location, dict):
        value = _string_value(location, "city")
        if value:
            return value
    return fallback


def _odata_quote(value: str) -> str:
    return value.replace("'", "''")


def _string_value(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _int_value(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None
