"""Locate recorded Financial Advisory Board motions in canonical packets."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
import json
from pathlib import Path
import re
from typing import Iterable, Sequence

import pypdfium2 as pdfium

from .models import MotionOutcome, MotionRecord, PacketSource


_FILENAME_DATE_RE = re.compile(r"^(?P<date>\d{4}-\d{2}-\d{2})\b")
_WEEKDAY_DATE_RE = re.compile(
    r"\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+"
    r"(?P<month>January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+(?P<day>\d{1,2}),?\s+(?P<year>\d{4})\b",
    re.IGNORECASE,
)
_CERTIFICATION_DATE_RE = re.compile(
    r"\bmeeting\s+of\s+(?P<month>January|February|March|April|May|June|July|"
    r"August|September|October|November|December)\s+(?P<day>\d{1,2}),?\s+"
    r"(?P<year>\d{4})\b",
    re.IGNORECASE,
)
_FOOTER_DATE_RE = re.compile(
    r"\b(?P<month>\d{1,2})/(?P<day>\d{1,2})/(?P<year>\d{4})\s+Agenda\b",
    re.IGNORECASE,
)
_VOTE_START_RE = re.compile(r"^\s*Ayes\b\s*:?", re.IGNORECASE)
_VOTE_CONTINUATION_RE = re.compile(
    r"^\s*(?:Noes?|Absent|Abstain)\b\s*:?", re.IGNORECASE,
)
_VOTE_LABEL_RE = re.compile(r"\b(?:Ayes|Noes?|Absent|Abstain)\b\s*:?", re.IGNORECASE)
_VOTER_CONTINUATION_RE = re.compile(
    r"^\s*(?:Youth\s+Member|Vice[-\s]+Chair|Chair|Members?|Member)\b",
    re.IGNORECASE,
)
_MOTION_START_RE = re.compile(r"^\s*(?:Motion(?:/Second)?|Moved/Second)\s*:", re.IGNORECASE)
_RECOMMENDATION_RE = re.compile(r"^\s*Recommendation(?:\s+\d+)?\s*:", re.IGNORECASE)
_PROPOSED_RECOMMENDATION_RE = re.compile(
    r"\bproposed\s+the\s+following\s+recommendation\s*:", re.IGNORECASE,
)
_AGENDA_ITEM_RE = re.compile(
    r"^\s*\d{1,2}\.\s+[A-Z][A-Z0-9 \-–/&(),.]+$",
    re.IGNORECASE,
)
_PASS_RE = re.compile(
    r"\bMotion\s+(?:is\s+)?(?:Approved|Passed|Passes|Carried)\b", re.IGNORECASE,
)
_FAIL_RE = re.compile(r"\bMotion\s+(?:Fails?|Failed|Died)\b", re.IGNORECASE)
_NO_SECOND_RE = re.compile(r"\bNo\s+Second\b", re.IGNORECASE)
_NO_ACTION_RE = re.compile(r"\bNo\s+Action\s+Taken\b", re.IGNORECASE)
_PRINTED_PAGE_RE = re.compile(r"^\s*Page\s+\d+\s+of\s+\d+\s*$", re.IGNORECASE)
_ROLE_NAMES_RE = re.compile(
    r"(?:^|[,;]\s*)(?:Youth\s+Member|Vice[-\s]+Chair|Chair|Members?|Member)\s+"
    r"(?P<names>.*?)(?=(?:[,;]\s*)(?:Youth\s+Member|Vice[-\s]+Chair|Chair|"
    r"Members?|Member)\b|$)",
    re.IGNORECASE,
)
_ROUTINE_RE = re.compile(
    r"\b(?:approval|approve|adopt)\b[^.]{0,100}\bminutes\b|"
    r"\badjourn(?:ment)?\b|\bappoint(?:ment)?\b|\belect(?:ion|ed)?\b",
    re.IGNORECASE,
)
_DEFERRAL_RE = re.compile(
    r"\b(?:defer|delay|table|postpone)\b",
    re.IGNORECASE,
)
_MEETING_SCHEDULE_RE = re.compile(
    r"\b(?:FAB\s+)?meeting\s+(?:schedule|calendar)\b|"
    r"\bcalendar\s+year\s+\d{4}\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class _PageLine:
    page: int
    text: str


@dataclass(frozen=True)
class _Decision:
    start: int
    end: int
    vote_start: int | None
    vote_end: int | None
    result_start: int | None
    result_end: int | None
    outcome: MotionOutcome
    ayes: int | None
    noes: int | None


@dataclass(frozen=True)
class _ActionAnchor:
    context_start: int | None
    motion_start: int


@dataclass(frozen=True)
class _LocatedRecord:
    record: MotionRecord
    start: int
    decision_end: int


def scan_minutes_packet(
    packet_path: Path,
    *,
    source_packet_date: date | None = None,
    source_file_id: int | None = None,
    source_url: str | None = None,
    source_sha256: str | None = None,
) -> list[MotionRecord]:
    """Return recorded motion outcomes from one FAB agenda packet."""

    packet_path = Path(packet_path)
    if not packet_path.is_file():
        raise FileNotFoundError(f"PDF not found: {packet_path}")
    source = PacketSource(
        path=packet_path,
        packet_date=source_packet_date or _packet_date_from_name(packet_path),
        file_id=source_file_id,
        source_url=source_url,
        sha256=source_sha256,
    )
    return scan_page_texts(_pdf_page_texts(packet_path), source)


def scan_page_texts(
    page_texts: Sequence[str],
    source: PacketSource,
) -> list[MotionRecord]:
    """Return recorded motion outcomes from already extracted packet page text."""

    lines = _page_lines(page_texts)
    located = _locate_records(lines, source)
    return [item.record for item in _attach_supporting_text(located, lines)]


def iter_fab_packet_sources(originals_dir: Path) -> list[PacketSource]:
    """Return only canonical FAB agenda-packet sources from archive manifests."""

    originals_dir = Path(originals_dir)
    sources: list[PacketSource] = []
    seen_paths: set[Path] = set()
    for manifest_path in sorted(originals_dir.glob("*/manifest.json")):
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        year_dir = manifest_path.parent
        for meeting in data.get("meetings", []):
            current = meeting.get("documents", {}).get("agenda_packet", {}).get("current")
            if not isinstance(current, dict) or not current.get("path"):
                continue
            packet_path = year_dir / current["path"]
            if packet_path in seen_paths:
                continue
            seen_paths.add(packet_path)
            sources.append(
                PacketSource(
                    path=packet_path,
                    packet_date=_parse_iso_date(meeting.get("meeting_date")),
                    file_id=_as_int(current.get("file_id")),
                    source_url=current.get("source_url"),
                    sha256=current.get("sha256"),
                ),
            )
    return sorted(sources, key=lambda source: (source.packet_date or date.max, source.path))


def scan_fab_archive(
    originals_dir: Path,
    *,
    start: date | None = None,
    through: date | None = None,
    successful_only: bool = False,
    exclude_routine: bool = False,
    exclude_procedural: bool = False,
) -> list[MotionRecord]:
    """Scan canonical FAB packets, filtering only after held dates are resolved."""

    records = [
        record
        for source in iter_fab_packet_sources(originals_dir)
        for record in scan_minutes_packet(
            source.path,
            source_packet_date=source.packet_date,
            source_file_id=source.file_id,
            source_url=source.source_url,
            source_sha256=source.sha256,
        )
    ]
    records = deduplicate_motion_records(records)
    return filter_motion_records(
        records,
        start=start,
        through=through,
        successful_only=successful_only,
        exclude_routine=exclude_routine,
        exclude_procedural=exclude_procedural,
    )


def filter_motion_records(
    records: Iterable[MotionRecord],
    *,
    start: date | None = None,
    through: date | None = None,
    successful_only: bool = False,
    exclude_routine: bool = False,
    exclude_procedural: bool = False,
) -> list[MotionRecord]:
    """Filter records using held dates, successful outcomes, and routine labels."""

    filtered: list[MotionRecord] = []
    for record in records:
        if not _matches_held_date(record, start, through):
            continue
        if successful_only and not record.is_successful:
            continue
        if exclude_routine and record.routine:
            continue
        if exclude_procedural and record.procedural:
            continue
        filtered.append(record)
    return filtered


def deduplicate_motion_records(records: Iterable[MotionRecord]) -> list[MotionRecord]:
    """Remove identical minute actions copied into later canonical packets.

    A source packet can include the same approved minutes as a prior packet.
    Keep the earliest canonical packet for a known held date and leave records
    without a resolved held date untouched.
    """

    deduplicated: list[MotionRecord] = []
    seen: set[tuple[date, str, str, str, str, str]] = set()
    indexed_records = enumerate(records)
    ordered_records = (
        record
        for original_index, record in sorted(
            indexed_records,
            key=lambda item: _record_sort_key(item[1], item[0]),
        )
    )
    for record in ordered_records:
        key = _duplicate_key(record)
        if key is not None and key in seen:
            continue
        if key is not None:
            seen.add(key)
        deduplicated.append(record)
    return deduplicated


def _pdf_page_texts(packet_path: Path) -> list[str]:
    document = pdfium.PdfDocument(str(packet_path))
    page_texts: list[str] = []
    try:
        for page_index in range(len(document)):
            page = document.get_page(page_index)
            text_page = page.get_textpage()
            try:
                page_texts.append(text_page.get_text_range(count=-1, force_this=True) or "")
            finally:
                text_page.close()
                page.close()
    finally:
        document.close()
    return page_texts


def _page_lines(page_texts: Sequence[str]) -> list[_PageLine]:
    lines: list[_PageLine] = []
    for page, page_text in enumerate(page_texts, start=1):
        lines.extend(_PageLine(page, line.strip()) for line in page_text.splitlines())
        lines.append(_PageLine(page, ""))
    return lines


def _locate_records(lines: list[_PageLine], source: PacketSource) -> list[_LocatedRecord]:
    located: list[_LocatedRecord] = []
    previous_decision_end = -1
    for decision in _find_decisions(lines):
        action = _find_action_anchor(lines, previous_decision_end + 1, decision.start)
        previous_decision_end = decision.end
        if action is None:
            continue
        located.append(_located_record(lines, source, action, decision))
    return located


def _find_decisions(lines: list[_PageLine]) -> list[_Decision]:
    decisions: list[_Decision] = []
    index = 0
    while index < len(lines):
        if _VOTE_START_RE.match(lines[index].text):
            decision = _decision_from_vote(lines, index)
            decisions.append(decision)
            index = decision.end + 1
            continue
        if _has_disposition(lines[index].text):
            decision = _decision_from_disposition(lines, index)
            decisions.append(decision)
            index = decision.end + 1
            continue
        index += 1
    return decisions


def _decision_from_vote(lines: list[_PageLine], start: int) -> _Decision:
    vote_end = start
    result_start = start if _has_disposition(lines[start].text) else None
    result_end = result_start
    end = start
    index = start + 1
    blank_lines = 0
    while index < len(lines):
        text = lines[index].text
        if not text:
            blank_lines += 1
            if blank_lines <= 1:
                index += 1
                continue
            break
        if _VOTE_CONTINUATION_RE.match(text) or _contains_vote_label(text):
            vote_end = index
            end = index
            if _has_disposition(text):
                result_start = index
                result_end = index
            index += 1
            continue
        if _VOTER_CONTINUATION_RE.match(text):
            vote_end = index
            end = index
            index += 1
            continue
        if _wrapped_vote_line(lines, index):
            vote_end = index
            end = index
            index += 1
            continue
        if _has_disposition(text) and not _MOTION_START_RE.match(text):
            result_start = index
            result_end = index
            end = index
        break
    vote_text = _text_for(lines[start:vote_end + 1])
    result_text = _text_for(lines[result_start:result_end + 1]) if result_start is not None else None
    outcome, ayes, noes = _classify_outcome(vote_text, result_text)
    return _Decision(start, end, start, vote_end, result_start, result_end, outcome, ayes, noes)


def _wrapped_vote_line(lines: list[_PageLine], index: int) -> bool:
    text = lines[index].text
    if not text or _MOTION_START_RE.match(text) or _AGENDA_ITEM_RE.match(text):
        return False
    for candidate in lines[index + 1:index + 6]:
        if not candidate.text:
            continue
        if _contains_vote_label(candidate.text) or _has_disposition(candidate.text):
            return True
        if _MOTION_START_RE.match(candidate.text) or _AGENDA_ITEM_RE.match(candidate.text):
            return False
    return False


def _decision_from_disposition(lines: list[_PageLine], start: int) -> _Decision:
    end = start
    if _NO_SECOND_RE.search(lines[start].text):
        next_index = _next_nonblank_index(lines, start + 1)
        if next_index is not None and _has_disposition(lines[next_index].text):
            end = next_index
    result_text = _text_for(lines[start:end + 1])
    outcome, ayes, noes = _classify_outcome(None, result_text)
    return _Decision(start, end, None, None, start, end, outcome, ayes, noes)


def _find_action_anchor(
    lines: list[_PageLine],
    lower_bound: int,
    decision_start: int,
) -> _ActionAnchor | None:
    recommendation_starts = [
        index
        for index in range(lower_bound, decision_start + 1)
        if _RECOMMENDATION_RE.match(lines[index].text)
        or _PROPOSED_RECOMMENDATION_RE.search(lines[index].text)
    ]
    motion_starts = [
        index
        for index in range(lower_bound, decision_start + 1)
        if _MOTION_START_RE.match(lines[index].text)
    ]
    if not motion_starts and not recommendation_starts:
        return None
    if not motion_starts:
        start = recommendation_starts[-1]
        return _ActionAnchor(None, start)

    motion_start = motion_starts[-1]
    context_start = recommendation_starts[-1] if recommendation_starts else None
    if context_start is not None and context_start > motion_start:
        context_start = None
    if context_start is None and lines[motion_start].text.lower().startswith("moved/second"):
        context_start = _preceding_recommendation_paragraph(lines, lower_bound, motion_start)
    return _ActionAnchor(context_start, motion_start)


def _preceding_recommendation_paragraph(
    lines: list[_PageLine],
    lower_bound: int,
    motion_start: int,
) -> int | None:
    start = motion_start - 1
    while start >= lower_bound and lines[start].text:
        start -= 1
    paragraph_start = start + 1
    paragraph = _text_for(lines[paragraph_start:motion_start])
    if re.search(r"\b(?:recommend|support|adopt)\b", paragraph, re.IGNORECASE):
        return paragraph_start
    return None


def _located_record(
    lines: list[_PageLine],
    source: PacketSource,
    action: _ActionAnchor,
    decision: _Decision,
) -> _LocatedRecord:
    motion_end = decision.start if action.motion_start == decision.start else decision.start - 1
    full_motion_text = _text_for(lines[action.motion_start:motion_end + 1])
    recommendation_text = None
    if action.context_start is not None:
        recommendation_text = _text_for(lines[action.context_start:action.motion_start])
    vote_text = None
    if decision.vote_start is not None and decision.vote_end is not None:
        vote_text = _text_for(lines[decision.vote_start:decision.vote_end + 1])
    result_text = None
    if decision.result_start is not None and decision.result_end is not None:
        result_text = _text_for(lines[decision.result_start:decision.result_end + 1])

    start = action.context_start if action.context_start is not None else action.motion_start
    held_date, held_date_evidence = _held_date(lines, start)
    page_start = lines[start].page
    page_end = lines[decision.end].page
    conflicts = _date_conflicts(lines, page_start, page_end, held_date)
    agenda_item = _agenda_item(lines, start)
    procedural_reason = _procedural_reason(
        agenda_item=agenda_item,
        recommendation_text=recommendation_text,
        full_motion_text=full_motion_text,
    )
    record = MotionRecord(
        source=source,
        held_date=held_date,
        held_date_evidence=held_date_evidence,
        physical_page_start=page_start,
        physical_page_end=page_end,
        agenda_item=agenda_item,
        full_motion_text=full_motion_text,
        recommendation_text=recommendation_text,
        supporting_text=None,
        vote_text=vote_text,
        result_text=result_text,
        outcome=decision.outcome,
        ayes=decision.ayes,
        noes=decision.noes,
        routine=_is_routine_action(
            agenda_item=agenda_item,
            recommendation_text=recommendation_text,
            full_motion_text=full_motion_text,
        ),
        procedural=procedural_reason is not None,
        procedural_reason=procedural_reason,
        date_conflicts=conflicts,
    )
    return _LocatedRecord(record, start, decision.end)


def _attach_supporting_text(
    located: list[_LocatedRecord],
    lines: list[_PageLine],
) -> list[_LocatedRecord]:
    attached: list[_LocatedRecord] = []
    for index, item in enumerate(located):
        next_start = located[index + 1].start if index + 1 < len(located) else len(lines)
        agenda_boundary = _next_agenda_item(lines, item.decision_end + 1, next_start)
        end = agenda_boundary if agenda_boundary is not None else next_start
        supporting_text = _text_for(lines[item.decision_end + 1:end])
        if not _is_supporting_text(supporting_text):
            supporting_text = None
        attached.append(
            _LocatedRecord(
                replace(item.record, supporting_text=supporting_text),
                item.start,
                item.decision_end,
            ),
        )
    return attached


def _next_agenda_item(lines: list[_PageLine], start: int, end: int) -> int | None:
    for index in range(start, end):
        if _AGENDA_ITEM_RE.match(lines[index].text):
            return index
    return None


def _is_supporting_text(text: str) -> bool:
    if len(text) < 20:
        return False
    lowered = text.lower()
    if "future agenda item" in lowered or "adjournment" in lowered:
        return False
    return "recommend" in lowered or "reviewed" in lowered


def _classify_outcome(
    vote_text: str | None,
    result_text: str | None,
) -> tuple[MotionOutcome, int | None, int | None]:
    combined = "\n".join(part for part in (vote_text, result_text) if part)
    if _FAIL_RE.search(combined):
        return MotionOutcome.EXPLICIT_FAILURE, None, None
    if _PASS_RE.search(combined):
        return MotionOutcome.EXPLICIT_PASS, _vote_count(vote_text, "Ayes"), _vote_count(vote_text, "Noes")
    if _NO_SECOND_RE.search(combined) or _NO_ACTION_RE.search(combined):
        return MotionOutcome.NO_DISPOSITION, None, None
    ayes = _vote_count(vote_text, "Ayes")
    noes = _vote_count(vote_text, "Noes")
    if ayes is not None and noes is not None and ayes > noes:
        return MotionOutcome.AFFIRMATIVE_RECORDED_VOTE, ayes, noes
    return MotionOutcome.UNRESOLVED, ayes, noes


def _vote_count(vote_text: str | None, label: str) -> int | None:
    if vote_text is None:
        return None
    field = _vote_field(vote_text, label)
    return _count_named_voters(field) if field is not None else None


def _vote_field(vote_text: str, label: str) -> str | None:
    flattened = " ".join(vote_text.split())
    match = re.search(
        rf"\b{label}\b\s*:?\s*(.*?)(?="
        r"\b(?:Ayes|Noes|Absent|Abstain)\b\s*:?|"
        r"\bMotion\s+(?:is\s+)?(?:Approved|Passed|Passes|Carried|Fails?|Failed|Died)\b|"
        r"\bNo\s+(?:Second|Action\s+Taken)\b|$)",
        flattened,
        re.IGNORECASE,
    )
    return match.group(1).strip() if match else None


def _count_named_voters(value: str) -> int:
    cleaned = value.strip(" .;")
    if not cleaned or re.fullmatch(r"(?:none|no one|n/?a|0)", cleaned, re.IGNORECASE):
        return 0
    role_groups = _ROLE_NAMES_RE.findall(cleaned)
    if role_groups:
        return sum(_count_names(group) for group in role_groups)
    return _count_names(cleaned)


def _count_names(value: str) -> int:
    names = [
        part.strip(" .;")
        for part in re.split(r"\s*(?:,|;|\band\b|&)\s*", value, flags=re.IGNORECASE)
        if part.strip(" .;")
    ]
    return len(names)


def _has_disposition(text: str) -> bool:
    return bool(
        _PASS_RE.search(text)
        or _FAIL_RE.search(text)
        or _NO_SECOND_RE.search(text)
        or _NO_ACTION_RE.search(text)
    )


def _contains_vote_label(text: str) -> bool:
    return bool(_VOTE_LABEL_RE.search(text))


def _next_nonblank_index(lines: list[_PageLine], start: int) -> int | None:
    for index in range(start, len(lines)):
        if lines[index].text:
            return index
    return None


def _held_date(
    lines: list[_PageLine],
    at: int,
) -> tuple[date | None, str]:
    context = _held_date_context(lines, at)
    heading_dates = [
        parsed
        for index, line in enumerate(context)
        if (parsed := _heading_date(context, index, line.text)) is not None
    ]
    if heading_dates:
        return heading_dates[-1], "minutes-heading"
    certification_dates = [
        parsed
        for line in context
        if (parsed := _certification_date(line.text)) is not None
    ]
    if certification_dates:
        return certification_dates[-1], "minutes-certification"
    footer_dates = [
        parsed
        for line in context
        if (parsed := _footer_date(line.text)) is not None
    ]
    if footer_dates:
        return footer_dates[-1], "page-footer"
    return None, "unresolved"


def _held_date_context(lines: list[_PageLine], at: int) -> list[_PageLine]:
    context = lines[:at + 1]
    for index in range(len(context) - 1, -1, -1):
        heading = context[index].text.upper()
        if heading in {
            "MINUTES", "DRAFT MINUTES", "APPROVED MINUTES",
            "AGENDA", "AMENDED AGENDA", "REVISED AGENDA",
        }:
            return context[index:]
    return context


def _heading_date(lines: list[_PageLine], index: int, text: str) -> date | None:
    match = _WEEKDAY_DATE_RE.search(text)
    if not match:
        return None
    context = " ".join(line.text for line in lines[max(0, index - 5):index + 1]).lower()
    if "financial advisory board" not in context or "meeting" not in context:
        return None
    return _written_date(match.group("month"), match.group("day"), match.group("year"))


def _certification_date(text: str) -> date | None:
    match = _CERTIFICATION_DATE_RE.search(text)
    if not match:
        return None
    return _written_date(match.group("month"), match.group("day"), match.group("year"))


def _footer_date(text: str) -> date | None:
    match = _FOOTER_DATE_RE.search(text)
    if not match:
        return None
    return date(int(match.group("year")), int(match.group("month")), int(match.group("day")))


def _written_date(month: str, day: str, year: str) -> date:
    return datetime.strptime(f"{month.title()} {day} {year}", "%B %d %Y").date()


def _date_conflicts(
    lines: list[_PageLine],
    page_start: int,
    page_end: int,
    held_date: date | None,
) -> tuple[str, ...]:
    if held_date is None:
        return ()
    footer_dates = {
        parsed
        for line in lines
        if page_start <= line.page <= page_end
        if (parsed := _footer_date(line.text)) is not None
    }
    return tuple(
        f"footer date {footer_date.isoformat()} conflicts with held date {held_date.isoformat()}"
        for footer_date in sorted(footer_dates)
        if footer_date != held_date
    )


def _agenda_item(lines: list[_PageLine], start: int) -> str | None:
    for index in range(start, -1, -1):
        text = lines[index].text
        if _AGENDA_ITEM_RE.match(text):
            return _text_for([lines[index]])
    return None


def _is_routine_action(
    *,
    agenda_item: str | None,
    recommendation_text: str | None,
    full_motion_text: str,
) -> bool:
    return any(
        _ROUTINE_RE.search(text)
        for text in (agenda_item, recommendation_text, full_motion_text)
        if text
    )


def _procedural_reason(
    *,
    agenda_item: str | None,
    recommendation_text: str | None,
    full_motion_text: str,
) -> str | None:
    text = " ".join(
        part
        for part in (agenda_item, recommendation_text, full_motion_text)
        if part
    )
    if _DEFERRAL_RE.search(text):
        return "deferral"
    if agenda_item and _MEETING_SCHEDULE_RE.search(agenda_item):
        return "meeting-schedule"
    return None


def _text_for(lines: Sequence[_PageLine]) -> str:
    return " ".join(
        line.text
        for line in lines
        if line.text and not _is_page_noise(line.text)
    )


def _is_page_noise(text: str) -> bool:
    if _PRINTED_PAGE_RE.match(text) or _FOOTER_DATE_RE.search(text):
        return True
    lowered = text.lower()
    if lowered in {"financial advisory board", "financial advisory board (fab)"}:
        return True
    return lowered.startswith("financial advisory board (fab)") and "agenda" in lowered


def _packet_date_from_name(path: Path) -> date | None:
    match = _FILENAME_DATE_RE.match(path.name)
    return _parse_iso_date(match.group("date")) if match else None


def _parse_iso_date(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _as_int(value: object) -> int | None:
    return value if isinstance(value, int) else None


def _record_sort_key(
    record: MotionRecord,
    original_index: int,
) -> tuple[date, date, str, int, int]:
    return (
        record.held_date or date.max,
        record.source.packet_date or date.max,
        str(record.source.path),
        record.physical_page_start,
        original_index,
    )


def _duplicate_key(
    record: MotionRecord,
) -> tuple[date, str, str, str, str, str] | None:
    if record.held_date is None:
        return None
    return (
        record.held_date,
        _normalized_text(record.agenda_item),
        _normalized_text(record.recommendation_text),
        _normalized_text(record.full_motion_text),
        _normalized_text(record.vote_text),
        _normalized_text(record.result_text),
    )


def _normalized_text(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"[^\w]+", " ", value.casefold()).strip()


def _matches_held_date(
    record: MotionRecord,
    start: date | None,
    through: date | None,
) -> bool:
    if start is None and through is None:
        return True
    if record.held_date is None:
        return False
    if start is not None and record.held_date < start:
        return False
    return through is None or record.held_date <= through
