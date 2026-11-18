"""Fetch source records from selected El Cerrito Archive Center indexes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from html import unescape
from html.parser import HTMLParser
import hashlib
from pathlib import Path
import re
from typing import Iterable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urljoin, urlsplit
from urllib.request import Request, urlopen


ARCHIVE_CENTER_BASE_URL = "https://www.elcerrito.gov/"


class ArchiveCenterError(RuntimeError):
    """Raised when Archive Center data cannot be fetched or interpreted."""


@dataclass(frozen=True)
class ArchiveCenterDocument:
    archive_id: int
    kind: str
    listing_title: str
    listing_description: str | None
    listing_date: date | None
    listing_url: str
    source_url: str
    document_format: str | None

    @property
    def is_pdf(self) -> bool:
        return self.document_format == "pdf"


@dataclass(frozen=True)
class CachedArchiveCenterDocument:
    path: Path
    bytes_written: int
    sha256: str
    content_type: str | None
    source_filename: str | None


def archive_index_url(archive_method_id: int) -> str:
    return urljoin(ARCHIVE_CENTER_BASE_URL, f"Archive.aspx?AMID={archive_method_id}")


def archive_document_url(archive_id: int) -> str:
    return urljoin(ARCHIVE_CENTER_BASE_URL, f"ArchiveCenter/ViewFile/Item/{archive_id}")


def fetch_documents(
    indexes: Mapping[str, int], *, timeout: float = 30.0,
) -> list[ArchiveCenterDocument]:
    """Read indexes mapped explicitly from document kind to Archive Center AMID."""
    if any(archive_method_id <= 0 for archive_method_id in indexes.values()):
        raise ValueError("Archive Center index IDs must be positive integers")
    documents: list[ArchiveCenterDocument] = []
    for kind, archive_method_id in indexes.items():
        index_url = archive_index_url(archive_method_id)
        documents.extend(
            parse_archive_index(
                _fetch_text(index_url, timeout=timeout),
                kind=kind,
                listing_url=index_url,
            ),
        )
    return sorted(
        documents,
        key=lambda document: (
            document.listing_date or date.max,
            document.kind,
            document.archive_id,
        ),
    )


def parse_archive_index(
    payload: str,
    *,
    kind: str,
    listing_url: str,
) -> list[ArchiveCenterDocument]:
    parser = _ArchiveIndexParser(listing_url)
    parser.feed(payload)
    parser.close()
    return [
        ArchiveCenterDocument(
            archive_id=item.archive_id,
            kind=kind,
            listing_title=item.title,
            listing_description=item.description,
            listing_date=_listing_date(item.title),
            listing_url=item.listing_url,
            source_url=archive_document_url(item.archive_id),
            document_format=item.document_format,
        )
        for item in parser.items
    ]


def download_document(
    document: ArchiveCenterDocument,
    output_path: Path,
    *,
    timeout: float = 60.0,
) -> CachedArchiveCenterDocument:
    if not document.is_pdf:
        raise ArchiveCenterError(
            f"Archive Center item {document.archive_id} is not marked as a PDF: "
            f"{document.document_format or 'unknown format'}",
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    part_path = output_path.with_name(output_path.name + ".part")
    try:
        part_path.unlink()
    except FileNotFoundError:
        pass

    request = Request(
        document.source_url,
        headers={
            "Accept": "application/pdf,*/*",
            "User-Agent": "ECCheckParser/1.0",
        },
    )
    digest = hashlib.sha256()
    bytes_written = 0
    content_type: str | None = None
    source_filename: str | None = None
    prefix = bytearray()

    try:
        with urlopen(request, timeout=timeout) as response:
            content_type = response.headers.get("content-type")
            source_filename = _content_disposition_filename(response.headers.get("content-disposition"))
            with part_path.open("wb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
                    digest.update(chunk)
                    bytes_written += len(chunk)
                    if len(prefix) < 1024:
                        prefix.extend(chunk[: 1024 - len(prefix)])
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        _remove_part(part_path)
        raise ArchiveCenterError(f"Could not download {document.source_url}: {exc}") from exc

    if b"%PDF-" not in prefix:
        _remove_part(part_path)
        raise ArchiveCenterError(f"Archive Center item {document.archive_id} is not a PDF")

    part_path.replace(output_path)
    return CachedArchiveCenterDocument(
        path=output_path,
        bytes_written=bytes_written,
        sha256=digest.hexdigest(),
        content_type=content_type,
        source_filename=source_filename,
    )


@dataclass(frozen=True)
class _ArchiveIndexItem:
    archive_id: int
    title: str
    description: str | None
    listing_url: str
    document_format: str | None


class _ArchiveIndexParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self._base_url = base_url
        self._in_details_table = False
        self._table_depth = 0
        self._current: dict[str, object] | None = None
        self._in_anchor = False
        self._anchor_text: list[str] = []
        self._in_description = False
        self._description_text: list[str] = []
        self.items: list[_ArchiveIndexItem] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "table":
            if self._in_details_table:
                self._table_depth += 1
            elif _normalized(attributes.get("summary")).lower() == "archive details":
                self._in_details_table = True
                self._table_depth = 1
                self._current = {
                    "title": None,
                    "description": None,
                    "listing_url": None,
                    "document_format": None,
                }
            return

        if not self._in_details_table or self._current is None:
            return

        if tag == "img" and not self._current["title"]:
            self._current["title"] = _normalized(attributes.get("alt")) or None
            self._current["document_format"] = _format_from_icon(attributes.get("src"))
        elif tag == "a":
            href = attributes.get("href")
            archive_id = _archive_id_from_href(href)
            if archive_id is not None:
                self._current["archive_id"] = archive_id
                self._current["listing_url"] = urljoin(self._base_url, href or "")
                self._in_anchor = True
                self._anchor_text = []
        elif tag == "span" and "font-style" in (attributes.get("style") or "").lower():
            self._in_description = True
            self._description_text = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "table" and self._in_details_table:
            self._table_depth -= 1
            if self._table_depth == 0:
                self._finish_current()
                self._in_details_table = False
                self._current = None
            return

        if not self._in_details_table or self._current is None:
            return

        if tag == "a" and self._in_anchor:
            title = _join_text(self._anchor_text)
            if title:
                self._current["title"] = title
            self._in_anchor = False
        elif tag == "span" and self._in_description:
            description = _join_text(self._description_text)
            self._current["description"] = description or None
            self._in_description = False

    def handle_data(self, data: str) -> None:
        if self._in_anchor:
            self._anchor_text.append(data)
        elif self._in_description:
            self._description_text.append(data)

    def _finish_current(self) -> None:
        if self._current is None:
            return
        archive_id = self._current.get("archive_id")
        title = self._current.get("title")
        listing_url = self._current.get("listing_url")
        if not isinstance(archive_id, int) or not isinstance(title, str) or not isinstance(listing_url, str):
            return
        description = self._current.get("description")
        document_format = self._current.get("document_format")
        self.items.append(
            _ArchiveIndexItem(
                archive_id=archive_id,
                title=title,
                description=description if isinstance(description, str) else None,
                listing_url=listing_url,
                document_format=document_format if isinstance(document_format, str) else None,
            ),
        )


_DATE_PATTERN = re.compile(
    r"\b(?P<month>January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+(?P<day>\d{1,2})[,.]?\s+(?P<year>\d{4})\b",
    re.IGNORECASE,
)


def _fetch_text(url: str, *, timeout: float) -> str:
    request = Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "User-Agent": "ECCheckParser/1.0",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = response.read()
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise ArchiveCenterError(f"Could not fetch {url}: {exc}") from exc
    return payload.decode("utf-8", errors="replace")


def _archive_id_from_href(value: str | None) -> int | None:
    if not value:
        return None
    query = parse_qs(urlsplit(value).query)
    values = query.get("ADID") or query.get("adid")
    if not values:
        return None
    try:
        return int(values[-1])
    except ValueError:
        return None


def _listing_date(value: str) -> date | None:
    match = _DATE_PATTERN.search(value)
    if not match:
        return None
    try:
        return date.fromisoformat(
            f"{match.group('year')}-{_month_number(match.group('month')):02d}-{int(match.group('day')):02d}",
        )
    except ValueError:
        return None


def _month_number(value: str) -> int:
    return (
        "January February March April May June July August September October November December".split().index(
            value.title(),
        )
        + 1
    )


def _format_from_icon(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"icon(?P<format>[a-z0-9]+)\.gif", value, re.IGNORECASE)
    return match.group("format").lower() if match else None


def _content_disposition_filename(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"filename=\"?(?P<filename>[^\";]+)", value, re.IGNORECASE)
    return unescape(match.group("filename").strip()) if match else None


def _join_text(parts: Iterable[str]) -> str:
    return _normalized(" ".join(parts))


def _normalized(value: str | None) -> str:
    return " ".join((value or "").split())


def _remove_part(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
