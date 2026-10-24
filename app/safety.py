"""PHI/PII redaction gate + medication-advice language check.

Two jobs:

1. Redaction. Nothing that looks like patient-identifiable information may
   reach logs, stored artifacts, or (in upstream mode) a third-party model
   provider without passing through ``redact_phi`` first. Logs carry
   *kinds* only (e.g. ``{"phi_kinds": ["PHONE"]}``), never values.

2. Advice language. PillTray is a reconciliation aid for a pharmacist,
   clinician, or patient to review. It never gives medication advice.
   ``find_advice_language`` scans every product-facing string for phrases
   like "safe to take" or "stop taking" so tests can fail the build if
   advice language ever slips into a summary or template.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger("pill-tray.safety")

_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")),
    ("SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("DOB", re.compile(
        r"\b(?:DOB|D\.O\.B\.|Date of Birth)\s*[:.]?\s*\d{1,2}[/-]\d{1,2}[/-]\d{2,4}",
        re.IGNORECASE)),
    ("MRN", re.compile(
        r"\b(?:MRN|Medical Record|Account|Acct)\s*#?\s*[:.]?\s*[\w-]{3,}\b",
        re.IGNORECASE)),
    # MEMBER_ID runs before PHONE: member IDs are digit-heavy and the phone
    # pattern would otherwise eat their tails first.
    ("MEMBER_ID", re.compile(
        r"\b(?:Member|Subscriber)\s*(?:ID|#|No\.?)?\s*[:.]?\s*[A-Z0-9][\w-]{4,}\b",
        re.IGNORECASE)),
    ("PHONE", re.compile(r"(?<!\d)(\+?1[-.\s]?)?(\(?\d{3}\)?[-.\s]?)?\d{3}[-.\s]?\d{4}(?!\d)")),
    ("ADDRESS", re.compile(
        r"\b\d{1,5}\s+[A-Z][a-zA-Z]+\s+"
        r"(?:St|Street|Ave|Avenue|Rd|Road|Blvd|Drive|Dr|Ln|Lane|Way|Ct|Court)\b.*",
        re.IGNORECASE)),
    ("NAME", re.compile(
        r"\b(?:Patient(?: Name)?|Pt\.?|Name)\s*:\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})")),
]


def redact_phi(text: str) -> tuple[str, dict[str, int]]:
    """Return ``(redacted_text, report)``.

    ``report`` maps PHI kind -> count of redactions. The redacted text keeps
    a ``[KIND]`` placeholder so downstream structure survives without the
    values.
    """
    report: dict[str, int] = {}
    redacted = text or ""
    for kind, pattern in _PATTERNS:
        redacted, n = pattern.subn(f"[{kind}]", redacted)
        if n:
            report[kind] = report.get(kind, 0) + n
    if report:
        # Kinds only -- never values.
        logger.info("phi_redacted", extra={"phi_kinds": sorted(report.keys()),
                                           "phi_counts": report})
    return redacted, report


def looks_like_phi(text: str) -> list[str]:
    """Return the PHI kinds still detectable in ``text`` (audit helper)."""
    kinds = []
    for kind, pattern in _PATTERNS:
        if pattern.search(text or ""):
            kinds.append(kind)
    return kinds


# ---------------------------------------------------------------------------
# Medication-advice language check
# ---------------------------------------------------------------------------

#: Phrases that turn a reconciliation report into medical advice. The
#: product flags items for a professional to review; it never tells anyone
#: what to take, skip, stop, or double.
ADVICE_PHRASES: list[str] = [
    "safe to take",
    "safe for you to take",
    "stop taking",
    "start taking",
    "you should take",
    "you can take",
    "skip this dose",
    "skip the dose",
    "double up",
    "double the dose",
    "increase the dose",
    "decrease the dose",
    "change the dose",
    "do not take this with",
    "don't take this with",
    "interacts with",
    "interaction risk",
    "is dangerous to combine",
]


def find_advice_language(text: str) -> list[str]:
    """Return any advice phrases found in ``text`` (should always be [])."""
    low = (text or "").lower()
    return [p for p in ADVICE_PHRASES if p in low]
