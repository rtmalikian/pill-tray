# Architecture

## The one idea

The product ships its own OpenAI-compatible inference gateway, and every
AI feature in the product calls that gateway. Nothing calls a vendor API
directly. On top of that sits the Week 4 idea: **reconciliation is a
subtraction of two sets, done in code**. The model is the last and
smallest step, and only for the pills the code cannot separate.

```
            ┌──────────────────────────────────────────────────────────┐
            │                      FastAPI app                          │
            │                                                          │
  HTTP ───► │  /api/*  regimens · trays · reconcile · demo             │
            │     │                                                    │
            │     ▼                                                    │
            │  app/pilltray/  domain module                            │
            │   detector (segment · colour · shape · size · marks)    │
            │   features (closed-set scoring, tie rule)               │
            │   service (embed once · match · escalate · diff)        │
            │   synth (ground-truth fixtures) · models                │
            │     │  phrasing only, numbers already computed           │
            │     ▼                                                    │
            │  app/gateway.py  embedded OpenAI-compatible gateway      │
            │   /v1/models · /v1/chat/completions · /v1/embeddings    │
            │   tiers: pill-tray-frugal | pill-tray-full              │
            │     │                                                    │
            │     ├─ stub     deterministic, no model                 │
            │     ├─ local    Ollama / llama.cpp / vLLM on-site       │
            │     └─ upstream any OpenAI-compatible provider          │
            │                                                          │
            │  app/safety.py  PHI redaction gate + advice-language    │
            │                 check                                    │
            └──────────────────────────────────────────────────────────┘
```

## The shared-skeleton answer, Week 4

Weeks 1-3 established the pattern: one platform skeleton (gateway +
redaction gate + verified generation + eval harness), a new domain
module per week. Week 4 reuses `app/gateway.py` and `app/safety.py` with
two changes, both forced by the vision domain:

1. **Embeddings as a cache, not a call.** The regimen's visual
   descriptors are embedded once at creation and cached on the regimen.
   A tray check reuses them. Observed descriptors go through one
   batched call, with a cache keyed on the descriptor string, so a
   repeat tray costs no new regimen calls. The exact-descriptor fast
   path is real on any backend: identical descriptor strings produce
   identical vectors, so cosine is 1.0. The service records that cosine
   on each observed pill, but the matching confidence comes from the
   deterministic feature agreement in `features.py`, never from a
   cosine threshold. That separation is deliberate: stub embeddings are
   hash-based, and a hash cosine means nothing.
2. **Tiers as routing profiles, with a ledger split.** `gateway.TIERS`
   holds the frugal and full profiles. `resolve_tier` reads the model
   alias or the `X-Tier` header. The service counts VLM (crop-read)
   calls separately from summary and verifier calls, because the
   product's cost claim is about VLM calls: a clean tray must cost
   zero of them in the frugal tier, and the tests assert that.

What changed is only the domain module: wound imaging out, closed-set
matching and set difference in.

## The reconcile pipeline (app/pilltray/service.py)

1. **Embed once.** At regimen creation, descriptors go through
   `/v1/embeddings` in one batched call and are cached.
2. **Detect.** `detector.detect_pills` segments the tray photo by colour
   distance from the tray background, labels components by run-length
   connected components, and reads colour (nearest palette), shape
   (bounding-box geometry: ellipse ~0.79 fill, capsule ~0.90 fill),
   size (area bucket), and marking estimate (dark imprint pixels).
   Components far bigger than any pill are skipped, not guessed.
3. **Match locally.** Each pill is scored only against the regimen
   (colour 0.30, shape 0.25, size 0.15, marking bucket 0.20). Confident
   means score >= 0.75 with margin >= 0.12. The coarse pass uses the
   marking *bucket*, not the exact count, so look-alikes tie.
4. **Escalate, don't guess.** Frugal: only ambiguous pills get a VLM
   crop read, which resolves on the exact marking measurement.
   Unmatched pills are reported unexpected with no model call. Full:
   every pill gets a crop read, and a verifier pass checks the finished
   report against the expected list.
5. **Diff in code.** Greedy assignment by confidence into expected
   slots; overflow becomes a duplicate. Sections: matched, missing,
   count mismatches, duplicates, unexpected, ambiguous.
6. **Phrase, then check.** One gateway call phrases the diff. The
   summary is scanned against the banned advice-phrase list before it
   is returned, and the result carries that check's output.

## Verified generation, applied to reports

Weeks 1-2 verified *claims against sources*. Week 3 verified *numbers
against measurements*. Week 4's version is the report verifier: the
full tier's second pass checks that every medicine named in the diff is
on the expected list, and that every expected medicine is accounted
for (matched, missing, short, or duplicated). A report that invents a
medicine or drops one fails the check in the response payload, where a
human or a test can see it.
