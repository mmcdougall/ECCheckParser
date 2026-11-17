from __future__ import annotations

import contextlib
from datetime import date
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from archivecenter_documents import cache_plan, main, parse_args
from check_register.archivecenter import (
    ArchiveCenterDocument,
    ArchiveCenterError,
    archive_document_url,
    fetch_documents,
    parse_archive_index,
)
from check_register.archivecenter_archive import archive_document as archive_archivecenter_document
from check_register.civicclerk import CivicClerkDocument, parse_meeting
from check_register.civicclerk_archive import archive_document as archive_civicclerk_document
from check_register.civicclerk_archive import load_manifest, manifest_path
from check_register.originals_audit import audit_originals


class TestArchiveCenterDocuments(unittest.TestCase):
    def test_fetch_documents_uses_the_selected_indexes(self):
        with patch('check_register.archivecenter._fetch_text', return_value=_INDEX_HTML) as fetch:
            documents = fetch_documents({'minutes': 700, 'report': 701}, timeout=12)

        self.assertEqual([call.args[0] for call in fetch.call_args_list], [
            'https://www.elcerrito.gov/Archive.aspx?AMID=700',
            'https://www.elcerrito.gov/Archive.aspx?AMID=701',
        ])
        self.assertEqual({document.kind for document in documents}, {'minutes', 'report'})
        self.assertEqual(len(documents), 4)

    def test_generic_packet_does_not_require_an_agenda(self):
        packet = _document(8128, 'agenda_packet', date(2025, 12, 18))
        plan = cache_plan([packet], document_kinds=('agenda_packet',))
        self.assertEqual(plan.documents, [packet])
        self.assertEqual(plan.skipped, [])

    def test_fiscal_year_listing_does_not_invent_a_source_date(self):
        documents = parse_archive_index(
            _INDEX_HTML.replace('December 18, 2025', 'FY 2025/2026 - 2026/2027 Workplan'),
            kind='work_plan', listing_url='https://www.elcerrito.gov/Archive.aspx?AMID=146',
        )
        self.assertIsNone(documents[0].listing_date)
        plan = cache_plan(documents[:1], document_kinds=('work_plan',))
        self.assertEqual(plan.documents, [])
        self.assertIn('no parseable listing date', plan.skipped[0])

    def test_ambiguous_agendas_do_not_block_a_work_plan(self):
        documents = [_document(i, kind, date(2025, 12, 18)) for i, kind in [
            (100, 'agenda'), (101, 'agenda'), (102, 'work_plan'), (103, 'agenda_packet'),
        ]]
        plan = cache_plan(
            documents, document_kinds=('agenda', 'work_plan', 'agenda_packet'),
            require_matching_agenda=True,
        )
        self.assertEqual([document.archive_id for document in plan.documents], [102])
        self.assertEqual(len(plan.skipped), 2)

    def test_additional_document_kinds_preserve_revisions_and_pass_audit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            originals_dir = Path(tmpdir)
            for index, (kind, directory, label) in enumerate([
                ('minutes', 'minutes', 'Minutes'),
                ('work_plan', 'work-plans', 'Work Plan'),
                ('report', 'reports', 'Report'),
            ]):
                with self.subTest(kind=kind):
                    for version in (0, 1):
                        document = _document(100 + index * 2 + version, kind, date(2025, 12, 18))
                        with patch('check_register.archivecenter.urlopen', return_value=_FakeResponse(
                            f'%PDF-1.7\n{kind} {version}'.encode(),
                        )):
                            archived = archive_archivecenter_document(
                                document, originals_dir=originals_dir, meeting_type='planning-commission',
                            )
                    self.assertEqual(archived.action, 'revised')
                    self.assertEqual(archived.path, originals_dir / 'planning-commission' / '2025' /
                                     directory / f'2025-12-18 {label}.pdf')
                    self.assertEqual(archived.revision_path.read_bytes(), f'%PDF-1.7\n{kind} 0'.encode())
                    self.assertEqual(archived.path.read_bytes(), f'%PDF-1.7\n{kind} 1'.encode())
            audit = audit_originals(originals_dir)
            self.assertEqual(audit.problems, [])
            self.assertEqual(audit.record_counts, {'planning-commission': 6})

    def test_archive_destinations_are_isolated(self):
        document = _document(8127, 'agenda', date(2025, 12, 18))
        with tempfile.TemporaryDirectory() as tmpdir:
            originals_dir = Path(tmpdir)
            for meeting_type in ('city-council', 'subdivision-committee'):
                with patch('check_register.archivecenter.urlopen', return_value=_FakeResponse(b'%PDF-1.7\nagenda')):
                    archived = archive_archivecenter_document(
                        document, originals_dir=originals_dir, meeting_type=meeting_type,
                    )
                self.assertEqual(archived.action, 'downloaded')
                manifest = load_manifest(manifest_path(originals_dir, meeting_type, 2025), year=2025)
                self.assertEqual(manifest['meetings'][0]['title'], meeting_type.replace('-', ' ').title())
            self.assertFalse((originals_dir / 'financial-advisory-board').exists())
            self.assertEqual(audit_originals(originals_dir).problems, [])

    def test_archive_rejects_invalid_destination_before_writing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('check_register.archivecenter.urlopen') as fetch:
                for meeting_type in ('../outside', '/tmp/outside', 'city/council', '2026', 'City Council'):
                    with self.subTest(meeting_type=meeting_type), self.assertRaises(ValueError):
                        archive_archivecenter_document(
                            _document(1, 'agenda', date(2025, 12, 18)),
                            originals_dir=Path(tmpdir), meeting_type=meeting_type,
                        )
                fetch.assert_not_called()
                self.assertEqual(list(Path(tmpdir).iterdir()), [])

    def test_cli_custom_index_caches_in_the_selected_category(self):
        document = _document(9001, 'work_plan', date(2025, 12, 18))
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('archivecenter_documents.fetch_documents', return_value=[document]) as fetch:
                with patch('check_register.archivecenter.urlopen', return_value=_FakeResponse(b'%PDF-1.7\nplan')):
                    with contextlib.redirect_stdout(io.StringIO()):
                        main(['cache', '--date', '2025-12-18', '--index', 'work-plan=700',
                              '--meeting-type', 'urban-forest-committee', '--originals-dir', tmpdir])
            fetch.assert_called_once_with({'work_plan': 700}, timeout=30.0)
            self.assertTrue((Path(tmpdir) / 'urban-forest-committee/2025/work-plans/2025-12-18 Work Plan.pdf').is_file())
            self.assertFalse((Path(tmpdir) / 'financial-advisory-board').exists())

    def test_cli_rejects_incomplete_or_conflicting_index_selection_before_fetching(self):
        selections = [
            ['--index', 'work-plan=700'],
            ['--meeting-type', 'city-council'],
            ['--meeting-type', 'city-council', '--index', 'agenda=700', '--index', 'agenda=701'],
            ['--meeting-type', 'city-council', '--index', 'agenda=700', '--document', 'report'],
            ['--document', 'work-plan'],
        ]
        with patch('archivecenter_documents.fetch_documents') as fetch:
            for selection in selections:
                with self.subTest(selection=selection), contextlib.redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit):
                        main(['cache', '--year', '2025', *selection])
            fetch.assert_not_called()

    def test_parse_archive_index_reads_archive_details_and_punctuation_dates(self):
        documents = parse_archive_index(
            _INDEX_HTML,
            kind="agenda",
            listing_url="https://www.elcerrito.gov/Archive.aspx?AMID=62",
        )

        self.assertEqual([document.archive_id for document in documents], [8127, 7623])
        self.assertEqual(documents[0].listing_date, date(2025, 12, 18))
        self.assertEqual(documents[0].document_format, "pdf")
        self.assertEqual(
            documents[0].listing_url,
            "https://www.elcerrito.gov/Archive.aspx?ADID=8127",
        )
        self.assertEqual(documents[1].listing_date, date(2024, 6, 25))
        self.assertEqual(documents[1].listing_description, "Special meeting")

    def test_cache_plan_uses_only_unambiguous_pdf_packets_with_an_agenda(self):
        agenda = _document(8127, "agenda", date(2025, 12, 18))
        packet = _document(8128, "agenda_packet", date(2025, 12, 18))
        cancellation = _document(8102, "agenda", date(2025, 11, 20))
        mislabeled_packet = _document(7847, "agenda_packet", date(2024, 1, 28))
        word_packet = _document(7624, "agenda_packet", date(2024, 6, 25), document_format="word")

        plan = cache_plan(
            [agenda, packet, cancellation, mislabeled_packet, word_packet],
            document_kinds=("agenda", "agenda_packet"),
            require_matching_agenda=True,
        )

        self.assertEqual([document.archive_id for document in plan.documents], [8102, 8127, 8128])
        self.assertTrue(any("7847" in message and "no matching indexed agenda" in message for message in plan.skipped))
        self.assertTrue(any("7624" in message and "not PDF" in message for message in plan.skipped))

    def test_archive_document_installs_missing_document_with_archivecenter_provenance(self):
        document = _document(8127, "agenda", date(2025, 12, 18))

        with tempfile.TemporaryDirectory() as tmpdir:
            originals_dir = Path(tmpdir) / "originals"
            with patch(
                "check_register.archivecenter.urlopen",
                return_value=_FakeResponse(b"%PDF-1.7\nagenda", filename="FAB 12 18 25 Agenda.pdf"),
            ):
                archived = archive_archivecenter_document(document, originals_dir=originals_dir, meeting_type="financial-advisory-board")

            self.assertEqual(archived.action, "downloaded")
            self.assertEqual(
                archived.path,
                originals_dir / "financial-advisory-board/2025/agendas/2025-12-18 Agenda.pdf",
            )
            self.assertEqual(archived.path.read_bytes(), b"%PDF-1.7\nagenda")
            manifest = load_manifest(
                manifest_path(originals_dir, "financial-advisory-board", 2025),
                year=2025,
            )
            current = manifest["meetings"][0]["documents"]["agenda"]["current"]
            self.assertIsNone(current["file_id"])
            self.assertEqual(current["source_system"], "archivecenter")
            self.assertEqual(current["archive_id"], 8127)
            self.assertEqual(current["listing_date"], "2025-12-18")
            self.assertEqual(current["source_url"], archive_document_url(8127))

    def test_archive_document_reuses_archive_id_without_a_second_download(self):
        document = _document(8127, "agenda", date(2025, 12, 18))

        with tempfile.TemporaryDirectory() as tmpdir:
            originals_dir = Path(tmpdir) / "originals"
            with patch(
                "check_register.archivecenter.urlopen",
                return_value=_FakeResponse(b"%PDF-1.7\nagenda", filename="FAB 12 18 25 Agenda.pdf"),
            ):
                archive_archivecenter_document(document, originals_dir=originals_dir, meeting_type="financial-advisory-board")
            with patch("check_register.archivecenter.urlopen") as urlopen:
                archived = archive_archivecenter_document(document, originals_dir=originals_dir, meeting_type="financial-advisory-board")

            self.assertEqual(archived.action, "unchanged")
            urlopen.assert_not_called()

    def test_archive_document_revises_a_changed_archivecenter_item(self):
        original = _document(8127, "agenda", date(2025, 12, 18))
        replacement = _document(9000, "agenda", date(2025, 12, 18))

        with tempfile.TemporaryDirectory() as tmpdir:
            originals_dir = Path(tmpdir) / "originals"
            with patch(
                "check_register.archivecenter.urlopen",
                return_value=_FakeResponse(b"%PDF-1.7\nfirst", filename="FAB 12 18 25 Agenda.pdf"),
            ):
                archive_archivecenter_document(original, originals_dir=originals_dir, meeting_type="financial-advisory-board")
            with patch(
                "check_register.archivecenter.urlopen",
                return_value=_FakeResponse(b"%PDF-1.7\nsecond", filename="FAB 12 18 25 Agenda.pdf"),
            ):
                archived = archive_archivecenter_document(replacement, originals_dir=originals_dir, meeting_type="financial-advisory-board")

            self.assertEqual(archived.action, "revised")
            self.assertEqual(
                archived.revision_path,
                originals_dir
                / "financial-advisory-board/2025/agenda-revisions/"
                "2025-12-18 Agenda - ArchiveCenter 8127.pdf",
            )
            manifest = load_manifest(
                manifest_path(originals_dir, "financial-advisory-board", 2025),
                year=2025,
            )
            state = manifest["meetings"][0]["documents"]["agenda"]
            self.assertEqual(state["current"]["archive_id"], 9000)
            self.assertEqual(state["revisions"][0]["archive_id"], 8127)

    def test_archive_document_restores_a_missing_current_copy(self):
        document = _document(8127, "agenda", date(2025, 12, 18))
        with tempfile.TemporaryDirectory() as tmpdir:
            originals_dir = Path(tmpdir) / "originals"
            for attempt in range(2):
                with patch("check_register.archivecenter.urlopen", return_value=_FakeResponse(b"%PDF-1.7\nagenda")):
                    archived = archive_archivecenter_document(
                        document, originals_dir=originals_dir, meeting_type="financial-advisory-board",
                    )
                self.assertEqual(archived.action, "downloaded")
                self.assertEqual(archived.path.read_bytes(), b"%PDF-1.7\nagenda")
                if attempt == 0:
                    archived.path.unlink()
            self.assertEqual(audit_originals(originals_dir).problems, [])

    def test_archive_document_restores_a_missing_revision_without_replacing_current(self):
        original = _document(8127, "agenda", date(2025, 12, 18))
        replacement = _document(9000, "agenda", date(2025, 12, 18))
        with tempfile.TemporaryDirectory() as tmpdir:
            originals_dir = Path(tmpdir) / "originals"
            for document, payload in [(original, b"%PDF-1.7\nfirst"), (replacement, b"%PDF-1.7\nsecond")]:
                with patch("check_register.archivecenter.urlopen", return_value=_FakeResponse(payload)):
                    current = archive_archivecenter_document(
                        document, originals_dir=originals_dir, meeting_type="financial-advisory-board",
                    )
            revision_path = current.revision_path
            revision_path.unlink()
            with patch("check_register.archivecenter.urlopen", return_value=_FakeResponse(b"%PDF-1.7\nfirst")):
                restored = archive_archivecenter_document(
                    original, originals_dir=originals_dir, meeting_type="financial-advisory-board",
                )
            self.assertEqual(restored.action, "downloaded")
            self.assertEqual(restored.path, revision_path)
            self.assertEqual(restored.path.read_bytes(), b"%PDF-1.7\nfirst")
            self.assertEqual(current.path.read_bytes(), b"%PDF-1.7\nsecond")
            self.assertEqual(audit_originals(originals_dir).problems, [])

    def test_missing_known_copy_dry_run_does_not_download_or_write(self):
        document = _document(8127, "agenda", date(2025, 12, 18))
        with tempfile.TemporaryDirectory() as tmpdir:
            originals_dir = Path(tmpdir) / "originals"
            with patch("check_register.archivecenter.urlopen", return_value=_FakeResponse(b"%PDF-1.7\nagenda")):
                archived = archive_archivecenter_document(
                    document, originals_dir=originals_dir, meeting_type="financial-advisory-board",
                )
            archived.path.unlink()
            manifest_file = manifest_path(originals_dir, "financial-advisory-board", 2025)
            before = manifest_file.read_bytes()
            with patch("check_register.archivecenter.urlopen") as fetch:
                planned = archive_archivecenter_document(
                    document, originals_dir=originals_dir, meeting_type="financial-advisory-board", dry_run=True,
                )
            self.assertEqual(planned.action, "download")
            self.assertFalse(planned.path.exists())
            self.assertEqual(manifest_file.read_bytes(), before)
            fetch.assert_not_called()

    def test_equivalent_source_restores_missing_civicclerk_copy_and_provenance(self):
        document = _document(8127, "agenda", date(2025, 12, 18))
        with tempfile.TemporaryDirectory() as tmpdir:
            originals_dir = Path(tmpdir) / "originals"
            year_dir = originals_dir / "financial-advisory-board/2025"
            canonical = year_dir / "agendas/2025-12-18 Agenda.pdf"
            canonical.parent.mkdir(parents=True)
            canonical.write_bytes(b"%PDF-1.7\nagenda")
            _write_manifest(year_dir, {
                "meeting_date": "2025-12-18", "documents": {
                    "agenda": {"current": _civic_record(canonical, year_dir), "revisions": []},
                },
            })
            for attempt in range(2):
                with patch("check_register.archivecenter.urlopen", return_value=_FakeResponse(b"%PDF-1.7\nagenda")):
                    archived = archive_archivecenter_document(
                        document, originals_dir=originals_dir, meeting_type="financial-advisory-board",
                        include_variants=True,
                    )
                if attempt == 0:
                    self.assertEqual(archived.action, "identical-to-current")
                    canonical.unlink()
            self.assertEqual(archived.action, "downloaded")
            self.assertEqual(archived.path, canonical)
            self.assertEqual(canonical.read_bytes(), b"%PDF-1.7\nagenda")
            state = json.loads((year_dir / "manifest.json").read_text())["meetings"][0]["documents"]["agenda"]
            self.assertEqual(state["current"]["file_id"], 100)
            self.assertEqual(state["revisions"], [])
            self.assertEqual(len(state["equivalent_sources"]), 1)
            self.assertEqual(audit_originals(originals_dir).problems, [])

    def test_missing_known_copy_rejects_bytes_that_differ_from_the_manifest(self):
        document = _document(8127, "agenda", date(2025, 12, 18))
        with tempfile.TemporaryDirectory() as tmpdir:
            originals_dir = Path(tmpdir) / "originals"
            with patch("check_register.archivecenter.urlopen", return_value=_FakeResponse(b"%PDF-1.7\nagenda")):
                archived = archive_archivecenter_document(
                    document, originals_dir=originals_dir, meeting_type="financial-advisory-board",
                )
            archived.path.unlink()
            manifest_file = manifest_path(originals_dir, "financial-advisory-board", 2025)
            before = manifest_file.read_bytes()
            with patch("check_register.archivecenter.urlopen", return_value=_FakeResponse(b"%PDF-1.7\nchanged")):
                with self.assertRaisesRegex(ArchiveCenterError, "downloaded SHA-256 differs"):
                    archive_archivecenter_document(
                        document, originals_dir=originals_dir, meeting_type="financial-advisory-board",
                    )
            self.assertFalse(archived.path.exists())
            self.assertEqual(manifest_file.read_bytes(), before)
            self.assertFalse(list(originals_dir.rglob("*.download")))

    def test_archive_document_normalizes_legacy_archive_id_stored_as_file_id(self):
        document = _document(8186, "agenda", date(2026, 3, 24))
        with tempfile.TemporaryDirectory() as tmpdir:
            originals_dir = Path(tmpdir) / "originals"
            year_dir = originals_dir / "financial-advisory-board/2026"
            revision_path = year_dir / "agenda-revisions/2026-03-24 Agenda - ArchiveCenter 8186.pdf"
            revision_path.parent.mkdir(parents=True)
            revision_path.write_bytes(b"%PDF-1.7\nlegacy")
            canonical_path = year_dir / "agendas/2026-03-24 Agenda.pdf"
            canonical_path.parent.mkdir(parents=True)
            canonical_path.write_bytes(b"%PDF-1.7\ncurrent")
            _write_manifest(
                year_dir,
                {
                    "meeting_date": "2026-03-24",
                    "title": "Financial Advisory Board Special Meeting",
                    "event_id": 1013,
                    "documents": {
                        "agenda": {
                            "current": _civic_record(canonical_path, year_dir),
                            "revisions": [
                                {
                                    "path": revision_path.relative_to(year_dir).as_posix(),
                                    "file_id": 8186,
                                    "sha256": _sha256(revision_path),
                                    "source_url": archive_document_url(8186),
                                },
                            ],
                        },
                    },
                },
            )

            with patch("check_register.archivecenter.urlopen") as urlopen:
                archived = archive_archivecenter_document(document, originals_dir=originals_dir, meeting_type="financial-advisory-board")

            self.assertEqual(archived.action, "unchanged")
            urlopen.assert_not_called()
            manifest = json.loads((year_dir / "manifest.json").read_text())
            revision = manifest["meetings"][0]["documents"]["agenda"]["revisions"][0]
            self.assertIsNone(revision["file_id"])
            self.assertEqual(revision["archive_id"], 8186)
            self.assertEqual(revision["source_system"], "archivecenter")

    def test_archive_document_preserves_civicclerk_canonical_unless_variants_are_requested(self):
        meeting = parse_meeting(
            {
                "id": 1,
                "eventName": "Financial Advisory Board Meeting",
                "eventDate": "2025-12-18T19:00:00Z",
                "categoryName": "Financial Advisory Board",
                "eventLocation": {"city": "El Cerrito"},
            },
        )
        civic_document = CivicClerkDocument(
            file_id=100,
            kind="agenda",
            name="Agenda",
            stream_url="https://example.test/civic-agenda.pdf",
            publish_on="2025-12-12T12:00:00Z",
        )
        archive_document = _document(8127, "agenda", date(2025, 12, 18))

        with tempfile.TemporaryDirectory() as tmpdir:
            originals_dir = Path(tmpdir) / "originals"
            with patch(
                "check_register.civicclerk.urlopen",
                return_value=_FakeResponse(b"%PDF-1.7\ncivic"),
            ):
                archive_civicclerk_document(meeting, civic_document, originals_dir=originals_dir)
            with patch("check_register.archivecenter.urlopen") as urlopen:
                skipped = archive_archivecenter_document(archive_document, originals_dir=originals_dir, meeting_type="financial-advisory-board")
            with patch(
                "check_register.archivecenter.urlopen",
                return_value=_FakeResponse(b"%PDF-1.7\narchive", filename="FAB 12 18 25 Agenda.pdf"),
            ):
                variant = archive_archivecenter_document(
                    archive_document,
                    originals_dir=originals_dir,
                    meeting_type="financial-advisory-board",
                    include_variants=True,
                )

            self.assertEqual(skipped.action, "skipped-existing")
            urlopen.assert_not_called()
            self.assertEqual(variant.action, "variant-downloaded")
            manifest = load_manifest(
                manifest_path(originals_dir, "financial-advisory-board", 2025),
                year=2025,
            )
            state = manifest["meetings"][0]["documents"]["agenda"]
            self.assertEqual(state["current"]["file_id"], 100)
            self.assertEqual(state["revisions"][0]["archive_id"], 8127)
            self.assertTrue(variant.path.exists())

    def test_archive_document_rejects_conflicting_download_filename_without_installing(self):
        document = _document(7847, "agenda_packet", date(2024, 1, 28))

        with tempfile.TemporaryDirectory() as tmpdir:
            originals_dir = Path(tmpdir) / "originals"
            with patch(
                "check_register.archivecenter.urlopen",
                return_value=_FakeResponse(b"%PDF-1.7\npacket", filename="01 28 25_Reports.pdf"),
            ):
                with self.assertRaisesRegex(ArchiveCenterError, "conflicts with downloaded filename"):
                    archive_archivecenter_document(document, originals_dir=originals_dir, meeting_type="financial-advisory-board")

            year_dir = originals_dir / "financial-advisory-board/2024"
            self.assertFalse((year_dir / "agenda-packets/2024-01-28 Agenda Packet.pdf").exists())
            self.assertFalse(list(year_dir.rglob("*.download")) if year_dir.exists() else [])

    def test_cli_cache_requires_a_date_selection(self):
        with io.StringIO() as stderr, contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as raised:
                main(["cache"])
            output = stderr.getvalue()

        self.assertEqual(raised.exception.code, 1)
        self.assertIn("Specify --date, --year, or --start/--end", output)

    def test_cli_cache_dry_run_selects_the_december_pair(self):
        agenda = _document(8127, "agenda", date(2025, 12, 18))
        packet = _document(8128, "agenda_packet", date(2025, 12, 18))
        with tempfile.TemporaryDirectory() as tmpdir:
            with io.StringIO() as stdout, contextlib.redirect_stdout(stdout):
                with patch("archivecenter_documents.fetch_documents", return_value=[agenda, packet]):
                    main(
                        [
                            "cache",
                            "--date",
                            "2025-12-18",
                            "--originals-dir",
                            tmpdir,
                            "--dry-run",
                        ],
                    )
                output = stdout.getvalue()

        self.assertIn("item 8127", output)
        self.assertIn("item 8128", output)
        self.assertIn("Dry run; action would be download", output)
        args = parse_args(["cache", "--date", "2025-12-18"])
        self.assertEqual(args.date, [date(2025, 12, 18)])


class _FakeResponse:
    def __init__(self, payload: bytes, *, filename: str | None = None):
        self._payload = payload
        self._offset = 0
        self.headers = {"content-type": "application/pdf"}
        if filename:
            self.headers["content-disposition"] = f'inline; filename="{filename}"'

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


def _document(
    archive_id: int,
    kind: str,
    listing_date: date,
    *,
    document_format: str = "pdf",
) -> ArchiveCenterDocument:
    label = "Attachment Reports" if kind == "agenda_packet" else "Agenda"
    return ArchiveCenterDocument(
        archive_id=archive_id,
        kind=kind,
        listing_title=f"{label} - {listing_date.strftime('%B')} {listing_date.day}, {listing_date.year}",
        listing_description=None,
        listing_date=listing_date,
        listing_url=f"https://www.elcerrito.gov/Archive.aspx?ADID={archive_id}",
        source_url=archive_document_url(archive_id),
        document_format=document_format,
    )


def _write_manifest(year_dir: Path, meeting: dict[str, object]) -> None:
    (year_dir / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "year": int(year_dir.name),
                "last_checked_at": None,
                "meetings": [meeting],
            },
        ),
    )


def _civic_record(path: Path, year_dir: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(year_dir).as_posix(),
        "file_id": 100,
        "sha256": _sha256(path),
        "source_url": "https://example.test/civic-agenda.pdf",
    }


def _sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


_INDEX_HTML = """
<table summary="Archive Details">
  <tr><td><img src="common/images/iconpdf.gif" alt="December 18, 2025"></td>
  <td><span class="archive"><a href="Archive.aspx?ADID=8127" target="_blank"><span>December 18, 2025</span></a><br>
  <span style="font-style: italic"></span></span></td></tr>
</table>
<table summary="Archive Details">
  <tr><td><img src="common/images/iconpdf.gif" alt="June 25. 2024"></td>
  <td><span class="archive"><a href="Archive.aspx?ADID=7623"><span>June 25. 2024</span></a><br>
  <span style="font-style: italic">Special meeting</span></span></td></tr>
</table>
"""


if __name__ == "__main__":
    unittest.main()
