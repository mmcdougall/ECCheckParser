import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from check_register.originals_audit import audit_originals
from check_register_parser import main


class TestOriginalsAudit(unittest.TestCase):
    def test_accepts_complete_category_first_archive(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            originals_dir = Path(tmpdir) / "originals"
            _write_meeting(originals_dir, "city-council", "agenda_packet")
            _write_meeting(originals_dir, "financial-advisory-board", "agenda")
            (originals_dir / ".DS_Store").write_bytes(b"")
            (originals_dir / "city-council/.DS_Store").write_bytes(b"")
            (originals_dir / "financial-advisory-board/2026/.DS_Store").write_bytes(b"")

            audit = audit_originals(originals_dir)

        self.assertEqual(audit.problems, [])
        self.assertEqual(audit.manifest_counts, {"city-council": 1, "financial-advisory-board": 1})
        self.assertEqual(audit.pdf_counts, {"city-council": 1, "financial-advisory-board": 1})
        self.assertEqual(audit.record_counts, {"city-council": 1, "financial-advisory-board": 1})

    def test_reports_source_integrity_problems(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            originals_dir = Path(tmpdir) / "originals"
            manifest_path, city_pdf = _write_meeting(originals_dir, "city-council", "agenda_packet")
            _write_meeting(originals_dir, "financial-advisory-board", "agenda")
            city_pdf.write_bytes(b"not a PDF")
            _write_pdf(city_pdf.parent / "orphan.pdf", b"orphan")
            (originals_dir / "2025").mkdir()

            audit = audit_originals(originals_dir)

        self.assertTrue(any(problem.startswith("SHA-256 mismatch") for problem in audit.problems))
        self.assertTrue(any(problem.startswith("Manifest PDF header is invalid") for problem in audit.problems))
        self.assertTrue(any(problem.startswith("Unreferenced PDF") for problem in audit.problems))
        self.assertTrue(any(problem.startswith("Unexpected originals root entry") for problem in audit.problems))

    def test_rejects_unsafe_manifest_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            originals_dir = Path(tmpdir) / "originals"
            manifest_path, _city_pdf = _write_meeting(originals_dir, "city-council", "agenda_packet")
            _write_meeting(originals_dir, "financial-advisory-board", "agenda")
            data = json.loads(manifest_path.read_text())
            data["meetings"][0]["documents"]["agenda_packet"]["current"]["path"] = "../escape.pdf"
            manifest_path.write_text(json.dumps(data))

            audit = audit_originals(originals_dir)

        self.assertTrue(any(problem.startswith("Unsafe document path") for problem in audit.problems))

    def test_cli_reports_current_originals_audit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            originals_dir = Path(tmpdir) / "originals"
            _write_meeting(originals_dir, "city-council", "agenda_packet")
            _write_meeting(originals_dir, "financial-advisory-board", "agenda")
            with io.StringIO() as buf, contextlib.redirect_stdout(buf):
                main(["--audit-originals", "--originals-dir", str(originals_dir)])
                output = buf.getvalue()

        self.assertIn("city-council: 1 manifests, 1 PDFs, 1 manifest records", output)
        self.assertIn("financial-advisory-board: 1 manifests, 1 PDFs, 1 manifest records", output)

    def test_cli_exits_nonzero_when_originals_are_invalid(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            originals_dir = Path(tmpdir) / "originals"
            with io.StringIO() as buf, contextlib.redirect_stdout(buf):
                with self.assertRaises(SystemExit) as cm:
                    main(["--audit-originals", "--originals-dir", str(originals_dir)])
                output = buf.getvalue()

        self.assertEqual(cm.exception.code, 1)
        self.assertIn("Originals directory not found", output)


def _write_meeting(originals_dir: Path, meeting_type: str, kind: str) -> tuple[Path, Path]:
    year_dir = originals_dir / meeting_type / "2026"
    directory, _revision_directory = {
        "agenda": ("agendas", "agenda-revisions"),
        "agenda_packet": ("agenda-packets", "agenda-packet-revisions"),
    }[kind]
    label = "Agenda" if kind == "agenda" else "Agenda Packet"
    pdf_path = year_dir / directory / f"2026-01-27 {label}.pdf"
    _write_pdf(pdf_path, f"{meeting_type} {kind}".encode())
    manifest_path = year_dir / "manifest.json"
    manifest = {
        "schema_version": 1,
        "year": 2026,
        "last_checked_at": "2026-01-27T20:00:00Z",
        "meetings": [
            {
                "meeting_date": "2026-01-27",
                "title": "Financial Advisory Board Meeting" if meeting_type.startswith("financial") else "City Council Meeting",
                "event_id": 1,
                "documents": {
                    kind: {
                        "current": _record(pdf_path, year_dir),
                        "revisions": [],
                    },
                },
            },
        ],
    }
    manifest_path.write_text(json.dumps(manifest))
    return manifest_path, pdf_path


def _record(path: Path, year_dir: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(year_dir).as_posix(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _write_pdf(path: Path, contents: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.7\n" + contents)
