"""Regimens (the expected set) and tray reports. In-memory in v0.1.0,
like Weeks 1-3.

The regimen is the product's whole premise: a short list a clinician or
pharmacist already has, against which a photo is checked. The regimen's
visual descriptors are embedded once, through the gateway, and cached on
the regimen object. Every later tray check reuses those vectors.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field

from app.pilltray import features


@dataclass
class Medication:
    id: str
    name: str
    strength: str
    form: str                 # tablet | capsule
    colour: str               # palette name, e.g. "white"
    shape: str                # round | oval | oblong
    size: str                 # S | M | L
    marking_strokes: int      # imprint marks on the reference pill
    expected_count: int       # pills expected in the tray photo

    def candidate(self) -> dict:
        """The closed-set candidate dict the matcher scores against."""
        return {
            "med_id": self.id,
            "name": self.name,
            "colour": self.colour,
            "shape": self.shape,
            "size": self.size,
            "marking_bucket": features.marking_bucket(self.marking_strokes),
            "marking_exact": self.marking_strokes * features.STROKE_PX,
        }

    def descriptor(self) -> str:
        return features.visual_descriptor(
            self.colour, self.shape, self.size,
            features.marking_bucket(self.marking_strokes))

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "strength": self.strength,
            "form": self.form, "colour": self.colour, "shape": self.shape,
            "size": self.size, "marking_strokes": self.marking_strokes,
            "expected_count": self.expected_count,
            "descriptor": self.descriptor(),
        }


@dataclass
class Regimen:
    id: str
    label: str                       # redacted before it reaches here
    medications: list[Medication]
    created_at: float = field(default_factory=time.time)
    embeddings: dict[str, list[float]] = field(default_factory=dict)
    embedding_calls_at_build: int = 0
    reports: list[dict] = field(default_factory=list)

    def candidates(self) -> list[dict]:
        return [m.candidate() for m in self.medications]

    def med_by_id(self, med_id: str) -> Medication | None:
        for m in self.medications:
            if m.id == med_id:
                return m
        return None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "created_at": self.created_at,
            "medications": [m.to_dict() for m in self.medications],
            "embeddings_cached": sorted(self.embeddings.keys()),
            "embedding_calls_at_build": self.embedding_calls_at_build,
            "expected_total": sum(m.expected_count for m in self.medications),
            "reports": len(self.reports),
        }


def new_regimen(label: str, medications: list[dict]) -> Regimen:
    meds = []
    for i, m in enumerate(medications):
        meds.append(Medication(
            id=m.get("id") or f"med-{i + 1}",
            name=m["name"],
            strength=m.get("strength", ""),
            form=m.get("form", "tablet"),
            colour=m["colour"],
            shape=m["shape"],
            size=m.get("size", "M"),
            marking_strokes=int(m.get("marking_strokes", 2)),
            expected_count=int(m.get("expected_count", 1)),
        ))
    return Regimen(id=f"reg-{uuid.uuid4().hex[:8]}", label=label,
                   medications=meds)
