import contextlib
import io
import tempfile
import unittest
from pathlib import Path

import pdfplumber

from fund_update.page_extractor import (
    default_fund_update_pdf_name,
    extract_fund_update_pdf,
    find_fund_update_pages,
)
from fund_update_parser import main as fund_update_main


class FundUpdatePdfBuilder:
    def __init__(self, texts: list[str]):
        if not texts:
            raise ValueError("PDF must contain at least one page")
        self.texts = texts

    @staticmethod
    def _escape(text: str) -> str:
        return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    @classmethod
    def _stream(cls, text: str) -> bytes:
        lines = text.split("\n")
        commands: list[str] = ["BT", "/F1 16 Tf", "72 720 Td"]
        for idx, line in enumerate(lines):
            escaped = cls._escape(line)
            if idx == 0:
                commands.append(f"({escaped}) Tj")
            else:
                commands.append("0 -20 Td")
                commands.append(f"({escaped}) Tj")
        commands.append("ET")
        content = "\n".join(commands).encode("utf-8")
        header = f"<< /Length {len(content)} >>\n".encode("ascii")
        return header + b"stream\n" + content + b"\nendstream\n"

    def write(self, path: Path) -> None:
        num_pages = len(self.texts)
        font_obj = 3 + 2 * num_pages
        data = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = [0]

        def add_obj(obj_id: int, body: bytes) -> None:
            offsets.append(len(data))
            data.extend(f"{obj_id} 0 obj\n".encode("ascii"))
            data.extend(body)
            if not body.endswith(b"\n"):
                data.extend(b"\n")
            data.extend(b"endobj\n")

        add_obj(1, b"<< /Type /Catalog /Pages 2 0 R >>\n")
        kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(num_pages)).encode("ascii")
        add_obj(2, b"<< /Type /Pages /Kids [" + kids + f"] /Count {num_pages} >>\n".encode("ascii"))
        for idx, text in enumerate(self.texts):
            page_id = 3 + 2 * idx
            contents_id = page_id + 1
            page_dict = (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 {font_obj} 0 R >> >> /Contents {contents_id} 0 R >>\n"
            ).encode("ascii")
            add_obj(page_id, page_dict)
            add_obj(contents_id, self._stream(text))
        add_obj(font_obj, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\n")

        xref_offset = len(data)
        data.extend(f"xref\n0 {font_obj + 1}\n".encode("ascii"))
        data.extend(b"0000000000 65535 f \n")
        for offset in offsets[1:]:
            data.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
        data.extend(
            f"trailer\n<< /Size {font_obj + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode("ascii")
        )
        path.write_bytes(bytes(data))


def build_pdf(path: Path, texts: list[str]) -> None:
    FundUpdatePdfBuilder(texts).write(path)


class TestFundUpdateExtractor(unittest.TestCase):
    def test_find_and_extract_pages(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            pdf_path = tmp / "Agenda Packet (rev. 9.25.2025).pdf"
            build_pdf(
                pdf_path,
                [
                    "City Council Meeting",
                    "General Fund Budget Update\nQ1 Results",
                    "General fund\nBudget update details",  # mixed case and spacing
                    "Other agenda item",
                ],
            )
            pages = find_fund_update_pages(pdf_path)
            self.assertEqual(pages, [2, 3])

            out_path = tmp / "fund-update.pdf"
            extracted = extract_fund_update_pdf(pdf_path, out_path)
            self.assertEqual(extracted, [2, 3])

            with pdfplumber.open(out_path) as pdf:
                self.assertEqual(len(pdf.pages), 2)
                texts = [page.extract_text().strip() for page in pdf.pages]
                self.assertIn("General Fund Budget Update", texts[0])

    def test_no_update_pages(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pdf_path = Path(tmpdir) / "packet.pdf"
            build_pdf(pdf_path, ["Consent calendar", "Staff report"])
            with self.assertRaises(ValueError):
                find_fund_update_pages(pdf_path)

    def test_default_name(self):
        pdf_path = Path("Agenda Packet (rev. 9.25.2025).pdf")
        self.assertEqual(
            default_fund_update_pdf_name(pdf_path),
            Path("2025-09-25-general-fund-update.pdf"),
        )
        self.assertIsNone(default_fund_update_pdf_name(Path("packet.pdf")))

    def test_cli_default_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            pdf_path = tmp / "Agenda Packet (rev. 9.25.2025).pdf"
            build_pdf(pdf_path, ["General Fund Budget Update"])
            artifact_dir = tmp / "artifacts"
            argv = [
                str(pdf_path),
                "--artifact-dir",
                str(artifact_dir),
            ]
            with contextlib.redirect_stdout(io.StringIO()):
                fund_update_main(argv)
            out_path = artifact_dir / "2025-09-25-general-fund-update.pdf"
            self.assertTrue(out_path.exists())

    def test_cli_requires_output_hint(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            pdf_path = tmp / "packet.pdf"
            build_pdf(pdf_path, ["General Fund Budget Update"])
            out_path = tmp / "update.pdf"
            argv = [
                str(pdf_path),
                "--out",
                str(out_path),
            ]
            with contextlib.redirect_stdout(io.StringIO()):
                fund_update_main(argv)
            self.assertTrue(out_path.exists())


if __name__ == "__main__":
    unittest.main()
