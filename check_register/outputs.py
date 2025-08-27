from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path
from typing import List

from .models import CheckEntry, RowChunk


def write_csv(entries: List[CheckEntry], out_path: Path) -> None:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow([
            "section_month", "section_year", "ap_type", "number", "date",
            "status", "source", "payee", "description", "amount", "voided"
        ])
        for e in entries:
            w.writerow([
                e.section_month, e.section_year, e.ap_type, e.number, e.date,
                e.status, e.source, e.payee, e.description,
                f"{e.amount:.2f}", "Y" if e.voided else "N"
            ])


def write_json(entries: List[CheckEntry], out_path: Path) -> None:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(
            [
                {**asdict(e), "amount": float(e.amount)}  # JSON-friendly
                for e in entries
            ],
            f,
            ensure_ascii=False,
            indent=2,
        )


def write_chunks(chunks: List[RowChunk], out_path: Path) -> None:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump([asdict(c) for c in chunks], f, ensure_ascii=False, indent=2)
