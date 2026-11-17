from __future__ import annotations

from dataclasses import replace
from datetime import date
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fab_motions import (
    MotionOutcome,
    PacketSource,
    deduplicate_motion_records,
    filter_motion_records,
    iter_fab_packet_sources,
    scan_fab_archive,
    scan_minutes_packet,
    scan_page_texts,
)
from project_paths import ORIGINALS_DIR


REVIEW_FIXTURE = Path(__file__).parent / "fixtures/fab_fy25_26_accomplishment_motions.json"


class TestFabMotionScanner(unittest.TestCase):
    def _source(self, packet_date: date = date(2025, 11, 13)) -> PacketSource:
        return PacketSource(
            Path("2025-11-13 Agenda Packet.pdf"),
            packet_date=packet_date,
            file_id=2757,
            source_url="https://example.test/packet.pdf",
            sha256="a" * 64,
        )

    def test_explicit_pass_preserves_proposed_recommendation(self):
        records = scan_page_texts(
            [
                "\n".join(
                    [
                        "MINUTES",
                        "REGULAR MEETING OF THE FINANCIAL ADVISORY BOARD (FAB)",
                        "Tuesday, October 28, 2025 at 6:30 p.m.",
                        "6. GENERAL FUND LONG-TERM FORECAST (15 min.) (Attachment)",
                        "Chair Carvel proposed the following recommendation: The Financial Advisory Board recommends the City Council take action to meet the 17% unassigned reserve goal.",
                        "Motion/Second: motion to approve the recommendation by Chair Carvel, Second by Member Szlatenyi.",
                        "Ayes: Chair Carvel; Vice-Chair McDougall; Members Szlatenyi and White; Youth Member Singer.",
                        "Noes: None",
                        "Motion Passed",
                    ],
                ),
            ],
            self._source(),
        )

        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record.held_date, date(2025, 10, 28))
        self.assertEqual(record.held_date_evidence, "minutes-heading")
        self.assertEqual(record.source.packet_date, date(2025, 11, 13))
        self.assertEqual(record.physical_page_start, 1)
        self.assertEqual(record.physical_page_end, 1)
        self.assertEqual(record.agenda_item, "6. GENERAL FUND LONG-TERM FORECAST (15 min.) (Attachment)")
        self.assertIn("17% unassigned reserve goal", record.recommendation_text or "")
        self.assertIn("motion to approve the recommendation", record.full_motion_text)
        self.assertEqual(record.vote_text, "Ayes: Chair Carvel; Vice-Chair McDougall; Members Szlatenyi and White; Youth Member Singer. Noes: None")
        self.assertEqual(record.result_text, "Motion Passed")
        self.assertEqual(record.outcome, MotionOutcome.EXPLICIT_PASS)
        self.assertEqual((record.ayes, record.noes), (5, 0))

    def test_vote_only_affirmative_and_no_second_outcomes_are_distinct(self):
        records = scan_page_texts(
            [
                "\n".join(
                    [
                        "SPECIAL MEETING OF THE FINANCIAL ADVISORY BOARD (FAB)",
                        "Thursday, May 7, 2026 at 6:30 p.m.",
                        "6. REVIEW OF DRAFT BUDGET",
                        "Motion/Second: Motion to recommend a 30% total reserve threshold. No second. Motion fails.",
                        "Motion/Second: Motion to recommend a 26% total reserve threshold. Seconded by Chair Carvel.",
                        "Ayes: Chair Carvel; Vice Chair McDougall; Member Szlatenyi, White, and Van",
                        "Zerber",
                        "Noes: Members White and Van Zerber",
                        "Motion/Second: Motion to recommend grant writing. No second.",
                    ],
                ),
            ],
            self._source(date(2026, 5, 26)),
        )

        self.assertEqual(
            [record.outcome for record in records],
            [
                MotionOutcome.EXPLICIT_FAILURE,
                MotionOutcome.AFFIRMATIVE_RECORDED_VOTE,
                MotionOutcome.NO_DISPOSITION,
            ],
        )
        self.assertEqual((records[1].ayes, records[1].noes), (5, 2))
        self.assertEqual(filter_motion_records(records, successful_only=True), [records[1]])

    def test_numbered_recommendation_can_span_packet_pages(self):
        records = scan_page_texts(
            [
                "\n".join(
                    [
                        "MINUTES",
                        "REGULAR MEETING OF THE FINANCIAL ADVISORY BOARD (FAB)",
                        "Tuesday, May 26, 2026 at 6:30 p.m.",
                        "6. REVIEW OF DRAFT BUDGET",
                        "Recommendation 3: The FAB recommends a fiscal sustainability framework.",
                        "Moved/Second: Member Szlatenyi/Chair Carvel",
                    ],
                ),
                "\n".join(
                    [
                        "Ayes: Chair Carvel; Members Szlatenyi and White",
                        "Noes: Vice Chair McDougall; Member Van Zerber",
                    ],
                ),
            ],
            self._source(date(2026, 6, 4)),
        )

        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record.held_date, date(2026, 5, 26))
        self.assertEqual((record.physical_page_start, record.physical_page_end), (1, 2))
        self.assertEqual(record.outcome, MotionOutcome.AFFIRMATIVE_RECORDED_VOTE)
        self.assertIn("fiscal sustainability framework", record.recommendation_text or "")
        self.assertEqual(record.full_motion_text, "Moved/Second: Member Szlatenyi/Chair Carvel")

    def test_agenda_language_without_a_recorded_outcome_is_not_a_motion_record(self):
        records = scan_page_texts(
            [
                "\n".join(
                    [
                        "AGENDA",
                        "FINANCIAL ADVISORY BOARD",
                        "6. BUDGET REVIEW",
                        "Consider a motion to make a recommendation to Council.",
                    ],
                ),
            ],
            self._source(),
        )

        self.assertEqual(records, [])

    def test_routine_minutes_approval_can_be_excluded_after_extraction(self):
        records = scan_page_texts(
            [
                "\n".join(
                    [
                        "MINUTES",
                        "REGULAR MEETING OF THE FINANCIAL ADVISORY BOARD (FAB)",
                        "Tuesday, October 28, 2025 at 6:30 p.m.",
                        "4. APPROVAL OF THE MINUTES",
                        "Motion/Second: Vice-Chair McDougall/Member Szlatenyi.",
                        "Ayes: Chair Carvel; Vice-Chair McDougall; Members Szlatenyi and White",
                        "Noes: None",
                        "Motion Passed",
                    ],
                ),
            ],
            self._source(),
        )

        self.assertTrue(records[0].routine)
        self.assertEqual(filter_motion_records(records, exclude_routine=True), [])

    def test_procedural_actions_have_reasons_and_can_be_excluded(self):
        records = scan_page_texts(
            [
                "\n".join(
                    [
                        "MINUTES",
                        "REGULAR MEETING OF THE FINANCIAL ADVISORY BOARD (FAB)",
                        "Thursday, November 13, 2025 at 6:30 p.m.",
                        "5. REVIEW COMPREHENSIVE FINANCIAL POLICY",
                        "Motion/Second: Motion to table the review to December by Member White, second by Vice-Chair McDougall.",
                        "Ayes: Chair Carvel; Vice-Chair McDougall; Members White and Szlatenyi",
                        "Noes: None",
                        "Motion passes.",
                        "6. FAB MEETING SCHEDULE CALENDAR YEAR 2026",
                        "Motion/Second: Motion to adopt the calendar by Member White, second by Member Szlatenyi.",
                        "Ayes: Chair Carvel; Vice-Chair McDougall; Members White and Szlatenyi",
                        "Noes: None",
                        "Motion passes.",
                    ],
                ),
            ],
            self._source(date(2025, 12, 18)),
        )

        self.assertEqual(
            [record.procedural_reason for record in records],
            ["deferral", "meeting-schedule"],
        )
        self.assertEqual(filter_motion_records(records, exclude_procedural=True), [])

    def test_officer_election_is_routine_when_motion_is_generic(self):
        records = scan_page_texts(
            [
                "\n".join(
                    [
                        "MINUTES",
                        "REGULAR MEETING OF THE FINANCIAL ADVISORY BOARD (FAB)",
                        "Tuesday, August 26, 2025 at 6:30 p.m.",
                        "9. ELECTION OF OFFICERS",
                        "Motion/Second: Member Szlatenyi/Vice-Chair Carvel.",
                        "Ayes: Chair White; Vice-Chair Carvel; Members Szlatenyi and McDougall",
                        "Noes: None",
                        "Motion passes.",
                    ],
                ),
            ],
            self._source(date(2025, 9, 23)),
        )

        self.assertTrue(records[0].routine)
        self.assertEqual(filter_motion_records(records, exclude_routine=True), [])

    def test_heading_date_wins_over_a_conflicting_agenda_footer(self):
        records = scan_page_texts(
            [
                "\n".join(
                    [
                        "SPECIAL MEETING OF THE FINANCIAL ADVISORY BOARD (FAB)",
                        "Thursday, May 7, 2026 at 6:30 p.m.",
                        "Motion/Second: Motion to recommend a 26% total reserve threshold. Seconded by Chair Carvel.",
                        "Ayes: Chair Carvel; Vice Chair McDougall; Member Szlatenyi",
                        "Noes: Members White and Van Zerber",
                        "Financial Advisory Board (FAB)",
                        "04/28/2026 Agenda Page 3 of 3",
                    ],
                ),
            ],
            self._source(date(2026, 5, 26)),
        )

        self.assertEqual(records[0].held_date, date(2026, 5, 7))
        self.assertEqual(records[0].held_date_evidence, "minutes-heading")
        self.assertEqual(
            records[0].date_conflicts,
            ("footer date 2026-04-28 conflicts with held date 2026-05-07",),
        )

    def test_unresolved_minutes_date_is_not_filled_from_source_packet(self):
        records = scan_page_texts(
            [
                "\n".join(
                    [
                        "4. APPROVAL OF THE MINUTES",
                        "Motion/Second: Member Farahmand/Member Schaffran.",
                        "Ayes: Chair White; Members Farahmand and Schaffran",
                        "Noes: None",
                    ],
                ),
            ],
            self._source(date(2025, 4, 29)),
        )

        self.assertIsNone(records[0].held_date)
        self.assertEqual(records[0].held_date_evidence, "unresolved")
        self.assertEqual(
            filter_motion_records(records, start=date(2025, 4, 1), through=date(2025, 4, 30)),
            [],
        )

    def test_undated_minutes_do_not_inherit_the_preceding_agenda_date(self):
        records = scan_page_texts(
            [
                "\n".join(
                    [
                        "AGENDA",
                        "REGULAR MEETING OF THE FINANCIAL ADVISORY BOARD (FAB)",
                        "Tuesday, April 29, 2025 at 6:30 p.m.",
                        "04/29/2025 Agenda Page 1 of 1",
                    ],
                ),
                "\n".join(
                    [
                        "MINUTES",
                        "4. APPROVAL OF THE MINUTES",
                        "Motion/Second: Member Farahmand/Member Schaffran.",
                        "Ayes: Chair White; Members Farahmand and Schaffran",
                        "Noes: None",
                    ],
                ),
            ],
            self._source(date(2025, 4, 29)),
        )

        self.assertIsNone(records[0].held_date)
        self.assertEqual(records[0].held_date_evidence, "unresolved")

    def test_colonless_noes_label_is_part_of_the_vote(self):
        records = scan_page_texts(
            [
                "\n".join(
                    [
                        "MINUTES",
                        "REGULAR MEETING OF THE FINANCIAL ADVISORY BOARD (FAB)",
                        "Tuesday, August 26, 2025 at 6:30 p.m.",
                        "6. BUDGET REVIEW",
                        "Motion/Second: Member White/Member Szlatenyi.",
                        "Ayes: Chair Carvel; Members White and Szlatenyi",
                        "Noes McDougall. Motion passes. Absent: None",
                    ],
                ),
            ],
            self._source(date(2025, 9, 23)),
        )

        record = records[0]
        self.assertEqual((record.ayes, record.noes), (3, 1))
        self.assertEqual(
            record.vote_text,
            "Ayes: Chair Carvel; Members White and Szlatenyi "
            "Noes McDougall. Motion passes. Absent: None",
        )
        self.assertEqual(record.result_text, "Noes McDougall. Motion passes. Absent: None")

    def test_colonless_vote_labels_count_affirmative_vote(self):
        records = scan_page_texts(
            [
                "\n".join(
                    [
                        "MINUTES",
                        "REGULAR MEETING OF THE FINANCIAL ADVISORY BOARD (FAB)",
                        "Tuesday, August 26, 2025 at 6:30 p.m.",
                        "6. BUDGET REVIEW",
                        "Motion/Second: Member White/Member Szlatenyi.",
                        "Ayes Chair Carvel; Members White and Szlatenyi",
                        "Noes None",
                    ],
                ),
            ],
            self._source(date(2025, 9, 23)),
        )

        self.assertEqual(records[0].outcome, MotionOutcome.AFFIRMATIVE_RECORDED_VOTE)
        self.assertEqual((records[0].ayes, records[0].noes), (3, 0))

    def test_archive_scan_deduplicates_copied_minutes(self):
        page_text = "\n".join(
            [
                "MINUTES",
                "REGULAR MEETING OF THE FINANCIAL ADVISORY BOARD (FAB)",
                "Thursday, December 18, 2025 at 6:30 p.m.",
                "6. COMMUNITY FACILITIES PLAN",
                "Motion/Second: Member White/Member Szlatenyi.",
                "Ayes: Chair Carvel; Members White and Szlatenyi",
                "Noes: None",
                "Motion passes.",
            ],
        )
        first_source = PacketSource(
            Path("2026-01-27 Agenda Packet.pdf"),
            packet_date=date(2026, 1, 27),
            file_id=3177,
        )
        copied_source = PacketSource(
            Path("2026-02-12 Agenda Packet.pdf"),
            packet_date=date(2026, 2, 12),
            file_id=3175,
        )
        first_record = scan_page_texts([page_text], first_source)[0]
        copied_record = scan_page_texts([page_text], copied_source)[0]
        different_action = replace(
            copied_record,
            recommendation_text="Recommendation 2: Use a different action.",
        )

        with (
            patch(
                "fab_motions.scanner.iter_fab_packet_sources",
                return_value=[copied_source, first_source],
            ),
            patch(
                "fab_motions.scanner.scan_minutes_packet",
                side_effect=[[copied_record, different_action], [first_record]],
            ),
        ):
            records = scan_fab_archive(Path("unused"))

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].source, first_source)
        self.assertEqual(records[1], different_action)
        self.assertEqual(
            deduplicate_motion_records([copied_record, first_record, different_action]),
            [first_record, different_action],
        )

    def test_post_vote_recommendation_is_retained_as_supporting_text(self):
        records = scan_page_texts(
            [
                "\n".join(
                    [
                        "MINUTES",
                        "REGULAR MEETING OF THE FINANCIAL ADVISORY BOARD (FAB)",
                        "Tuesday, January 27, 2026 at 6:30 p.m.",
                        "8. ANNUAL COMPREHENSIVE FINANCIAL REPORT",
                        "Motion/Second: Motion to submit an ACFR recommendation to Council.",
                        "Ayes: Chair Carvel; Vice-Chair McDougall; Members White and Szlatenyi",
                        "Noes: None",
                        "Motion passes",
                        "FAB reviewed the ACFR and recommends particular attention be paid to controlling expenses.",
                        "9. FUTURE AGENDA ITEMS",
                    ],
                ),
            ],
            self._source(date(2026, 2, 12)),
        )

        self.assertEqual(records[0].outcome, MotionOutcome.EXPLICIT_PASS)
        self.assertIn("controlling expenses", records[0].supporting_text or "")

    def test_manifest_discovery_uses_only_current_agenda_packets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            year_dir = root / "2026"
            (year_dir / "agenda-packets").mkdir(parents=True)
            (year_dir / "agenda-packet-revisions").mkdir(parents=True)
            manifest = {
                "schema_version": 1,
                "year": 2026,
                "meetings": [
                    {
                        "meeting_date": "2026-05-26",
                        "documents": {
                            "agenda_packet": {
                                "current": {
                                    "path": "agenda-packets/2026-05-26 Agenda Packet.pdf",
                                    "file_id": 3400,
                                    "source_url": "https://example.test/current.pdf",
                                    "sha256": "b" * 64,
                                },
                                "revisions": [
                                    {
                                        "path": "agenda-packet-revisions/2026-05-26 Agenda Packet - old.pdf",
                                        "file_id": 3300,
                                    },
                                ],
                            },
                        },
                    },
                ],
            }
            (year_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

            sources = iter_fab_packet_sources(root)

        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0].path.name, "2026-05-26 Agenda Packet.pdf")
        self.assertEqual(sources[0].file_id, 3400)
        self.assertEqual(sources[0].packet_date, date(2026, 5, 26))

    def test_small_canonical_packet_smoke_test(self):
        packet_path = (
            ORIGINALS_DIR
            / "financial-advisory-board/2025/agenda-packets/2025-11-13 Agenda Packet.pdf"
        )
        self.assertTrue(packet_path.exists(), f"Missing original PDF: {packet_path}")

        records = scan_minutes_packet(packet_path)
        recommendations = [
            record
            for record in records
            if record.is_successful and record.recommendation_text
        ]

        self.assertEqual(len(records), 3)
        self.assertTrue(all(record.source.packet_date == date(2025, 11, 13) for record in records))
        self.assertEqual(
            len(filter_motion_records(records, successful_only=True, exclude_routine=True)),
            2,
        )
        self.assertEqual(len(recommendations), 2)
        self.assertTrue(all(record.held_date == date(2025, 10, 28) for record in recommendations))
        self.assertEqual(
            [record.physical_page_start for record in recommendations],
            [2, 3],
        )
        self.assertIn("17% unassigned reserve goal", recommendations[0].recommendation_text or "")
        self.assertIn("service delivery study", recommendations[1].recommendation_text or "")

    def test_fy25_26_candidates_match_hand_reviewed_fixture(self):
        fixture = json.loads(REVIEW_FIXTURE.read_text(encoding="utf-8"))
        packet_specs = [
            (2025, "2025-09-23", 2760),
            (2025, "2025-10-28", 2759),
            (2025, "2025-11-13", 2757),
            (2025, "2025-12-18", None),
            (2026, "2026-01-27", 3177),
            (2026, "2026-02-12", 3175),
            (2026, "2026-05-26", 3350),
            (2026, "2026-06-04", 3400),
            (2026, "2026-07-28", 3499),
        ]
        records = []
        for year, packet_date, file_id in packet_specs:
            packet_path = (
                ORIGINALS_DIR
                / f"financial-advisory-board/{year}/agenda-packets/{packet_date} Agenda Packet.pdf"
            )
            self.assertTrue(packet_path.exists(), f"Missing original PDF: {packet_path}")
            records.extend(
                scan_minutes_packet(
                    packet_path,
                    source_packet_date=date.fromisoformat(packet_date),
                    source_file_id=file_id,
                ),
            )

        scope = fixture["scope"]
        records = filter_motion_records(
            deduplicate_motion_records(records),
            start=date.fromisoformat(scope["held_from"]),
            through=date.fromisoformat(scope["held_through"]),
            successful_only=scope["successful_only"],
            exclude_routine=scope["exclude_routine"],
            exclude_procedural=scope["exclude_procedural"],
        )

        expected = fixture["motions"]
        self.assertEqual(len(records), len(expected))
        for record, reviewed in zip(records, expected, strict=True):
            self.assertEqual(record.held_date.isoformat(), reviewed["held_date"])
            self.assertEqual(record.source.file_id, reviewed["source_file_id"])
            self.assertEqual(record.physical_page_start, reviewed["physical_page_start"])
            self.assertEqual(record.outcome.value, reviewed["outcome"])
            self.assertEqual(record.ayes, reviewed["ayes"])
            self.assertEqual(record.noes, reviewed["noes"])
            self.assertIn(reviewed["evidence_contains"], record.source_excerpt)
            self.assertFalse(record.routine)
            self.assertFalse(record.procedural)


if __name__ == "__main__":
    unittest.main()
