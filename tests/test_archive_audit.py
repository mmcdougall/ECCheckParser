import contextlib
import io
import tempfile
from pathlib import Path
import unittest

from check_register.archive_audit import (
    audit_register_archive,
    format_archive_audit,
    month_label,
    quarter_label,
)
from check_register_parser import main
from tests.test_fund_update_extractor import build_pdf


def write_csv(path: Path, months: list[tuple[int, int]]) -> None:
    rows = ["section_month,section_year,ap_type,number,date,status,source,payee,description,amount,voided"]
    for idx, (year, month) in enumerate(months, start=1):
        rows.append(f"{month},{year},check,{idx},01/01/{year},Open,Accounts Payable,Payee,Desc,1.00,N")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def write_fund_update_pdf(path: Path, fiscal_year: int, quarter: int) -> None:
    build_pdf(
        path,
        [
            "AGENDA BILL\nSubject: General Fund Budget Update",
            f"Page 1 of 2\nGeneral Fund Budget Update Quarter {quarter} FY {fiscal_year}-{(fiscal_year + 1) % 100:02d}",
            "Page 2 of 2\nFund balance details",
        ],
    )


class TestArchiveAudit(unittest.TestCase):
    def test_finds_missing_month_between_csv_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_dir = Path(tmpdir)
            fund_update_dir = csv_dir / "fund_updates"
            fund_update_dir.mkdir()
            write_csv(csv_dir / "2025-01.csv", [(2025, 1)])
            write_csv(csv_dir / "2025-03.csv", [(2025, 3)])
            write_fund_update_pdf(fund_update_dir / "2025-02-01-general-fund-update.pdf", 2024, 2)

            audit = audit_register_archive(csv_dir, fund_update_dir)

        self.assertEqual(audit.covered_months, [(2025, 1), (2025, 3)])
        self.assertEqual(audit.missing_months, [(2025, 2)])
        self.assertEqual(audit.problems, [])

    def test_reads_multi_month_csv_by_row_content(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_dir = Path(tmpdir)
            fund_update_dir = csv_dir / "fund_updates"
            fund_update_dir.mkdir()
            write_csv(csv_dir / "2025-06-07.csv", [(2025, 6), (2025, 7)])
            write_csv(csv_dir / "2025-08.csv", [(2025, 8)])
            write_fund_update_pdf(fund_update_dir / "2025-02-01-general-fund-update.pdf", 2024, 2)

            audit = audit_register_archive(csv_dir, fund_update_dir)

        self.assertEqual(audit.covered_months, [(2025, 6), (2025, 7), (2025, 8)])
        self.assertEqual(audit.missing_months, [])

    def test_format_lists_missing_months(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_dir = Path(tmpdir)
            fund_update_dir = csv_dir / "fund_updates"
            fund_update_dir.mkdir()
            write_csv(csv_dir / "2025-01.csv", [(2025, 1)])
            write_csv(csv_dir / "2025-03.csv", [(2025, 3)])
            write_fund_update_pdf(fund_update_dir / "2025-02-01-general-fund-update.pdf", 2024, 2)
            audit = audit_register_archive(csv_dir, fund_update_dir)

        lines = format_archive_audit(audit)
        self.assertIn("Missing check register months:", lines)
        self.assertIn(f"  {month_label((2025, 2))}", lines)

    def test_cli_exits_nonzero_when_months_are_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_dir = Path(tmpdir)
            fund_update_dir = csv_dir / "fund_updates"
            fund_update_dir.mkdir()
            write_csv(csv_dir / "2025-01.csv", [(2025, 1)])
            write_csv(csv_dir / "2025-03.csv", [(2025, 3)])
            write_fund_update_pdf(fund_update_dir / "2025-02-01-general-fund-update.pdf", 2024, 2)
            with io.StringIO() as buf, contextlib.redirect_stdout(buf):
                with self.assertRaises(SystemExit) as cm:
                    main([
                        "--audit-archive",
                        "--archive-csv-dir",
                        str(csv_dir),
                        "--archive-fund-update-dir",
                        str(fund_update_dir),
                    ])
                output = buf.getvalue()

        self.assertEqual(cm.exception.code, 1)
        self.assertIn("2025-02", output)

    def test_cli_exits_zero_when_no_months_are_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_dir = Path(tmpdir)
            fund_update_dir = csv_dir / "fund_updates"
            fund_update_dir.mkdir()
            write_csv(csv_dir / "2025-01.csv", [(2025, 1)])
            write_csv(csv_dir / "2025-02.csv", [(2025, 2)])
            write_fund_update_pdf(fund_update_dir / "2025-02-01-general-fund-update.pdf", 2024, 2)
            with io.StringIO() as buf, contextlib.redirect_stdout(buf):
                main([
                    "--audit-archive",
                    "--archive-csv-dir",
                    str(csv_dir),
                    "--archive-fund-update-dir",
                    str(fund_update_dir),
                ])
                output = buf.getvalue()

        self.assertIn("Missing check register months: none", output)

    def test_finds_missing_quarter_between_fund_update_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            csv_dir = root / "csv"
            fund_update_dir = root / "fund_updates"
            csv_dir.mkdir()
            fund_update_dir.mkdir()
            write_csv(csv_dir / "2025-01.csv", [(2025, 1)])
            write_fund_update_pdf(fund_update_dir / "2025-02-01-general-fund-update.pdf", 2024, 2)
            write_fund_update_pdf(fund_update_dir / "2025-09-01-general-fund-update.pdf", 2024, 4)

            audit = audit_register_archive(csv_dir, fund_update_dir)

        self.assertEqual(audit.covered_quarters, [(2024, 2), (2024, 4)])
        self.assertEqual(audit.missing_quarters, [(2024, 3)])

    def test_format_lists_missing_quarterly_fund_updates(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            csv_dir = root / "csv"
            fund_update_dir = root / "fund_updates"
            csv_dir.mkdir()
            fund_update_dir.mkdir()
            write_csv(csv_dir / "2025-01.csv", [(2025, 1)])
            write_fund_update_pdf(fund_update_dir / "2025-02-01-general-fund-update.pdf", 2024, 2)
            write_fund_update_pdf(fund_update_dir / "2025-09-01-general-fund-update.pdf", 2024, 4)

            audit = audit_register_archive(csv_dir, fund_update_dir)

        lines = format_archive_audit(audit)
        self.assertIn("Missing quarterly fund updates:", lines)
        self.assertIn(f"  {quarter_label((2024, 3))}", lines)

    def test_flags_fund_update_without_report_anchor(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            csv_dir = root / "csv"
            fund_update_dir = root / "fund_updates"
            csv_dir.mkdir()
            fund_update_dir.mkdir()
            write_csv(csv_dir / "2025-01.csv", [(2025, 1)])
            build_pdf(
                fund_update_dir / "2025-02-01-general-fund-update.pdf",
                ["Agenda summary mentioning General Fund Budget Update"],
            )

            audit = audit_register_archive(csv_dir, fund_update_dir)

        self.assertEqual(audit.covered_quarters, [])
        self.assertEqual(audit.missing_quarters, [])
        self.assertIn("no fund update report anchor found", audit.problems[0])


if __name__ == "__main__":
    unittest.main()
