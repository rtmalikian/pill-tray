"""Tray photo detection: segment pills, read their visual features.

This is deliberately simple, deterministic vision: a tray background
that differs from every pill colour, connected components over the
colour-distance mask, and per-component feature extraction (dominant
colour, shape class from the bounding box, size bucket from area, and a
marking estimate from the dark imprint pixels inside the component).

What it is not: a pill detector for arbitrary real photos. Real trays
have shadows, glare, overlapping pills, and printed text this code
cannot read. The synthetic fixtures in ``synth.py`` exist so the eval
harness can measure the *matching and diff logic* against known ground
truth. The detector's limits are stated in SECURITY.md, and the API also
accepts detector-style descriptors directly, for deployments where a
real detector/OCR front end does this step.
"""

from __future__ import annotations

import io

import numpy as np
from PIL import Image

from app.pilltray import features

#: Palette the renderer uses and the detector names against.
PALETTE: dict[str, tuple[int, int, int]] = {
    "white": (245, 245, 238),
    "yellow": (238, 198, 60),
    "pink": (233, 148, 170),
    "blue": (108, 158, 224),
    "orange": (240, 148, 58),
    "green": (128, 198, 128),
    "purple": (168, 138, 218),
    "peach": (244, 198, 148),
}

MIN_COMPONENT_AREA = 200
BG_DISTANCE = 42.0


def load_image(data: bytes) -> np.ndarray:
    img = Image.open(io.BytesIO(data)).convert("RGB")
    return np.asarray(img).astype(np.int32)


def encode_png(arr: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(arr.astype(np.uint8)).save(buf, format="PNG")
    return buf.getvalue()


def _label_components(mask: np.ndarray) -> list[dict]:
    """Run-length connected components over a boolean mask (4-connectivity
    via row runs). Returns [{bbox, area, pixels}] with pixels as (ys, xs)
    index arrays. Good enough for separated pills on a tray; pills that
    touch merge into one component, which the area check then rejects
    downstream as an oversize blob."""
    h, w = mask.shape
    parent: list[int] = []

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    runs: list[tuple[int, int, int, int]] = []  # (y, x0, x1, label)
    prev_row: list[tuple[int, int, int, int]] = []
    for y in range(h):
        row = mask[y]
        cur_row: list[tuple[int, int, int, int]] = []
        x = 0
        while x < w:
            if row[x]:
                x0 = x
                while x < w and row[x]:
                    x += 1
                label = len(parent)
                parent.append(label)
                for (_py, px0, px1, plabel) in prev_row:
                    # Overlap (with 1px tolerance) with a run directly
                    # above means the same component.
                    if px0 <= x and x0 - 1 <= px1:
                        union(label, plabel)
                run = (y, x0, x - 1, label)
                runs.append(run)
                cur_row.append(run)
            else:
                x += 1
        prev_row = cur_row

    comps: dict[int, dict] = {}
    for (y, x0, x1, label) in runs:
        root = find(label)
        c = comps.setdefault(root, {"ys": [], "xs": []})
        c["ys"].extend([y] * (x1 - x0 + 1))
        c["xs"].extend(range(x0, x1 + 1))
    out = []
    for c in comps.values():
        ys = np.array(c["ys"])
        xs = np.array(c["xs"])
        out.append({
            "area": int(len(ys)),
            "bbox": (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())),
            "ys": ys, "xs": xs,
        })
    return [c for c in out if c["area"] >= MIN_COMPONENT_AREA]


def _nearest_colour(rgb: np.ndarray) -> str:
    best, best_d = "unknown", 1e18
    for name, ref in PALETTE.items():
        d = float(np.sum((rgb - np.array(ref)) ** 2))
        if d < best_d:
            best, best_d = name, d
    return best


def _shape_of(bbox: tuple[int, int, int, int], area: int) -> str:
    """Shape from bounding-box geometry. An ellipse fills ~0.79 of its
    bounding box; a capsule (rounded rectangle) fills ~0.90. That gap is
    what separates oval from oblong here."""
    x0, y0, x1, y1 = bbox
    w = x1 - x0 + 1
    h = y1 - y0 + 1
    aspect = w / max(1, h)
    extent = area / max(1, w * h)
    if 0.80 <= aspect <= 1.25:
        return "round"
    if extent > 0.85:
        return "oblong"
    return "oval"


def _size_of(area: int) -> str:
    if area < 800:
        return "S"
    if area < 1500:
        return "M"
    return "L"


def detect_pills(arr: np.ndarray) -> list[dict]:
    """Detect pills in a tray image array (RGB int32). Returns a list of
    observed-pill dicts with detector features, sorted left-to-right,
    top-to-bottom, each with a stable ``obs_id``."""
    corners = np.array([arr[0, 0], arr[0, -1], arr[-1, 0], arr[-1, -1]])
    bg = np.median(corners, axis=0)
    dist = np.sqrt(np.sum((arr - bg) ** 2, axis=2))
    mask = dist > BG_DISTANCE
    comps = _label_components(mask)
    pills = []
    for c in comps:
        if c["area"] > 4000:
            # A blob far bigger than any pill: merged/touching pills or a
            # tray artefact. Skipping it makes the tray under-count, which
            # the diff then surfaces as missing, rather than hallucinating
            # a giant pill. Stated here because it is a real failure mode.
            continue
        ys, xs = c["ys"], c["xs"]
        pixels = arr[ys, xs]
        mean_rgb = pixels.mean(axis=0)
        colour = _nearest_colour(mean_rgb)
        lum = pixels.mean(axis=1)
        pill_lum = float(lum.mean())
        marking_exact = int(np.sum(lum < pill_lum - 55))
        pills.append({
            "bbox": [int(v) for v in c["bbox"]],
            "area_px": c["area"],
            "colour": colour,
            "shape": _shape_of(c["bbox"], c["area"]),
            "size": _size_of(c["area"]),
            "marking_exact": marking_exact,
            "marking_bucket": features.marking_bucket(marking_exact,
                                                       from_px=True),
        })
    pills.sort(key=lambda p: (p["bbox"][1], p["bbox"][0]))
    for i, p in enumerate(pills):
        p["obs_id"] = f"obs-{i + 1}"
    return pills
