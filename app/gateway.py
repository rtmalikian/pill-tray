"""Embedded OpenAI-compatible inference gateway.

This module is the architectural core of PillTray, and it is the shared
platform skeleton carried over from Week 1's Discharge Decoded, Week 2's
Prior-Auth Co-Pilot, and Week 3's WoundDelta: instead of the product
calling an outside AI API directly, every AI feature goes through this
gateway, which speaks the OpenAI API shapes (``/v1/models``,
``/v1/chat/completions``, ``/v1/embeddings``) and routes to a pluggable
backend selected by the ``AI_BACKEND`` environment variable:

- ``stub`` (default): deterministic, rule-based responses. Zero model needed.
  Used by tests, CI, and the demo when no model is configured.
- ``local``: forwards to an OpenAI-compatible server on the clinic's own
  hardware (Ollama, llama.cpp server, vLLM, ...) via ``LOCAL_MODEL_URL``.
  Photos never leave the building: the self-hosting story.
- ``upstream``: forwards to any OpenAI-compatible provider via
  ``UPSTREAM_BASE_URL`` + ``UPSTREAM_API_KEY``.

Two product tiers ride on the same gateway (see ``TIERS`` below). The tier
is a routing profile, selected by the ``model`` name (``pill-tray-frugal``
vs ``pill-tray-full``) or an ``X-Tier`` header. It is one product with the
escalation dial in one config dict, never two products.

The gateway also keeps an honest call ledger. Embeddings, chat (VLM)
calls, and estimated tokens are counted separately, so the eval harness
can assert the product's central claim: in the frugal tier most trays are
resolved with **zero VLM calls**, because the closed-set local match did
the work.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
import uuid

import httpx
from fastapi import HTTPException

STUB_MODEL_ID = "pill-tray-stub-1"
FRUGAL_MODEL_ID = "pill-tray-frugal"
FULL_MODEL_ID = "pill-tray-full"
_REQUEST_TIMEOUT = 120.0

# ---------------------------------------------------------------------------
# Tiers -- one gateway, one config dict, two budgets
# ---------------------------------------------------------------------------

TIERS: dict[str, dict] = {
    "frugal": {
        "model_alias": FRUGAL_MODEL_ID,
        # The VLM sees a pill only when the local closed-set match cannot
        # separate the candidates. That is the whole cost story.
        "vlm_mode": "ambiguous_only",
        "vision_detail": "low",
        "verifier": False,
        "summary_max_tokens": 220,
    },
    "full": {
        "model_alias": FULL_MODEL_ID,
        # Commercial tier: a VLM pass reads every pill crop, and a second
        # pass verifies the mismatch report against the expected list.
        "vlm_mode": "every_pill",
        "vision_detail": "high",
        "verifier": True,
        "summary_max_tokens": 500,
    },
}


def resolve_tier(model: str | None = None, x_tier: str | None = None) -> str:
    """Resolve the tier from an X-Tier header or a model alias."""
    if x_tier and x_tier.strip().lower() in TIERS:
        return x_tier.strip().lower()
    if model:
        m = model.strip().lower()
        if m.endswith("-full") or m == FULL_MODEL_ID:
            return "full"
        if m.endswith("-frugal") or m == FRUGAL_MODEL_ID:
            return "frugal"
    env = (os.environ.get("PILL_TRAY_TIER", "frugal") or "frugal").strip().lower()
    return env if env in TIERS else "frugal"


def tier_profile(tier: str) -> dict:
    return dict(TIERS[tier])


def estimate_image_tokens(detail: str, width: int, height: int) -> int:
    """Published tile maths: low detail is flat; high detail tiles at 512px."""
    if detail == "low":
        return 85
    tiles = max(1, math.ceil(width / 512)) * max(1, math.ceil(height / 512))
    return 85 + 170 * tiles


def estimate_text_tokens(text: str) -> int:
    return max(1, len(text or "") // 4)


# ---------------------------------------------------------------------------
# Call ledger -- tests assert on this (e.g. clean tray == zero VLM calls)
# ---------------------------------------------------------------------------

CALL_LEDGER: dict[str, int] = {"chat": 0, "embeddings": 0}
CALL_LOG: list[dict] = []


def reset_ledger() -> None:
    CALL_LEDGER["chat"] = 0
    CALL_LEDGER["embeddings"] = 0
    CALL_LOG.clear()


# ---------------------------------------------------------------------------
# Backend selection
# ---------------------------------------------------------------------------

def get_backend() -> str:
    """Return the configured backend name: stub | local | upstream."""
    return (os.environ.get("AI_BACKEND", "stub") or "stub").strip().lower()


def _local_base() -> str:
    return (os.environ.get("LOCAL_MODEL_URL", "http://localhost:11434") or "").rstrip("/")


def _upstream_base() -> str:
    return (os.environ.get("UPSTREAM_BASE_URL", "https://api.openai.com") or "").rstrip("/")


def _upstream_headers() -> dict:
    key = os.environ.get("UPSTREAM_API_KEY", "")
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


# ---------------------------------------------------------------------------
# Public dispatch API -- the single code path for all AI calls
# ---------------------------------------------------------------------------

def list_models() -> dict:
    backend = get_backend()
    if backend == "stub":
        data = [
            {"id": STUB_MODEL_ID, "object": "model",
             "created": int(time.time()), "owned_by": "pill-tray"},
            {"id": FRUGAL_MODEL_ID, "object": "model",
             "created": int(time.time()), "owned_by": "pill-tray",
             "tier": "frugal"},
            {"id": FULL_MODEL_ID, "object": "model",
             "created": int(time.time()), "owned_by": "pill-tray",
             "tier": "full"},
        ]
        return {"object": "list", "data": data}
    if backend == "local":
        try:
            r = httpx.get(f"{_local_base()}/v1/models", timeout=10.0)
            r.raise_for_status()
            return r.json()
        except Exception:
            return {"object": "list", "data": [
                {"id": "local-model", "object": "model",
                 "created": int(time.time()), "owned_by": "local"}]}
    if backend == "upstream":
        try:
            r = httpx.get(f"{_upstream_base()}/v1/models",
                          headers=_upstream_headers(), timeout=15.0)
            r.raise_for_status()
            return r.json()
        except Exception as exc:
            raise HTTPException(status_code=502,
                                detail=f"upstream /v1/models failed: {exc}")
    raise HTTPException(status_code=500, detail=f"unknown AI_BACKEND: {backend}")


def dispatch_chat(messages: list[dict], model: str | None = None,
                  temperature: float = 0.2, max_tokens: int = 2000,
                  response_format: dict | None = None,
                  tier: str | None = None) -> dict:
    """OpenAI-shaped chat completion through the configured backend.

    ``messages`` may carry multimodal content parts (text + image_url).
    The usage block reports *estimated* vision tokens using the tile maths
    above, so per-tray call and token budgets are assertable in tests on
    every backend.
    """
    tier = tier or resolve_tier(model)
    profile = tier_profile(tier)
    backend = get_backend()
    CALL_LEDGER["chat"] += 1
    CALL_LOG.append({"kind": "chat", "tier": tier, "backend": backend,
                     "model": model})
    if backend == "stub":
        content = _stub_chat(messages)
        model_id = model or profile["model_alias"]
    elif backend in ("local", "upstream"):
        content, model_id = _forward_chat(
            messages, model, temperature, max_tokens, response_format, backend)
    else:
        raise HTTPException(status_code=500, detail=f"unknown AI_BACKEND: {backend}")

    prompt_tokens = _count_prompt_tokens(messages, profile)
    completion_tokens = estimate_text_tokens(content)
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model_id,
        "tier": tier,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


def _count_prompt_tokens(messages: list[dict], profile: dict) -> int:
    total = 0
    for m in messages:
        content = m.get("content", "")
        if isinstance(content, str):
            total += estimate_text_tokens(content)
        elif isinstance(content, list):
            for part in content:
                if part.get("type") == "text":
                    total += estimate_text_tokens(part.get("text", ""))
                elif part.get("type") == "image_url":
                    detail = (part.get("image_url", {}) or {}).get(
                        "detail", profile["vision_detail"])
                    w = part.get("_width", 1024)
                    h = part.get("_height", 1024)
                    total += estimate_image_tokens(detail, w, h)
    return total


def dispatch_embeddings(input: str | list[str], model: str | None = None) -> dict:
    """OpenAI-shaped embeddings through the configured backend."""
    backend = get_backend()
    CALL_LEDGER["embeddings"] += 1
    texts = [input] if isinstance(input, str) else list(input)
    if backend == "stub":
        vectors = [_stub_embedding(t) for t in texts]
        model_id = model or STUB_MODEL_ID
    elif backend in ("local", "upstream"):
        vectors, model_id = _forward_embeddings(texts, model, backend)
    else:
        raise HTTPException(status_code=500, detail=f"unknown AI_BACKEND: {backend}")

    return {
        "object": "list",
        "data": [
            {"object": "embedding", "embedding": vec, "index": i}
            for i, vec in enumerate(vectors)
        ],
        "model": model_id,
        "usage": {
            "prompt_tokens": max(1, sum(len(t) for t in texts) // 4),
            "total_tokens": max(1, sum(len(t) for t in texts) // 4),
        },
    }


# ---------------------------------------------------------------------------
# Forwarding backends
# ---------------------------------------------------------------------------

def _clean_messages(messages: list[dict]) -> list[dict]:
    """Strip ledger-only keys (``_width``/``_height``) before forwarding."""
    out = []
    for m in messages:
        content = m.get("content")
        if isinstance(content, list):
            content = [{k: v for k, v in part.items()
                        if not k.startswith("_")} for part in content]
        out.append({**m, "content": content})
    return out


def _forward_chat(messages, model, temperature, max_tokens, response_format, backend):
    if backend == "local":
        url = f"{_local_base()}/v1/chat/completions"
        headers = {"Content-Type": "application/json"}
        model_id = model or os.environ.get("LOCAL_MODEL", "local-model")
    else:
        url = f"{_upstream_base()}/v1/chat/completions"
        headers = _upstream_headers()
        model_id = model or os.environ.get("UPSTREAM_MODEL", "gpt-4o-mini")
    payload = {"model": model_id, "messages": _clean_messages(messages),
               "temperature": temperature, "max_tokens": max_tokens}
    if response_format:
        payload["response_format"] = response_format
    try:
        r = httpx.post(url, json=payload, headers=headers, timeout=_REQUEST_TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        raise HTTPException(status_code=502,
                            detail=f"{backend} chat completions failed: {exc}")
    try:
        content = data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        raise HTTPException(status_code=502,
                            detail=f"{backend} returned an unexpected chat shape")
    return content, data.get("model", model_id)


def _forward_embeddings(texts, model, backend):
    if backend == "local":
        url = f"{_local_base()}/v1/embeddings"
        headers = {"Content-Type": "application/json"}
        model_id = model or os.environ.get("LOCAL_MODEL", "local-model")
    else:
        url = f"{_upstream_base()}/v1/embeddings"
        headers = _upstream_headers()
        model_id = model or os.environ.get("UPSTREAM_MODEL", "text-embedding-3-small")
    try:
        r = httpx.post(url, json={"model": model_id, "input": texts},
                       headers=headers, timeout=_REQUEST_TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502,
                            detail=f"{backend} embeddings failed: {exc}")
    try:
        vectors = [d["embedding"] for d in sorted(data["data"], key=lambda d: d["index"])]
    except (KeyError, TypeError):
        raise HTTPException(status_code=502,
                            detail=f"{backend} returned an unexpected embeddings shape")
    return vectors, data.get("model", model_id)


# ---------------------------------------------------------------------------
# Stub backend -- deterministic, zero-model, used by tests/CI/demo
#
# The stub enforces the product's core contract in miniature: the model
# never decides the set difference. Code computes the diff; the stub only
# simulates the two things a real VLM pass adds -- reading a pill marking
# at crop detail to separate look-alikes (RESOLVE_PILL), and phrasing /
# verifying the finished report (SUMMARISE_DIFF / VERIFY_REPORT).
# ---------------------------------------------------------------------------

def _stub_embedding(text: str, dims: int = 32) -> list[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return [round(b / 255.0, 6) for b in digest[:dims]]


def _find_block(messages: list[dict], tag: str) -> str:
    blob = ""
    for m in messages:
        content = m.get("content", "")
        if isinstance(content, str):
            blob += content + "\n"
        elif isinstance(content, list):
            for part in content:
                if part.get("type") == "text":
                    blob += part.get("text", "") + "\n"
    mm = re.search(rf"\[{tag}\]\s*(.*?)\s*\[/{tag}\]", blob, re.S)
    return mm.group(1) if mm else ""


def _stub_chat(messages: list[dict]) -> str:
    blob_all = ""
    for m in messages:
        c = m.get("content", "")
        blob_all += c if isinstance(c, str) else " ".join(
            p.get("text", "") for p in c if isinstance(p, dict))
    task_m = re.search(r"\[TASK:\s*([A-Z_]+)\]", blob_all)
    task = task_m.group(1) if task_m else None
    if task == "RESOLVE_PILL":
        return _stub_resolve(_find_block(messages, "OBSERVED"),
                             _find_block(messages, "CANDIDATES"))
    if task == "SUMMARISE_DIFF":
        return _stub_summarise(_find_block(messages, "DIFF"))
    if task == "VERIFY_REPORT":
        return _stub_verify(_find_block(messages, "EXPECTED"),
                            _find_block(messages, "DIFF"))
    return "Stub response."


def _fine_agreement(obs: dict, cand: dict) -> float:
    """Fine-grained agreement used to simulate a crop read: unlike the
    coarse local pass it can use the exact marking measurement, which is
    what separates look-alike pills."""
    score = 0.0
    if obs.get("colour") == cand.get("colour"):
        score += 0.30
    if obs.get("shape") == cand.get("shape"):
        score += 0.25
    if obs.get("size") == cand.get("size"):
        score += 0.15
    mo, mc = obs.get("marking_exact"), cand.get("marking_exact")
    if mo is not None and mc is not None:
        if mo == mc:
            score += 0.30
        elif abs(mo - mc) <= max(6, 0.1 * max(mo, mc)):
            score += 0.15
    return round(score, 4)


def _stub_resolve(observed_blob: str, candidates_blob: str) -> str:
    try:
        obs = json.loads(observed_blob)
        cands = json.loads(candidates_blob)
    except Exception:
        return json.dumps({"med_id": None, "confidence": 0.0,
                           "note": "unreadable crop"})
    scored = sorted(
        ({"med_id": c.get("med_id"),
          "confidence": _fine_agreement(obs, c)} for c in cands),
        key=lambda s: -s["confidence"])
    if not scored:
        return json.dumps({"med_id": None, "confidence": 0.0})
    best = scored[0]
    second = scored[1]["confidence"] if len(scored) > 1 else 0.0
    if best["confidence"] < 0.80 or best["confidence"] - second < 0.10:
        return json.dumps({"med_id": None, "confidence": best["confidence"],
                           "note": "still ambiguous after crop read"})
    return json.dumps(best)


def _stub_summarise(diff_blob: str) -> str:
    try:
        d = json.loads(diff_blob)
    except Exception:
        return "No reconciliation result was provided, so no summary can be written."
    matched = d.get("matched_count", 0)
    expected = d.get("expected_total", 0)
    lines = [f"{matched} of {expected} expected pills on the list were "
             f"matched in the tray photo."]
    issues = []
    for item in d.get("missing", []):
        issues.append(f"missing: {item['name']} ({item['shortfall']} not seen)")
    for item in d.get("count_mismatches", []):
        issues.append(f"count differs: {item['name']} (expected "
                      f"{item['expected_count']}, saw {item['observed_count']})")
    for item in d.get("duplicates", []):
        issues.append(f"extra of a listed medicine: {item['name']} "
                      f"({item['excess']} more than expected)")
    for item in d.get("unexpected", []):
        issues.append(f"not on the list: {item['description']} "
                      f"(confidence {item['confidence']})")
    for item in d.get("ambiguous", []):
        issues.append(f"could not be told apart: {item['description']}")
    if issues:
        lines.append("For a pharmacist or clinician to review: "
                     + "; ".join(issues) + ".")
    else:
        lines.append("No differences from the list were found in this photo. "
                     "A pharmacist or clinician still confirms the tray; "
                     "a photo can miss pills that are hidden or stacked.")
    lines.append("This report compares a photo with a list. It does not say "
                 "what anyone should take, and it is not medical advice.")
    return " ".join(lines)


def _stub_verify(expected_blob: str, diff_blob: str) -> str:
    """Second-pass check (full tier): every medicine named in the diff
    must be on the expected list, and every expected medicine must be
    accounted for (matched, missing, short, or duplicated)."""
    try:
        expected = json.loads(expected_blob)
        d = json.loads(diff_blob)
    except Exception:
        return json.dumps({"ok": False, "problems": ["unreadable input"]})
    names = {m["name"] for m in expected}
    problems = []
    accounted = set()
    for item in d.get("matched", []):
        accounted.add(item["name"])
        if item["name"] not in names:
            problems.append(f"matched item not on list: {item['name']}")
    for section in ("missing", "count_mismatches", "duplicates"):
        for item in d.get(section, []):
            accounted.add(item["name"])
            if item["name"] not in names:
                problems.append(f"{section} item not on list: {item['name']}")
    for m in expected:
        if m["name"] not in accounted:
            problems.append(f"expected medicine unaccounted for: {m['name']}")
    return json.dumps({"ok": not problems, "problems": problems})
