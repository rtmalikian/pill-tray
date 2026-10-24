"""Synthetic tray fixtures with known ground truth.

These fixtures are how the eval harness measures the matching and diff
logic: a tray image is rendered from a declared list of pills, so the
correct set difference is known exactly, by construction.

Honesty note (repeated in the README): the pills are drawn shapes on a
flat tray, rendered by the same palette the detector names against.
The fixtures prove the pipeline computes the right diff from the
features it reads. They do not prove anything about real pill photos,
real imprint reading, glare, overlap, or the hundred other ways a real
tray is harder than this one. A labelled real-photo set is roadmap
issue #1.
"""

from __future__ import annotations

import io
import random

import numpy as np
from PIL import Image, ImageDraw

from app.pilltray.detector import PALETTE

TRAY_W, TRAY_H = 680, 460
TRAY_BG = (206, 211, 216)
_RADII = {"S": 13, "M": 18, "L": 24}


def _darken(rgb: tuple[int, int, int], factor: float = 0.5) -> tuple[int, int, int]:
    return tuple(int(c * factor) for c in rgb)


def _draw_pill(img: Image.Image, cx: int, cy: int, med: dict) -> None:
    """Draw one pill, with its imprint strokes clipped to the pill shape
    (strokes that spilled onto the tray would corrupt the marking count,
    which is the measurement the whole look-alike story rests on)."""
    colour = PALETTE[med["colour"]]
    r = _RADII[med.get("size", "M")]
    shape = med["shape"]
    if shape == "round":
        hw, hh = r, r
    elif shape == "oval":
        hw, hh = int(r * 1.35), int(r * 0.8)
    else:  # oblong / capsule
        hw, hh = int(r * 1.25), int(r * 0.62)
    layer = Image.new("RGB", (2 * hw + 2, 2 * hh + 2), TRAY_BG)
    mask = Image.new("L", layer.size, 0)
    ld = ImageDraw.Draw(layer)
    md = ImageDraw.Draw(mask)
    box = [1, 1, 2 * hw, 2 * hh]
    if shape == "oblong":
        ld.rounded_rectangle(box, radius=hh, fill=colour)
        md.rounded_rectangle(box, radius=hh, fill=255)
    else:
        ld.ellipse(box, fill=colour)
        md.ellipse(box, fill=255)
    # Imprint marks: dark strokes across the centre, each a 6x3 rectangle
    # (18 px), the marking measurement the detector counts. If the
    # strokes do not fit on one row inside the pill, stack them in rows
    # (a single row wider than the pill would clip and corrupt the
    # count, which is exactly the measurement the matcher rests on).
    strokes = int(med.get("marking_strokes", 2))
    dark = _darken(colour)
    per_row = max(1, (2 * hw) // 10)
    n_rows = (strokes + per_row - 1) // per_row
    rows = [min(per_row, strokes - i * per_row) for i in range(n_rows)]
    row_offsets = [int((i - (len(rows) - 1) / 2) * 6) for i in range(len(rows))]
    for n_in_row, dy in zip(rows, row_offsets):
        total_w = n_in_row * 6 + max(0, n_in_row - 1) * 4
        x = hw + 1 - total_w // 2
        for _ in range(n_in_row):
            ld.rectangle([x, hh + dy, x + 5, hh + dy + 2], fill=dark)
            x += 10
    img.paste(layer, (cx - hw - 1, cy - hh - 1), mask)


def make_tray(items: list[dict], seed: int = 7) -> dict:
    """Render a tray holding ``items``: a list of medication dicts (the
    same shape as Medication fields), one entry per pill. Returns
    {png, truth} where truth maps med id (or the item's ``key``) to the
    pill count rendered."""
    rng = random.Random(seed)
    img = Image.new("RGB", (TRAY_W, TRAY_H), TRAY_BG)
    cols = 4
    cell_w, cell_h = TRAY_W // cols, 92
    truth: dict[str, int] = {}
    for i, med in enumerate(items):
        row, col = divmod(i, cols)
        cx = col * cell_w + cell_w // 2 + rng.randint(-14, 14)
        cy = row * cell_h + cell_h // 2 + 10 + rng.randint(-8, 8)
        _draw_pill(img, cx, cy, med)
        key = med.get("id") or med.get("key") or med["name"]
        truth[key] = truth.get(key, 0) + 1
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return {"png": buf.getvalue(), "truth": truth}


# ---------------------------------------------------------------------------
# Standard fixture regimen (synthetic medicines, not real prescriptions)
#
# Lisinopril and Amlodipine below are a deliberate look-alike pair: same
# colour, shape, and size, imprint marks 3 vs 4, which fall in the same
# coarse bucket. The coarse pass cannot separate them; only a crop read
# can. Trays containing either one are the battery's ambiguous minority.
# ---------------------------------------------------------------------------

STANDARD_MEDICATIONS: list[dict] = [
    {"id": "med-1", "name": "Lisinopril (fixture)", "strength": "10 mg",
     "form": "tablet", "colour": "white", "shape": "round", "size": "M",
     "marking_strokes": 3, "expected_count": 2},
    {"id": "med-2", "name": "Amlodipine (fixture)", "strength": "5 mg",
     "form": "tablet", "colour": "white", "shape": "round", "size": "M",
     "marking_strokes": 4, "expected_count": 1},
    {"id": "med-3", "name": "Atorvastatin (fixture)", "strength": "20 mg",
     "form": "tablet", "colour": "yellow", "shape": "oval", "size": "L",
     "marking_strokes": 2, "expected_count": 1},
    {"id": "med-4", "name": "Omeprazole (fixture)", "strength": "20 mg",
     "form": "capsule", "colour": "purple", "shape": "oblong", "size": "M",
     "marking_strokes": 2, "expected_count": 2},
    {"id": "med-5", "name": "Aspirin (fixture)", "strength": "81 mg",
     "form": "tablet", "colour": "orange", "shape": "round", "size": "S",
     "marking_strokes": 1, "expected_count": 1},
]

#: A pill that is on nobody's list: the battery's unexpected item.
UNKNOWN_PILL: dict = {"id": "unknown-1", "name": "Unknown blue pill",
                      "colour": "blue", "shape": "round", "size": "M",
                      "marking_strokes": 2}


def _expand(counts: dict[str, int],
            meds: list[dict] = STANDARD_MEDICATIONS) -> list[dict]:
    by_id = {m["id"]: m for m in meds}
    items: list[dict] = []
    for med_id, n in counts.items():
        items.extend([by_id[med_id]] * n)
    return items


def full_counts() -> dict[str, int]:
    return {m["id"]: m["expected_count"] for m in STANDARD_MEDICATIONS}


#: Eval battery scenarios over the standard regimen. Each entry:
#: (scenario name, tray counts by med id, extra items, planted events)
#: An "event" is one ground-truth difference the diff must surface:
#: ("missing", med_id) / ("count", med_id) / ("duplicate", med_id) /
#: ("unexpected", key). Clean trays plant no events but still exercise
#: the matcher (including the look-alike pair in the standard set).
SCENARIOS: list[dict] = [
    {"name": "std-clean", "counts": full_counts(), "extra": [], "events": []},
    {"name": "std-missing-atorvastatin",
     "counts": {**full_counts(), "med-3": 0}, "extra": [],
     "events": [("missing", "med-3")]},
    {"name": "std-short-lisinopril",
     "counts": {**full_counts(), "med-1": 1}, "extra": [],
     "events": [("count", "med-1")]},
    {"name": "std-duplicate-omeprazole",
     "counts": {**full_counts(), "med-4": 3}, "extra": [],
     "events": [("duplicate", "med-4")]},
    {"name": "std-unexpected-blue",
     "counts": full_counts(), "extra": [UNKNOWN_PILL],
     "events": [("unexpected", "unknown-1")]},
    {"name": "std-missing-aspirin-and-extra-aspirin",
     "counts": {**full_counts(), "med-5": 2}, "extra": [],
     "events": [("duplicate", "med-5")]},
]


def make_scenario(sc: dict, seed: int = 11) -> dict:
    items = _expand(sc["counts"]) + list(sc.get("extra", []))
    tray = make_tray(items, seed=seed)
    return {"png": tray["png"], "truth": tray["truth"],
            "events": sc["events"], "name": sc["name"]}


# ---------------------------------------------------------------------------
# Simple fixture regimen: no look-alike pair. Every medicine differs from
# every other in at least two coarse features, so a correct tray resolves
# on the local pass with zero VLM calls. This is the battery's majority,
# and the README says so: trays containing a same-colour/shape/size
# look-alike pair are the ambiguous minority (the standard regimen above).
# ---------------------------------------------------------------------------

SIMPLE_MEDICATIONS: list[dict] = [
    {"id": "med-s1", "name": "Vitamin D (fixture)", "strength": "1000 IU",
     "form": "tablet", "colour": "pink", "shape": "round", "size": "S",
     "marking_strokes": 5, "expected_count": 2},
    {"id": "med-s2", "name": "Atorvastatin (fixture)", "strength": "20 mg",
     "form": "tablet", "colour": "yellow", "shape": "oval", "size": "L",
     "marking_strokes": 2, "expected_count": 1},
    {"id": "med-s3", "name": "Omeprazole (fixture)", "strength": "20 mg",
     "form": "capsule", "colour": "purple", "shape": "oblong", "size": "M",
     "marking_strokes": 2, "expected_count": 2},
    {"id": "med-s4", "name": "Cetirizine (fixture)", "strength": "10 mg",
     "form": "tablet", "colour": "green", "shape": "oval", "size": "S",
     "marking_strokes": 1, "expected_count": 1},
]


def simple_full_counts() -> dict[str, int]:
    return {m["id"]: m["expected_count"] for m in SIMPLE_MEDICATIONS}


SIMPLE_SCENARIOS: list[dict] = [
    {"name": "simple-clean-a", "counts": simple_full_counts(), "extra": [],
     "events": []},
    {"name": "simple-clean-b", "counts": simple_full_counts(), "extra": [],
     "events": []},
    {"name": "simple-clean-c", "counts": simple_full_counts(), "extra": [],
     "events": []},
    {"name": "simple-missing-vitd",
     "counts": {**simple_full_counts(), "med-s1": 0}, "extra": [],
     "events": [("missing", "med-s1")]},
    {"name": "simple-missing-omeprazole",
     "counts": {**simple_full_counts(), "med-s3": 0}, "extra": [],
     "events": [("missing", "med-s3")]},
    {"name": "simple-short-omeprazole",
     "counts": {**simple_full_counts(), "med-s3": 1}, "extra": [],
     "events": [("count", "med-s3")]},
    {"name": "simple-duplicate-cetirizine",
     "counts": {**simple_full_counts(), "med-s4": 2}, "extra": [],
     "events": [("duplicate", "med-s4")]},
    {"name": "simple-duplicate-atorvastatin",
     "counts": {**simple_full_counts(), "med-s2": 2}, "extra": [],
     "events": [("duplicate", "med-s2")]},
    {"name": "simple-unexpected-blue",
     "counts": simple_full_counts(), "extra": [UNKNOWN_PILL],
     "events": [("unexpected", "unknown-1")]},
    {"name": "simple-missing-vitd-unexpected-blue",
     "counts": {**simple_full_counts(), "med-s1": 0},
     "extra": [UNKNOWN_PILL],
     "events": [("missing", "med-s1"), ("unexpected", "unknown-1")]},
]


def make_simple_scenario(sc: dict, seed: int = 21) -> dict:
    items = _expand(sc["counts"], SIMPLE_MEDICATIONS) + list(sc.get("extra", []))
    tray = make_tray(items, seed=seed)
    return {"png": tray["png"], "truth": tray["truth"],
            "events": sc["events"], "name": sc["name"]}
