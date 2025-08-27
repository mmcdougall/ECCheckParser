import contextlib
import io
import tempfile
from decimal import Decimal
from pathlib import Path
import unittest

from check_register.models import CheckEntry
from check_register.page_extractor import register_name_prefix, default_pdf_name
from check_register_parser import (
    parse_args,
    derive_output_paths,
    write_outputs,
    print_stats,
)


class TestCliHelpers(unittest.TestCase):
    def _entries(self):
        return [
            CheckEntry(6, 2025, "check", "", "", "", "", "", "", Decimal("1"), False)
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
