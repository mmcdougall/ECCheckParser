from __future__ import annotations

import contextlib
from dataclasses import replace
from datetime import date
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fab_motion_search import _render_records, main, parse_args
from fab_motions import MotionOutcome, MotionRecord, PacketSource


class TestFabMotionSearchCli(unittest.TestCase):
    def _record(self, outcome: MotionOutcome, held_date: date) -> MotionRecord:
        return MotionRecord(
            source=PacketSource(Path("packet.pdf"), packet_date=date(2026, 5, 26), file_id=3350),
            held_date=held_date,
            held_date_evidence="minutes-heading",
            physical_page_start=5,
            physical_page_end=5,
            agenda_item="6. REVIEW OF DRAFT BUDGET",
            full_motion_text="Motion/Second: Motion to recommend a reserve threshold.",
            recommendation_text=None,
            supporting_text=None,
            vote_text="Ayes: Chair Carvel; Members A and B. Noes: Member C.",
            result_text=None,
            outcome=outcome,
            ayes=3,
            noes=1,
            routine=False,
        )

    def test_parse_args_defaults_to_fab_archive(self):
        args = parse_args([])

        self.assertEqual(args.packet, [])
        self.assertFalse(args.successful_only)
        self.assertFalse(args.exclude_routine)
        self.assertFalse(args.exclude_procedural)
        self.assertEqual(args.format, "text")

    def test_selected_packets_filter_and_render_json(self):
        passed = self._record(MotionOutcome.AFFIRMATIVE_RECORDED_VOTE, date(2026, 5, 7))
        failed = self._record(MotionOutcome.EXPLICIT_FAILURE, date(2026, 5, 7))

        with patch("fab_motion_search.scan_minutes_packet", return_value=[passed, failed]) as scan:
            with io.StringIO() as buffer, contextlib.redirect_stdout(buffer):
                main(
                    [
                        "--packet",
                        "packet.pdf",
                        "--packet",
                        "copied-minutes.pdf",
                        "--successful-only",
                        "--format",
                        "json",
                    ],
                )
                payload = buffer.getvalue()

        records = json.loads(payload)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["outcome"], "affirmative-recorded-vote")
        self.assertEqual(records[0]["held_date"], "2026-05-07")
        self.assertEqual(scan.call_count, 2)

    def test_archive_mode_passes_filters_to_scanner(self):
        passed = self._record(MotionOutcome.EXPLICIT_PASS, date(2025, 10, 28))
        with patch("fab_motion_search.scan_fab_archive", return_value=[passed]) as scan:
            with io.StringIO() as buffer, contextlib.redirect_stdout(buffer):
                main(
                    [
                        "--from",
                        "2025-10-01",
                        "--through",
                        "2025-10-31",
                        "--successful-only",
                        "--exclude-routine",
                        "--exclude-procedural",
                    ],
                )
                output = buffer.getvalue()

        self.assertIn("2025-10-28 | explicit-pass", output)
        self.assertIn("CivicClerk file 3350", output)
        self.assertEqual(scan.call_args.kwargs["start"], date(2025, 10, 1))
        self.assertEqual(scan.call_args.kwargs["through"], date(2025, 10, 31))
        self.assertTrue(scan.call_args.kwargs["successful_only"])
        self.assertTrue(scan.call_args.kwargs["exclude_routine"])
        self.assertTrue(scan.call_args.kwargs["exclude_procedural"])

    def test_out_writes_text_without_printing(self):
        record = self._record(MotionOutcome.EXPLICIT_PASS, date(2025, 10, 28))
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "motions.txt"
            with patch("fab_motion_search.scan_minutes_packet", return_value=[record]):
                with io.StringIO() as buffer, contextlib.redirect_stdout(buffer):
                    main(["--packet", "packet.pdf", "--out", str(output_path)])
                    output = buffer.getvalue()

            self.assertEqual(output, "")
            self.assertIn("Motion: Motion/Second", output_path.read_text(encoding="utf-8"))

    def test_markdown_output_uses_substantive_text_and_packet_link(self):
        record = self._record(MotionOutcome.EXPLICIT_PASS, date(2025, 10, 28))
        record = replace(
            record,
            recommendation_text="The FAB recommends a 17% reserve goal.",
            source=replace(
                record.source,
                source_url=(
                    "https://example.test/GetMeetingFileStream"
                    "(fileId=3350,plainText=false)"
                ),
            ),
        )

        output = _render_records([record], "markdown")

        self.assertIn("**2025-10-28**", output)
        self.assertIn("The FAB recommends a 17% reserve goal.", output)
        self.assertIn("GetMeetingFileStream%28fileId=3350,plainText=false%29", output)
        self.assertIn("Minutes packet, p. 5", output)


if __name__ == "__main__":
    unittest.main()
