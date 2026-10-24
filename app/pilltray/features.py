"""Pill features and closed-set match scoring.

A pill, for matching purposes, is four visual features: colour, shape,
size, and an imprint-marking estimate. That is all the local pass needs,
because the search space is not 60,000 drugs. It is the patient's own
list, typically 5-10 medicines.

The coarse pass deliberately does NOT use the exact marking measurement.
Reading an imprint off a low-detail photo is exactly what a cheap pass
cannot do reliably, and pretending otherwise is how look-alike pills get
silently mis-matched. The coarse pass buckets the marking (few / some /
many). Two medicines that differ only in imprint therefore tie on the
coarse pass, and a tie is what triggers a VLM crop read (the escalation),
where the exact marking is available. Ambiguity is surfaced, never
guessed away.

Scoring weights (coarse, max 0.90):

- colour exact: 0.30
- shape exact: 0.25
- size exact: 0.15
- marking bucket exact: 0.20

A confident match needs score >= 0.75 with a margin >= 0.12 over the
runner-up. Anything else is ambiguous or unmatched, and the service
handles those two cases differently on purpose.
"""

from __future__ import annotations

MATCH_THRESHOLD = 0.75
MARGIN_THRESHOLD = 0.12

#: Rendering constant shared by the synthetic tray generator and the
#: detector: one imprint stroke is a 6x3 rectangle, 18 dark pixels.
STROKE_PX = 18


def marking_bucket(strokes_or_px: float, *, from_px: bool = False) -> str:
    """Bucket a marking estimate: few (<=2 strokes) / some (3-4) / many (>=5)."""
    strokes = strokes_or_px / STROKE_PX if from_px else strokes_or_px
    if strokes <= 2.4:
        return "few"
    if strokes <= 4.4:
        return "some"
    return "many"


def visual_descriptor(colour: str, shape: str, size: str, bucket: str) -> str:
    """Canonical descriptor string. This is what gets embedded (once, for
    the regimen) and compared: identical descriptors give identical
    embedding vectors on any backend, which is the exact-match fast path."""
    return f"{colour} {shape} pill, size {size}, imprint marks {bucket}"


def coarse_score(obs: dict, cand: dict) -> float:
    """Coarse agreement between an observed pill's features and a
    candidate medication's declared features. Both dicts carry colour,
    shape, size, and marking_bucket."""
    score = 0.0
    if obs.get("colour") == cand.get("colour"):
        score += 0.30
    if obs.get("shape") == cand.get("shape"):
        score += 0.25
    if obs.get("size") == cand.get("size"):
        score += 0.15
    if obs.get("marking_bucket") == cand.get("marking_bucket"):
        score += 0.20
    return round(score, 4)


def score_candidates(obs: dict, candidates: list[dict]) -> list[dict]:
    """Score an observed pill against every medication on the list.
    Returns entries sorted by score, each {med_id, score}."""
    scored = [{"med_id": c["med_id"], "score": coarse_score(obs, c)}
              for c in candidates]
    return sorted(scored, key=lambda s: -s["score"])


def classify(scored: list[dict]) -> str:
    """Classify a scored candidate list: confident | ambiguous | unmatched."""
    if not scored:
        return "unmatched"
    best = scored[0]["score"]
    second = scored[1]["score"] if len(scored) > 1 else 0.0
    if best < MATCH_THRESHOLD:
        return "unmatched"
    if second >= MATCH_THRESHOLD and best - second < MARGIN_THRESHOLD:
        return "ambiguous"
    return "confident"
