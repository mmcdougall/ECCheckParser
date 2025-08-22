from __future__ import annotations

import csv
import json
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from typing import Dict, List

from .models import CheckEntry


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


def write_payee_quadtree_html(entries: List[CheckEntry], out_path: Path) -> None:
    """Write an HTML quadtree of payees sized by total dollar amount.

    Rectangles are colored using a linear ramp so larger dollar amounts
    stand out.
    """
    from bokeh.models import ColumnDataSource, HoverTool
    from bokeh.palettes import Viridis256
    from bokeh.plotting import figure, output_file, save
    from bokeh.transform import linear_cmap

    totals: Dict[str, Decimal] = {}
    for e in entries:
        if e.voided:
            continue
        totals[e.payee] = totals.get(e.payee, Decimal("0.00")) + e.amount

    items = [(name, float(amount)) for name, amount in totals.items() if float(amount) > 0]

    def greedy_split_2(items):
        left_group, right_group, sum_left, sum_right = [], [], 0.0, 0.0
        for label, weight in sorted(items, key=lambda t: t[1], reverse=True):
            if sum_left <= sum_right:
                left_group.append((label, weight))
                sum_left += weight
            else:
                right_group.append((label, weight))
                sum_right += weight
        return left_group, right_group, sum_left, sum_right

    def greedy_split_4(items):
        left_items, right_items, sum_left, sum_right = greedy_split_2(items)
        top_left, bottom_left, sum_top_left, sum_bottom_left = (
            greedy_split_2(left_items) if left_items else ([], [], 0, 0)
        )
        top_right, bottom_right, sum_top_right, sum_bottom_right = (
            greedy_split_2(right_items) if right_items else ([], [], 0, 0)
        )
        return {
            "NW": (top_left, sum_top_left),
            "SW": (bottom_left, sum_bottom_left),
            "NE": (top_right, sum_top_right),
            "SE": (bottom_right, sum_bottom_right),
        }, (sum_left, sum_right)

    rects: List[Dict[str, float]] = []

    def draw(items, x, y, width, height):
        total = sum(value for _, value in items)
        if not items or total <= 0:
            return
        if len(items) == 1:
            label, val = items[0]
            rects.append({"label": label, "value": val, "x": x, "y": y, "w": width, "h": height})
            return
        groups, (sum_left, sum_right) = greedy_split_4(items)
        left_fraction = sum_left / total if total else 0.5
        split_x = width * left_fraction
        top_fraction_left = groups["NW"][1] / sum_left if sum_left else 0.5
        top_fraction_right = groups["NE"][1] / sum_right if sum_right else 0.5
        top_height_left = height * top_fraction_left
        bottom_height_left = height - top_height_left
        top_height_right = height * top_fraction_right
        bottom_height_right = height - top_height_right
        draw(groups["NW"][0], x, y + height - top_height_left, split_x, top_height_left)
        draw(groups["SW"][0], x, y, split_x, bottom_height_left)
        draw(
            groups["NE"][0],
            x + split_x,
            y + height - top_height_right,
            width - split_x,
            top_height_right,
        )
        draw(groups["SE"][0], x + split_x, y, width - split_x, bottom_height_right)

    draw(items, 0.0, 0.0, 1.0, 1.0)

    data = {
        "cx": [r["x"] + r["w"] / 2 for r in rects],
        "cy": [r["y"] + r["h"] / 2 for r in rects],
        "w": [r["w"] for r in rects],
        "h": [r["h"] for r in rects],
        "payee": [r["label"] for r in rects],
        "amount": [r["value"] for r in rects],
    }
    total_amount = sum(data["amount"])
    data["percent"] = [v / total_amount * 100 if total_amount else 0 for v in data["amount"]]

    source = ColumnDataSource(data)
    low = min(data["amount"]) if data["amount"] else 0
    high = max(data["amount"]) if data["amount"] else 1
    color_map = linear_cmap("amount", Viridis256, low, high)
    p = figure(width=960, height=600, x_range=(0, 1), y_range=(0, 1),
               toolbar_location="above", tools="pan,wheel_zoom,reset,save",
               outline_line_color=None, title=None)
    p.rect(x="cx", y="cy", width="w", height="h", source=source,
           line_color="white", line_width=1, fill_color=color_map, fill_alpha=0.9)
    hover = HoverTool(tooltips=[("Payee", "@payee"),
                                ("Total", "@amount{$0,0}"),
                                ("% of total", "@percent{0.0}%")])
    p.add_tools(hover)
    p.xgrid.grid_line_color = None
    p.ygrid.grid_line_color = None

    output_file(out_path, title="Payees by Dollar Amount")
    save(p)
