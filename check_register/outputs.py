from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Tuple

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


def group_payees(entries: List[CheckEntry]) -> Dict[str, List[CheckEntry]]:
    payees: Dict[str, List[CheckEntry]] = {}
    for e in entries:
        if e.voided:
            continue
        payees.setdefault(e.payee, []).append(e)
    return payees


def payee_totals(payees: Dict[str, List[CheckEntry]]) -> List[Tuple[str, float]]:
    items: List[Tuple[str, float]] = []
    for name, es in payees.items():
        total = float(sum(e.amount for e in es))
        if total > 0:
            items.append((name, total))
    return items


def greedy_split_two(items: List[Tuple[str, float]]):
    left, right, sum_left, sum_right = [], [], 0.0, 0.0
    for label, weight in sorted(items, key=lambda t: t[1], reverse=True):
        if sum_left <= sum_right:
            left.append((label, weight))
            sum_left += weight
        else:
            right.append((label, weight))
            sum_right += weight
    return left, right, sum_left, sum_right


def greedy_split_four(items: List[Tuple[str, float]]):
    left_items, right_items, sum_left, sum_right = greedy_split_two(items)
    tl, bl, sum_tl, sum_bl = greedy_split_two(left_items) if left_items else ([], [], 0, 0)
    tr, br, sum_tr, sum_br = greedy_split_two(right_items) if right_items else ([], [], 0, 0)
    groups = {"NW": (tl, sum_tl), "SW": (bl, sum_bl), "NE": (tr, sum_tr), "SE": (br, sum_br)}
    return groups, (sum_left, sum_right)


def layout_rectangles(
    items: List[Tuple[str, float]],
    x: float = 0.0,
    y: float = 0.0,
    width: float = 1.0,
    height: float = 1.0,
    rects: List[Dict[str, float]] | None = None,
) -> List[Dict[str, float]]:
    if rects is None:
        rects = []
    total = sum(value for _, value in items)
    if not items or total <= 0:
        return rects
    if len(items) == 1:
        label, val = items[0]
        rects.append({"label": label, "value": val, "x": x, "y": y, "w": width, "h": height})
        return rects
    groups, (sum_left, sum_right) = greedy_split_four(items)
    left_fraction = sum_left / total if total else 0.5
    split_x = width * left_fraction
    top_fraction_left = groups["NW"][1] / sum_left if sum_left else 0.5
    top_fraction_right = groups["NE"][1] / sum_right if sum_right else 0.5
    top_height_left = height * top_fraction_left
    bottom_height_left = height - top_height_left
    top_height_right = height * top_fraction_right
    bottom_height_right = height - top_height_right
    layout_rectangles(groups["NW"][0], x, y + height - top_height_left, split_x, top_height_left, rects)
    layout_rectangles(groups["SW"][0], x, y, split_x, bottom_height_left, rects)
    layout_rectangles(
        groups["NE"][0],
        x + split_x,
        y + height - top_height_right,
        width - split_x,
        top_height_right,
        rects,
    )
    layout_rectangles(groups["SE"][0], x + split_x, y, width - split_x, bottom_height_right, rects)
    return rects


def assemble_quadtree_data(rects: List[Dict[str, float]], payees: Dict[str, List[CheckEntry]]):
    data = {"cx": [], "cy": [], "w": [], "h": [], "payee": [], "amount": [], "description": [], "checks": [], "label": []}
    for r in rects:
        payee = r["label"]
        info = payees[payee]
        descs = sorted({e.description for e in info if e.description})
        nums = [(e.number, e.amount) for e in info]
        checks = ", ".join(f"{n}: ${a:.2f}" for n, a in nums) if len({n for n, _ in nums}) > 1 else ""
        w, h = r["w"], r["h"]
        data["cx"].append(r["x"] + w / 2)
        data["cy"].append(r["y"] + h / 2)
        data["w"].append(w)
        data["h"].append(h)
        data["payee"].append(payee)
        data["amount"].append(r["value"])
        data["description"].append("; ".join(descs))
        data["checks"].append(checks)
        fits_w = w * 960 >= len(payee) * 7
        fits_h = h * 600 >= 14
        data["label"].append(payee if (fits_w and fits_h) else "")
    total = sum(data["amount"])
    data["percent"] = [v / total * 100 if total else 0 for v in data["amount"]]
    return data


def build_payee_quadtree_data(entries: List[CheckEntry]) -> Dict[str, List]:
    """Return ColumnDataSource-friendly data for the payee quadtree."""

    payees = group_payees(entries)
    items = payee_totals(payees)
    rects = layout_rectangles(items)
    return assemble_quadtree_data(rects, payees)


def make_quadtree_figure(data: Dict[str, List]):
    from bokeh.models import ColumnDataSource
    from bokeh.palettes import Viridis256
    from bokeh.transform import linear_cmap

    source = ColumnDataSource(data)
    low = min(data["amount"]) if data["amount"] else 0
    high = max(data["amount"]) if data["amount"] else 1
    color_map = linear_cmap("amount", Viridis256, low, high)
    return _build_quadtree_plot(source, color_map)


def _build_quadtree_plot(source, color_map):
    from bokeh.plotting import figure

    p = figure(
        width=960,
        height=600,
        x_range=(0, 1),
        y_range=(0, 1),
        toolbar_location="above",
        tools="pan,wheel_zoom,reset,save",
        outline_line_color=None,
        title=None,
    )
    _add_rectangles(p, source, color_map)
    _add_labels(p, source)
    _add_hover(p)
    p.xgrid.grid_line_color = None
    p.ygrid.grid_line_color = None
    return p


def _add_rectangles(p, source, color_map):
    p.rect(
        x="cx", y="cy", width="w", height="h", source=source,
        line_color="white", line_width=1, fill_color=color_map, fill_alpha=0.9,
    )


def _add_labels(p, source):
    p.text(
        x="cx", y="cy", text="label", source=source,
        text_align="center", text_baseline="middle",
        text_color="black", text_font_size="9pt",
    )


def _add_hover(p):
    from bokeh.models import HoverTool

    hover = HoverTool(
        tooltips=[
            ("Payee", "@payee"),
            ("Total", "@amount{$0,0}"),
            ("% of total", "@percent{0.0}%"),
            ("Description", "@description"),
            ("Checks", "@checks"),
        ]
    )
    p.add_tools(hover)


def write_payee_quadtree_html(entries: List[CheckEntry], out_path: Path) -> None:
    """Write an HTML quadtree of payees sized by total dollar amount."""
    from bokeh.plotting import output_file, save

    data = build_payee_quadtree_data(entries)
    plot = make_quadtree_figure(data)
    output_file(out_path, title="Payees by Dollar Amount")
    save(plot)
