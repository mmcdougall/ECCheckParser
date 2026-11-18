import contextlib
import io
import tempfile
from decimal import Decimal
from pathlib import Path
import unittest
from unittest.mock import patch

from check_register.models import CheckEntry
from check_register.page_extractor import register_name_prefix, default_pdf_name
from check_register_parser import (
    parse_args,
    derive_output_paths,
    derive_output_path_sets,
    ParsedSection,
    plan_outputs,
    main,
    write_outputs,
    print_stats,
)


class TestCliHelpers(unittest.TestCase):
    def _entries(self):
        return [
            CheckEntry(6, 2025, "check", "", "", "", "", "", "", Decimal("1"), False)
        ]

    def _monthly_sections(self, second_start=14):
        june = CheckEntry(6, 2025, "check", "1001", "06/30/2025", "Open",
                          "Accounts Payable", "ACME", "SUPPLIES", Decimal("3"), False)
        overlap = CheckEntry(7, 2025, "check", "1001", "06/30/2025", "Open",
                             "Accounts Payable", "ACME", "SUPPLIES", Decimal("3"), False)
        july = CheckEntry(7, 2025, "check", "1002", "07/01/2025", "Open",
                          "Accounts Payable", "BETA", "SERVICES", Decimal("7"), False)
        return [
            ParsedSection((7, 13), [], [june]),
            ParsedSection((second_start, 21), [], [overlap, july]),
        ]

    def test_parse_args_defaults(self):
        args = parse_args(["in.pdf"])
        self.assertEqual(args.pdf, Path("in.pdf"))
        self.assertIsNone(args.csv)
        self.assertFalse(args.print_rollups)

    def test_derive_output_paths(self):
        entries = self._entries()
        args = parse_args([
            "in.pdf",
            "--csv",
            "--json",
            "--html",
            "--chunks-json",
            "--pdf",
        ])
        paths = derive_output_paths(args, entries)
        prefix = register_name_prefix(entries)
        self.assertEqual(paths.csv, Path(f"{prefix}.csv"))
        self.assertEqual(paths.json, Path(f"{prefix}.json"))
        self.assertEqual(paths.html, Path(f"{prefix}-payees.html"))
        self.assertEqual(paths.chunks_json, Path(f"{prefix}-chunks.json"))
        self.assertEqual(paths.pdf, default_pdf_name(entries))

    def test_derive_output_path_sets_for_disjoint_sections(self):
        nov_entries = [
            CheckEntry(11, 2025, "check", "", "", "", "", "", "", Decimal("1"), False)
        ]
        dec_entries = [
            CheckEntry(12, 2025, "check", "", "", "", "", "", "", Decimal("1"), False)
        ]
        args = parse_args(["in.pdf", "--csv", "--chunks-json", "--pdf"])
        path_sets = derive_output_path_sets(args, [nov_entries, dec_entries])
        self.assertEqual(path_sets[0].csv, Path("2025-11.csv"))
        self.assertEqual(path_sets[0].chunks_json, Path("2025-11-chunks.json"))
        self.assertEqual(path_sets[0].pdf, Path("2025-11-register.pdf"))
        self.assertEqual(path_sets[1].csv, Path("2025-12.csv"))
        self.assertEqual(path_sets[1].chunks_json, Path("2025-12-chunks.json"))
        self.assertEqual(path_sets[1].pdf, Path("2025-12-register.pdf"))

    def test_derive_output_path_sets_rejects_explicit_paths(self):
        nov_entries = [
            CheckEntry(11, 2025, "check", "", "", "", "", "", "", Decimal("1"), False)
        ]
        dec_entries = [
            CheckEntry(12, 2025, "check", "", "", "", "", "", "", Decimal("1"), False)
        ]
        args = parse_args(["in.pdf", "--csv", "out.csv"])
        with io.StringIO() as buf, contextlib.redirect_stdout(buf):
            with self.assertRaises(SystemExit) as cm:
                derive_output_path_sets(args, [nov_entries, dec_entries])
        self.assertEqual(cm.exception.code, 1)

    def test_adjacent_explicit_exports_combine_all_requested_formats(self):
        args = parse_args([
            "in.pdf", "--csv", "out.csv", "--json", "out.json", "--html", "out.html",
            "--chunks-json", "out-chunks.json", "--pdf", "out.pdf", "--payees", "out-payees.txt",
        ])
        plans = plan_outputs(args, self._monthly_sections())
        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0].section.page_range, (7, 21))
        self.assertEqual(len(plans[0].section.entries), 3)
        self.assertEqual(plans[0].paths.csv, Path('out.csv'))
        self.assertEqual(plans[0].paths.json, Path('out.json'))
        self.assertEqual(plans[0].paths.html, Path('out.html'))
        self.assertEqual(plans[0].paths.chunks_json, Path('out-chunks.json'))
        self.assertEqual(plans[0].paths.pdf, Path('out.pdf'))
        self.assertEqual(plans[0].paths.payees_txt, Path('out-payees.txt'))

    def test_mixed_explicit_and_default_exports_keep_monthly_defaults(self):
        args = parse_args([
            'in.pdf', '--csv', 'out.csv', '--json', '--html', '--chunks-json', '--pdf',
        ])
        plans = plan_outputs(args, self._monthly_sections())
        self.assertEqual(len(plans), 3)
        for plan, month in zip(plans[:2], ('2025-06', '2025-07')):
            self.assertIsNone(plan.paths.csv)
            self.assertEqual(plan.paths.json, Path(f'{month}.json'))
            self.assertEqual(plan.paths.html, Path(f'{month}-payees.html'))
            self.assertEqual(plan.paths.chunks_json, Path(f'{month}-chunks.json'))
            self.assertEqual(plan.paths.pdf, Path(f'{month}-register.pdf'))
        self.assertEqual(plans[2].paths.csv, Path('out.csv'))
        self.assertIsNone(plans[2].paths.pdf)

    def test_overlapping_explicit_and_default_paths_are_rejected(self):
        args = parse_args(['in.pdf', '--csv', '2025-06.json', '--json'])
        with io.StringIO() as buf, contextlib.redirect_stdout(buf):
            with self.assertRaises(SystemExit) as cm:
                plan_outputs(args, self._monthly_sections())
        self.assertEqual(cm.exception.code, 1)

    def test_cli_deduplicates_totals_across_monthly_sections_once(self):
        with patch('check_register_parser.parse_sections', return_value=self._monthly_sections()):
            with io.StringIO() as buf, contextlib.redirect_stdout(buf):
                main(['in.pdf', '--totals'])
                output = buf.getvalue()
        self.assertEqual(output.count('Per-month totals (non-void, deduped):'), 1)
        self.assertEqual(output.count('06/2025:'), 1)
        self.assertEqual(output.count('07/2025:'), 1)
        self.assertIn('06/2025: $3.00', output)
        self.assertIn('07/2025: $7.00', output)

    def test_cli_combined_csv_and_monthly_pdfs_use_distinct_groups(self):
        sections = self._monthly_sections()
        with patch('check_register_parser.parse_sections', return_value=sections):
            with patch('check_register_parser.write_csv') as csv:
                with patch('check_register_parser.extract_check_register_pdf_range') as pdf:
                    pdf.side_effect = lambda source, target, start, end: (start, end)
                    with io.StringIO() as buf, contextlib.redirect_stdout(buf):
                        main(['in.pdf', '--csv', 'out.csv', '--pdf'])
        self.assertEqual(len(csv.call_args.args[0]), 3)
        self.assertEqual(csv.call_args.args[1], Path('out.csv'))
        self.assertEqual([call.args[1:] for call in pdf.call_args_list], [
            (Path('2025-06-register.pdf'), 7, 13),
            (Path('2025-07-register.pdf'), 14, 21),
        ])

    def test_cli_explicit_pdf_combines_adjacent_ranges(self):
        with patch('check_register_parser.parse_sections', return_value=self._monthly_sections()):
            with patch('check_register_parser.extract_check_register_pdf_range', return_value=(7, 21)) as pdf:
                with io.StringIO() as buf, contextlib.redirect_stdout(buf):
                    main(['in.pdf', '--pdf', 'out.pdf'])
        pdf.assert_called_once_with(Path('in.pdf'), Path('out.pdf'), 7, 21)

    def test_cli_rejects_disjoint_explicit_outputs_before_writing(self):
        with patch('check_register_parser.parse_sections', return_value=self._monthly_sections(15)):
            with patch('check_register_parser.write_csv') as csv:
                with patch('check_register_parser.extract_check_register_pdf_range') as pdf:
                    with io.StringIO() as buf, contextlib.redirect_stdout(buf):
                        with self.assertRaises(SystemExit) as cm:
                            main(['in.pdf', '--csv', 'out.csv', '--pdf', 'out.pdf'])
        self.assertEqual(cm.exception.code, 1)
        csv.assert_not_called()
        pdf.assert_not_called()

    def test_write_outputs_and_print_stats(self):
        entries = self._entries()
        args = parse_args(["in.pdf", "--csv", "--json", "--html"])
        paths = derive_output_paths(args, entries)
        with tempfile.TemporaryDirectory() as td:
            paths.csv = Path(td, "out.csv")
            paths.json = Path(td, "out.json")
            paths.html = Path(td, "out.html")
            write_outputs(entries, paths, drop=0)
            self.assertTrue(paths.csv.exists())
            self.assertTrue(paths.json.exists())
            self.assertTrue(paths.html.exists())
            with io.StringIO() as buf, contextlib.redirect_stdout(buf):
                print_stats(entries, paths, rollups=False, totals=False)
                out = buf.getvalue()
        self.assertIn("Rows: 1", out)


if __name__ == "__main__":
    unittest.main()
