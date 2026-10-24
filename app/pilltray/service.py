"""The reconcile pipeline -- the product in one function.

Order matters, and the order *is* the cost story:

1. The regimen is embedded ONCE, at creation, through the gateway, and
   cached. A tray check reuses those vectors; it never re-embeds the list.
   Observed tray items are embedded in one batched call, with an exact
   descriptor fast path: an observed descriptor identical to a cached
   regimen descriptor has cosine 1.0 with it on any backend.
2. Local closed-set match in code (``features.coarse_score``). Every pill
   is scored only against this patient's list. The model is not involved.
3. Frugal tier: a VLM crop read only for pills the local pass could not
   separate (ambiguous: two or more candidates at/above threshold with
   too small a margin). The crop read uses the exact marking measurement
   the coarse pass deliberately does not. Unmatched pills are reported
   as unexpected without any model call.
4. Full tier: a VLM pass reads every pill crop, and a verifier pass
   checks the finished mismatch report against the expected list.
5. The set difference is computed in code, never by a model: matched,
   missing, count mismatches, duplicates, unexpected, ambiguous.
6. One gateway call phrases the diff. The summary is checked against the
   medication-advice phrase list before it is returned.
"""

from __future__ import annotations

import base64
import json

from app import gateway, safety
from app.pilltray import detector, features, models

_EMBED_CACHE: dict[str, list[float]] = {}


def _embed_descriptors(descriptors: list[str]) -> tuple[list[list[float]], int]:
    """Embed descriptors through the gateway, reusing the cache. Returns
    (vectors, gateway_calls_made)."""
    missing = [d for d in descriptors if d not in _EMBED_CACHE]
    calls = 0
    if missing:
        resp = gateway.dispatch_embeddings(missing)
        for item in resp["data"]:
            _EMBED_CACHE[missing[item["index"]]] = item["embedding"]
        calls = 1
    return [_EMBED_CACHE[d] for d in descriptors], calls


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def build_regimen(label: str, medications: list[dict]) -> models.Regimen:
    """Create a regimen and embed its descriptors once, via the gateway."""
    regimen = models.new_regimen(label, medications)
    before = gateway.CALL_LEDGER["embeddings"]
    descriptors = [m.descriptor() for m in regimen.medications]
    vectors, _calls = _embed_descriptors(descriptors)
    for med, vec in zip(regimen.medications, vectors):
        regimen.embeddings[med.id] = vec
    regimen.embedding_calls_at_build = gateway.CALL_LEDGER["embeddings"] - before
    return regimen


def _resolve_via_gateway(obs: dict, candidates: list[dict], tier: str) -> dict:
    """One VLM crop-read call: pick a candidate from the fine features.
    ``obs`` carries marking_exact; candidates carry their expected
    marking_exact. Returns the stub/real model's JSON decision."""
    profile = gateway.tier_profile(tier)
    # Note: the stub/CI path passes the crop's measured features as text.
    # A production deployment passes the actual pill crop as a multimodal
    # image part through this same dispatch point; the stub simulates the
    # crop read by resolving on the exact marking measurement, which is
    # the piece of information a crop read adds over the coarse pass.
    messages = [
        {"role": "system",
         "content": "You read one pill crop. Choose the medication it best "
                    "matches from the candidates given, using the imprint "
                    "marking measurement. Return JSON only: "
                    '{"med_id": ..., "confidence": ...}.'},
        {"role": "user", "content":
            "[TASK: RESOLVE_PILL]\n[OBSERVED]\n"
            + json.dumps({
                "colour": obs["colour"], "shape": obs["shape"],
                "size": obs["size"],
                "marking_exact": obs["marking_exact"]})
            + "\n[/OBSERVED]\n[CANDIDATES]\n"
            + json.dumps([{
                "med_id": c["med_id"], "colour": c["colour"],
                "shape": c["shape"], "size": c["size"],
                "marking_exact": c["marking_exact"]}
                for c in candidates])
            + "\n[/CANDIDATES]"},
    ]
    resp = gateway.dispatch_chat(messages, model=profile["model_alias"],
                                 tier=tier)
    try:
        decision = json.loads(resp["choices"][0]["message"]["content"])
    except Exception:
        decision = {"med_id": None, "confidence": 0.0,
                    "note": "crop read returned non-JSON"}
    return {"decision": decision, "usage": resp["usage"]}


def reconcile(regimen: models.Regimen, observed: list[dict],
              tier: str = "frugal") -> dict:
    """Reconcile one tray against a regimen. Returns the diff report."""
    profile = gateway.tier_profile(tier)
    chat_before = gateway.CALL_LEDGER["chat"]
    emb_before = gateway.CALL_LEDGER["embeddings"]
    est_tokens = 0
    vlm_calls = 0

    candidates = regimen.candidates()
    cand_by_id = {c["med_id"]: c for c in candidates}

    # Observed descriptors, embedded in one batched gateway call (cache
    # means repeat descriptors cost nothing).
    descriptors = [features.visual_descriptor(o["colour"], o["shape"],
                                              o["size"], o["marking_bucket"])
                   for o in observed]
    obs_vectors, _ = _embed_descriptors(descriptors)
    reg_vectors = [regimen.embeddings[m.id] for m in regimen.medications]
    for obs, vec in zip(observed, obs_vectors):
        best = max((_cosine(vec, rv) for rv in reg_vectors), default=0.0)
        obs["_embedding_cosine_best"] = round(best, 4)

    # Local closed-set match per pill.
    assignments: list[dict] = []      # {obs, med_id, confidence, via}
    unexpected: list[dict] = []
    ambiguous: list[dict] = []
    for obs in observed:
        scored = features.score_candidates(obs, candidates)
        kind = features.classify(scored)
        if tier == "full":
            # Commercial tier: every pill gets a crop read.
            top = [cand_by_id[s["med_id"]] for s in scored[:3]]
            res = _resolve_via_gateway(obs, top, tier)
            vlm_calls += 1
            est_tokens += res["usage"]["total_tokens"]
            decision = res["decision"]
            if decision.get("med_id") and decision.get("confidence", 0) >= 0.80:
                assignments.append({"obs": obs, "med_id": decision["med_id"],
                                    "confidence": decision["confidence"],
                                    "via": "vlm"})
            elif kind == "confident":
                assignments.append({"obs": obs, "med_id": scored[0]["med_id"],
                                    "confidence": scored[0]["score"],
                                    "via": "local"})
            else:
                ambiguous.append(_ambiguous_item(obs, scored))
            continue
        if kind == "confident":
            assignments.append({"obs": obs, "med_id": scored[0]["med_id"],
                                "confidence": scored[0]["score"],
                                "via": "local"})
        elif kind == "ambiguous":
            top = [cand_by_id[s["med_id"]] for s in scored
                   if s["score"] >= features.MATCH_THRESHOLD][:3]
            res = _resolve_via_gateway(obs, top, tier)
            vlm_calls += 1
            est_tokens += res["usage"]["total_tokens"]
            decision = res["decision"]
            if decision.get("med_id") and decision.get("confidence", 0) >= 0.80:
                assignments.append({"obs": obs, "med_id": decision["med_id"],
                                    "confidence": decision["confidence"],
                                    "via": "vlm"})
            else:
                ambiguous.append(_ambiguous_item(obs, scored))
        else:
            unexpected.append(_unexpected_item(obs, scored))

    # Greedy assignment, highest confidence first, into expected slots;
    # overflow against a medicine becomes a duplicate, not an error.
    per_med: dict[str, list[dict]] = {}
    for a in sorted(assignments, key=lambda x: -x["confidence"]):
        per_med.setdefault(a["med_id"], []).append(a)

    matched, missing, count_mismatches, duplicates = [], [], [], []
    matched_count = 0
    for med in regimen.medications:
        assigned = per_med.get(med.id, [])
        n = len(assigned)
        conf = min((a["confidence"] for a in assigned), default=None)
        if n == med.expected_count:
            matched.append({"med_id": med.id, "name": med.name,
                            "expected_count": med.expected_count,
                            "observed_count": n, "confidence": conf})
            matched_count += n
        elif n == 0:
            missing.append({"med_id": med.id, "name": med.name,
                            "expected_count": med.expected_count,
                            "observed_count": 0,
                            "shortfall": med.expected_count})
        elif n < med.expected_count:
            count_mismatches.append({
                "med_id": med.id, "name": med.name,
                "expected_count": med.expected_count, "observed_count": n,
                "shortfall": med.expected_count - n, "confidence": conf})
            matched_count += n
        else:
            matched.append({"med_id": med.id, "name": med.name,
                            "expected_count": med.expected_count,
                            "observed_count": med.expected_count,
                            "confidence": conf})
            duplicates.append({"med_id": med.id, "name": med.name,
                               "expected_count": med.expected_count,
                               "observed_count": n,
                               "excess": n - med.expected_count,
                               "confidence": conf})
            matched_count += med.expected_count

    diff = {
        "matched": matched,
        "missing": missing,
        "count_mismatches": count_mismatches,
        "duplicates": duplicates,
        "unexpected": unexpected,
        "ambiguous": ambiguous,
        "matched_count": matched_count,
        "expected_total": sum(m.expected_count for m in regimen.medications),
        "observed_total": len(observed),
        "diff_found": bool(missing or count_mismatches or duplicates
                           or unexpected or ambiguous),
    }

    # One phrasing call (not a VLM pill read).
    messages = [
        {"role": "system",
         "content": "You phrase a medication reconciliation report for a "
                    "pharmacist or clinician to review. Use only the "
                    "numbers given. Never give medication advice, never "
                    "say whether anything is safe to take, and never "
                    "suggest starting, stopping, or changing a dose."},
        {"role": "user", "content":
            "[TASK: SUMMARISE_DIFF]\n[DIFF]\n" + json.dumps(diff)
            + "\n[/DIFF]"},
    ]
    resp = gateway.dispatch_chat(messages, model=profile["model_alias"],
                                 tier=tier,
                                 max_tokens=profile["summary_max_tokens"])
    summary = resp["choices"][0]["message"]["content"]
    est_tokens += resp["usage"]["total_tokens"]
    summary_calls = 1

    verifier = None
    verifier_calls = 0
    if profile["verifier"]:
        v_messages = [
            {"role": "user", "content":
                "[TASK: VERIFY_REPORT]\n[EXPECTED]\n"
                + json.dumps([{"name": m.name} for m in regimen.medications])
                + "\n[/EXPECTED]\n[DIFF]\n" + json.dumps(diff)
                + "\n[/DIFF]"},
        ]
        v_resp = gateway.dispatch_chat(v_messages, tier=tier,
                                       model=profile["model_alias"])
        verifier_calls = 1
        est_tokens += v_resp["usage"]["total_tokens"]
        try:
            verifier = json.loads(v_resp["choices"][0]["message"]["content"])
        except Exception:
            verifier = {"ok": None, "note": "verifier returned non-JSON"}

    advice_found = safety.find_advice_language(summary)

    return {
        "tier": tier,
        "diff": diff,
        "summary": summary,
        "verifier": verifier,
        "advice_language_found": advice_found,
        "usage": {
            "vlm_calls": vlm_calls,
            "summary_calls": summary_calls,
            "verifier_calls": verifier_calls,
            "chat_calls": gateway.CALL_LEDGER["chat"] - chat_before,
            "embedding_calls": gateway.CALL_LEDGER["embeddings"] - emb_before,
            "est_tokens": est_tokens,
        },
    }


def _unexpected_item(obs: dict, scored: list[dict]) -> dict:
    best = scored[0]["score"] if scored else 0.0
    return {
        "obs_id": obs.get("obs_id"),
        "description": f"{obs['colour']} {obs['shape']} pill, size {obs['size']}",
        "confidence": best,
        "features": {k: obs[k] for k in ("colour", "shape", "size",
                                         "marking_bucket") if k in obs},
    }


def _ambiguous_item(obs: dict, scored: list[dict]) -> dict:
    return {
        "obs_id": obs.get("obs_id"),
        "description": f"{obs['colour']} {obs['shape']} pill, size {obs['size']}",
        "candidates": [s["med_id"] for s in scored[:3]],
        "scores": [s["score"] for s in scored[:3]],
    }


def reconcile_photo(regimen: models.Regimen, png_bytes: bytes,
                    tier: str = "frugal") -> dict:
    """Detect pills in a tray photo, then reconcile. Raises ValueError
    for unreadable images."""
    try:
        arr = detector.load_image(png_bytes)
    except Exception:
        raise ValueError("not a readable PNG/JPEG image")
    observed = detector.detect_pills(arr)
    result = reconcile(regimen, observed, tier=tier)
    result["detected_pills"] = observed
    return result


def reconcile_descriptors(regimen: models.Regimen, observed: list[dict],
                          tier: str = "frugal") -> dict:
    """Reconcile from detector-style descriptors directly (for device or
    integration front ends that run detection themselves)."""
    norm = []
    for i, o in enumerate(observed):
        norm.append({
            "obs_id": o.get("obs_id") or f"obs-{i + 1}",
            "colour": o["colour"], "shape": o["shape"], "size": o["size"],
            "marking_exact": int(o.get("marking_exact", 0)),
            "marking_bucket": o.get("marking_bucket")
            or features.marking_bucket(o.get("marking_exact", 0), from_px=True),
        })
    return reconcile(regimen, norm, tier=tier)
