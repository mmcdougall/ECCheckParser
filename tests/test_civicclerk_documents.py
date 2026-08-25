from __future__ import annotations

from datetime import date
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from check_register.civicclerk import (
    CivicClerkDocument,
    document_cache_filename,
    document_cache_path,
    download_document,
    fetch_meetings,
    meeting_file_stream_url,
    parse_meeting,
    published_documents,
    select_current_meeting,
    select_document,
)
from check_register.civicclerk_archive import archive_document, load_manifest, manifest_path
from civicclerk_documents import _document_kinds, _meetings_for_cache_args, parse_args


class TestCivicClerkDocuments(unittest.TestCase):
    def test_published_documents_selects_agenda_and_latest_packet(self):
        meeting = parse_meeting(_event())

        documents = published_documents(meeting)
        agenda = select_document(documents, "agenda")
        packet = select_document(documents, "agenda-packet")

        self.assertIsNotNone(agenda)
        self.assertIsNotNone(packet)
        self.assertEqual(agenda.name, "Agenda")
        self.assertEqual(packet.file_id, 3406)
        self.assertEqual(packet.name, "Agenda Packet (rev. 6.10.2026)")

    def test_published_documents_synthesizes_stream_url_from_file_id(self):
        meeting = parse_meeting(
            {
                **_event(),
                "publishedFiles": [
                    {
                        "fileId": 3391,
                        "type": "Agenda Packet",
                        "name": "Agenda Packet (rev. 6.3.2026)",
                        "publishOn": "2026-06-03T14:32:27.787Z",
                        "fileType": 2,
                        "url": "stream/ELCERRITOCA/12615bfa-481e-482b-821c-badc1321c05e.pdf",
                        "streamUrl": None,
                    },
                ],
            },
            city_code="elcerritoca",
        )

        packet = select_document(published_documents(meeting), "agenda_packet")

        self.assertIsNotNone(packet)
        self.assertEqual(packet.stream_url, meeting_file_stream_url("elcerritoca", 3391))

    def test_document_cache_filename_uses_compact_canonical_name(self):
        meeting = parse_meeting(_event())
        packet = select_document(published_documents(meeting), "agenda_packet")
        assert packet is not None

        self.assertEqual(
            document_cache_filename(meeting, packet),
            "2026-06-09 Agenda Packet.pdf",
        )

    def test_document_cache_path_separates_agendas(self):
        meeting = parse_meeting(_event())
        agenda = select_document(published_documents(meeting), "agenda")
        assert agenda is not None

        self.assertEqual(
            document_cache_filename(meeting, agenda),
            "2026-06-09 Agenda.pdf",
        )
        self.assertEqual(
            document_cache_path(meeting, agenda, originals_dir=Path("data/originals")),
            Path("data/originals/city-council/2026/agendas/2026-06-09 Agenda.pdf"),
        )

    def test_document_cache_path_separates_packets(self):
        meeting = parse_meeting(_event())
        packet = select_document(published_documents(meeting), "agenda_packet")
        assert packet is not None

        self.assertEqual(
            document_cache_path(meeting, packet, originals_dir=Path("data/originals")),
            Path("data/originals/city-council/2026/agenda-packets/2026-06-09 Agenda Packet.pdf"),
        )

    def test_generic_packet_name_does_not_change_canonical_filename(self):
        meeting = parse_meeting(_event())
        packet = CivicClerkDocument(
            file_id=1,
            kind="agenda_packet",
            name="Packet",
            stream_url="https://example.test/packet.pdf",
            publish_on="2026-07-02T15:57:51.433Z",
        )

        self.assertEqual(
            document_cache_filename(meeting, packet),
            "2026-06-09 Agenda Packet.pdf",
        )

    def test_missing_publish_date_does_not_change_canonical_filename(self):
        meeting = parse_meeting(_event())
        packet = CivicClerkDocument(
            file_id=1,
            kind="agenda_packet",
            name="Packet",
            stream_url="https://example.test/packet.pdf",
        )

        self.assertEqual(
            document_cache_filename(meeting, packet),
            "2026-06-09 Agenda Packet.pdf",
        )

    def test_archive_document_preserves_revised_packet_and_updates_manifest(self):
        meeting = parse_meeting(_event())
        original = CivicClerkDocument(
            file_id=3406,
            kind="agenda_packet",
            name="Agenda Packet (rev. 6.10.2026)",
            stream_url="https://example.test/original.pdf",
            publish_on="2026-06-10T13:53:08.443Z",
        )
        revised = CivicClerkDocument(
            file_id=3410,
            kind="agenda_packet",
            name="Agenda Packet (rev. 6.11.2026)",
            stream_url="https://example.test/revised.pdf",
            publish_on="2026-06-11T09:20:00Z",
        )

        with tempfile.TemporaryDirectory() as td:
            originals_dir = Path(td)
            with patch("check_register.civicclerk.urlopen", return_value=_FakeResponse(b"first packet")):
                first = archive_document(meeting, original, originals_dir=originals_dir)
            with patch("check_register.civicclerk.urlopen", return_value=_FakeResponse(b"second packet")):
                second = archive_document(meeting, revised, originals_dir=originals_dir)

            canonical = originals_dir / "city-council/2026/agenda-packets/2026-06-09 Agenda Packet.pdf"
            revision = originals_dir / "city-council/2026/agenda-packet-revisions/2026-06-09 Agenda Packet - 2026-06-10.pdf"
            self.assertEqual(first.action, "downloaded")
            self.assertEqual(second.action, "revised")
            self.assertEqual(second.revision_path, revision)
            self.assertEqual(canonical.read_bytes(), b"second packet")
            self.assertEqual(revision.read_bytes(), b"first packet")

            manifest = load_manifest(
                manifest_path(originals_dir, "city-council", 2026),
                year=2026,
            )
            state = manifest["meetings"][0]["documents"]["agenda_packet"]
            self.assertEqual(state["current"]["file_id"], 3410)
            self.assertEqual(state["revisions"][0]["file_id"], 3406)

    def test_archive_document_separates_meeting_types(self):
        city_council = parse_meeting(_event())
        financial_advisory_board = parse_meeting(
            {
                **_event(),
                "id": 1374,
                "eventName": "Financial Advisory Board Regular Meeting",
                "categoryName": "Financial Advisory Board",
            },
        )
        packet = CivicClerkDocument(
            file_id=1,
            kind="agenda_packet",
            name="Agenda Packet",
            stream_url="https://example.test/packet.pdf",
            publish_on="2026-06-10T13:53:08.443Z",
        )

        with tempfile.TemporaryDirectory() as td:
            originals_dir = Path(td)
            with patch(
                "check_register.civicclerk.urlopen",
                side_effect=[_FakeResponse(b"city"), _FakeResponse(b"fab")],
            ):
                city_document = archive_document(city_council, packet, originals_dir=originals_dir)
                fab_document = archive_document(financial_advisory_board, packet, originals_dir=originals_dir)

            self.assertEqual(
                city_document.path,
                originals_dir / "city-council/2026/agenda-packets/2026-06-09 Agenda Packet.pdf",
            )
            self.assertEqual(
                fab_document.path,
                originals_dir / "financial-advisory-board/2026/agenda-packets/2026-06-09 Agenda Packet.pdf",
            )
            self.assertTrue(manifest_path(originals_dir, "city-council", 2026).exists())
            self.assertTrue(manifest_path(originals_dir, "financial-advisory-board", 2026).exists())

    def test_document_cache_path_rejects_unknown_category(self):
        meeting = parse_meeting({**_event(), "categoryName": "Parks and Recreation"})
        packet = select_document(published_documents(meeting), "agenda_packet")
        assert packet is not None

        with self.assertRaisesRegex(ValueError, "Unsupported CivicClerk meeting category"):
            document_cache_path(meeting, packet, originals_dir=Path("data/originals"))

    def test_archive_document_skips_unchanged_remote_identity(self):
        meeting = parse_meeting(_event())
        packet = select_document(published_documents(meeting), "agenda_packet")
        assert packet is not None

        with tempfile.TemporaryDirectory() as td:
            originals_dir = Path(td)
            with patch("check_register.civicclerk.urlopen", return_value=_FakeResponse(b"packet")):
                archive_document(meeting, packet, originals_dir=originals_dir)
            with patch("check_register.civicclerk.urlopen") as urlopen:
                result = archive_document(meeting, packet, originals_dir=originals_dir)

            self.assertEqual(result.action, "unchanged")
            urlopen.assert_not_called()

    def test_archive_document_adds_meeting_time_only_for_real_collision(self):
        first_meeting = parse_meeting({**_event(), "id": 1})
        second_meeting = parse_meeting(
            {**_event(), "id": 2, "eventDate": "2026-06-09T19:30:00Z"},
        )
        first_packet = CivicClerkDocument(
            file_id=1,
            kind="agenda_packet",
            name="Packet",
            stream_url="https://example.test/one.pdf",
            publish_on="2026-06-04T12:00:00Z",
        )
        second_packet = CivicClerkDocument(
            file_id=2,
            kind="agenda_packet",
            name="Packet",
            stream_url="https://example.test/two.pdf",
            publish_on="2026-06-05T12:00:00Z",
        )

        with tempfile.TemporaryDirectory() as td:
            originals_dir = Path(td)
            with patch("check_register.civicclerk.urlopen", return_value=_FakeResponse(b"one")):
                archive_document(first_meeting, first_packet, originals_dir=originals_dir)
            with patch("check_register.civicclerk.urlopen", return_value=_FakeResponse(b"two")):
                result = archive_document(second_meeting, second_packet, originals_dir=originals_dir)

            self.assertEqual(
                result.path.name,
                "2026-06-09 1930 Agenda Packet.pdf",
            )

    def test_select_current_meeting_prefers_next_upcoming_with_documents(self):
        past = parse_meeting({**_event(), "id": 1, "eventDate": "2026-06-01T18:00:00Z"})
        upcoming = parse_meeting({**_event(), "id": 2, "eventDate": "2026-07-07T18:00:00Z"})
        later = parse_meeting({**_event(), "id": 3, "eventDate": "2026-07-14T18:00:00Z"})

        selected = select_current_meeting([later, past, upcoming], today=date(2026, 7, 6))

        self.assertEqual(selected, upcoming)

    def test_select_current_meeting_falls_back_to_latest_past(self):
        older = parse_meeting({**_event(), "id": 1, "eventDate": "2026-06-01T18:00:00Z"})
        newer = parse_meeting({**_event(), "id": 2, "eventDate": "2026-06-15T18:00:00Z"})

        selected = select_current_meeting([older, newer], today=date(2026, 7, 6))

        self.assertEqual(selected, newer)

    def test_fetch_meetings_filters_and_follows_next_link(self):
        seen_urls = []

        def fake_fetch(url: str, *, timeout: float):
            seen_urls.append(url)
            if len(seen_urls) == 1:
                return {
                    "value": [_event()],
                    "@odata.nextLink": "https://example.test/next",
                }
            return {
                "value": [{**_event(), "id": 1400, "eventDate": "2026-06-16T18:00:00Z"}],
            }

        with patch("check_register.civicclerk._fetch_json", side_effect=fake_fetch):
            meetings = fetch_meetings(
                "elcerritoca",
                start=date(2026, 6, 1),
                end=date(2026, 7, 1),
            )

        self.assertEqual([meeting.id for meeting in meetings], [1373, 1400])
        self.assertIn("%24filter=", seen_urls[0])
        self.assertIn("categoryName+eq+%27City+Council%27", seen_urls[0])
        self.assertEqual(seen_urls[1], "https://example.test/next")

    def test_download_document_writes_response_bytes(self):
        document = CivicClerkDocument(
            file_id=1,
            kind="agenda",
            name="Agenda",
            stream_url="https://example.test/agenda.pdf",
        )

        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "agenda.pdf"
            with patch("check_register.civicclerk.urlopen", return_value=_FakeResponse(b"pdf bytes")):
                cached = download_document(document, out)

            self.assertEqual(out.read_bytes(), b"pdf bytes")
            self.assertEqual(cached.bytes_written, 9)
            self.assertFalse((Path(td) / "agenda.pdf.part").exists())

    def test_cli_current_defaults_to_packet_cache(self):
        args = parse_args(["current", "--dry-run"])

        self.assertEqual(args.command, "current")
        self.assertTrue(args.dry_run)
        self.assertIsNone(args.document)
        self.assertEqual(_document_kinds(args), ("agenda_packet",))

    def test_cache_event_only_does_not_require_date_window(self):
        args = parse_args(["cache", "--event", "1373", "--dry-run"])
        meeting = parse_meeting(_event())

        with patch("civicclerk_documents.fetch_meeting", return_value=meeting):
            meetings = _meetings_for_cache_args(args)

        self.assertEqual(meetings, [meeting])


class _FakeResponse:
    def __init__(self, payload: bytes):
        self._payload = payload
        self._offset = 0
        self.headers = {"content-type": "application/pdf"}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, size: int = -1) -> bytes:
        if self._offset >= len(self._payload):
            return b""
        if size < 0:
            size = len(self._payload) - self._offset
        chunk = self._payload[self._offset:self._offset + size]
        self._offset += len(chunk)
        return chunk


def _event() -> dict:
    return {
        "id": 1373,
        "eventName": "Special City Council Meeting",
        "eventDate": "2026-06-09T18:15:00Z",
        "categoryName": "City Council",
        "eventLocation": {"city": "El Cerrito"},
        "publishedFiles": [
            {
                "fileId": 3395,
                "type": "Agenda",
                "name": "Agenda",
                "publishOn": "2026-06-04T15:10:21.48Z",
                "fileType": 1,
                "streamUrl": "https://elcerritoca.api.civicclerk.com/v1/Meetings/GetMeetingFileStream(fileId=3395,plainText=false)",
            },
            {
                "fileId": 3401,
                "type": "Agenda Packet",
                "name": "Agenda Packet (rev. 6.8.2026)",
                "publishOn": "2026-06-08T13:53:08.443Z",
                "fileType": 2,
                "streamUrl": "https://elcerritoca.api.civicclerk.com/v1/Meetings/GetMeetingFileStream(fileId=3401,plainText=false)",
            },
            {
                "fileId": 3406,
                "type": "Agenda Packet",
                "name": "Agenda Packet (rev. 6.10.2026)",
                "publishOn": "2026-06-10T13:53:08.443Z",
                "fileType": 2,
                "streamUrl": "https://elcerritoca.api.civicclerk.com/v1/Meetings/GetMeetingFileStream(fileId=3406,plainText=false)",
            },
        ],
    }


if __name__ == "__main__":
    unittest.main()
