> ## ⚠️ PROOF OF CONCEPT — NOT CLINICALLY TESTED
>
> **This tool has not been tested clinically and is a proof-of-concept for
> research and software demonstration only. It is not a medical device, it
> does not diagnose, treat, or rule out any condition, and its outputs may
> be wrong — including false positives and false negatives.**
>
> **Do not use it to make decisions about your health.**
> For any medical issue or concern, seek a licensed healthcare professional.
> **In an emergency, go to your nearest emergency room or dial 911 immediately.**

---

# PillTray Set-Difference

**Open-source brown-bag medication reconciliation by subtraction. Photograph everything in the bag or on the tray, and see only what does not match the patient's own list: missing, short, extra, unexpected, or ambiguous. The match is made only against that patient's list, never against a drug database. A pharmacist or clinician confirms the tray. PillTray never says what anyone should take.**

The brown-bag review is one of the oldest, most labour-intensive checks in primary care: a patient brings every bottle they have, and a clinician works through them against the chart, one by one. It rarely happens as often as it should, and the need is large. About 40% of adults aged 65 and over take five or more prescription medicines; 46% of primary-care adults misunderstood at least one prescription container label; 69.2% of older adults with low literacy and polypharmacy reported a self-administration error in the last six months. A systematic review found 25 generic pill-identification apps, but none found in searching that does closed-set reconciliation against the patient's own list as a self-hostable open-source product. Naming any of 60,000 drugs from a photo is a hard, crowded problem. Checking a tray against a list of five to ten medicines is a different, much smaller problem, and that is the whole product.

PillTray is a subtraction of two sets. The expected set comes from the chart. The observed set comes from the tray photo. The output is only the difference.

**This software is information for a pharmacist or clinician to review. It does not give medication advice, it does not say anything is safe to take, and it does not suggest starting, stopping, or changing a dose.** A report that says "missing" means a listed medicine was not seen in the photo, which is as often a photo problem (hidden or stacked pills) as a real gap. See SECURITY.md for the plain limits.

## The measurable failure, and what moves it

| Metric | Current workflow | With PillTray |
|---|---|---|
| Brown-bag review effort | Every bottle checked against the chart by hand, in the visit | One tray photo; the diff is computed in code and only the differences are shown. Clean trays in the fixture battery resolve with **zero VLM calls** |
| Mismatch spotting | Relies on the reviewer noticing an extra, missing, or wrong pill | Deterministic set difference: missing, short count, duplicate, unexpected, ambiguous. Eval harness on synthetic trays with known ground truth: **mismatch recall 1.0 (11/11 planted events)** |
| Cost per tray | Clinician time, every tray | Frugal tier: local closed-set match only, VLM reads only the pills it cannot separate. Fixture battery: **10 of 14 trays resolved with zero VLM calls (71.4%)**; the other four are trays containing the deliberate look-alike pair |
| Look-alike pills | The hardest case, and the one a name-this-pill app gets wrong quietly | Look-alikes tie on the coarse pass and are *escalated*, never guessed. A crop read separates them on the exact imprint measurement. Ambiguous items that stay ambiguous are reported as ambiguous, not assigned |

The eval harness in `tests/test_eval.py` fails the build if mismatch recall drops below 0.95 or if the zero-VLM share drops below 0.70. Current results, run on the shipped synthetic fixtures: **recall 1.0, zero-VLM share 71.4%.**

Honest note on those numbers, and on the battery: the fixtures are drawn pills on a flat tray, rendered by code in this repo (`app/pilltray/synth.py`), and the detector reads the same palette it renders against. They prove the pipeline computes the right diff from the features it reads. They do not prove anything about real pill photos, real imprint reading, glare, overlap, or hidden pills. The battery composition also matters: 10 of the 14 trays use a regimen with no look-alike pair, and 4 use the standard regimen, which contains one deliberate look-alike pair (white, round, medium, imprint marks 3 vs 4). A battery with more look-alike trays would legitimately score lower on the zero-VLM share. Real-photo accuracy is unproven, and that validation set is roadmap issue #1.

## How it works

```
 Expected list ──► embedded ONCE via /v1/embeddings, cached on the regimen
 Tray photo ────► segment pills in code (colour, shape, size, imprint marks)
                    │
                    ▼
        Local closed-set match, per pill, against ONLY that list
                    │
        ┌───────────┼───────────────┐
        │           │               │
   Confident    Ambiguous       Unmatched
   (assign)   (VLM crop read,   (report as
               frugal only)      unexpected,
                              no model call)
                    │
                    ▼
        Set difference, in code: matched / missing / count differs /
        duplicates / unexpected / ambiguous
                    │
                    ▼
        Gateway phrases the diff (never advice), full tier adds a
        verifier pass that checks the report against the expected list
```

Design rules that do the safety work:

1. **The closed set is the elegance.** Searching 60,000 drugs needs a database and a big model. Searching five to ten medicines needs four visual features and a tie rule. The small search space is simultaneously why a local match suffices, why accuracy can be high, and why a VLM is needed only for the ambiguous few.
2. **The model never decides the difference.** Matching scores, assignment, and the set difference are deterministic code in `app/pilltray/features.py` and `app/pilltray/service.py`. The model only reads a crop (to separate look-alikes) or phrases numbers it is given.
3. **Ambiguity is surfaced, never guessed.** The coarse pass deliberately does not use the exact imprint measurement. Two medicines that differ only in imprint therefore tie, and a tie triggers a crop read. If the crop read still cannot separate them, the pill is reported as ambiguous. No pill is ever silently assigned on a coin flip.
4. **No advice language, by test.** Every summary is checked against a banned-phrase list ("safe to take", "stop taking", "double up", and the rest in `app/safety.py`). The build fails if advice language appears.

## Two tiers, one gateway

Tier is a routing profile on the same gateway, chosen by the `model` name (`pill-tray-frugal` / `pill-tray-full`), an `X-Tier` header, or one env var. Same endpoints, same JSON schema, same UI, same eval harness. It is one product with the escalation dial turned up, not two products.

| | Frugal (default) | Full / commercial |
|---|---|---|
| Pill reading | Local closed-set match; VLM crop read only for ambiguous pills | VLM reads every pill crop |
| Verification | None (the diff is code, and the code is tested) | Second-pass verifier checks the report against the expected list |
| Measured cost | 0 VLM calls on clean simple-regimen trays; 3 VLM calls on a 7-pill standard tray (the look-alike pair) | 6 VLM calls on a 6-pill simple tray, plus 1 verifier call |
| What the spend buys | The diff itself | Verification on look-alike pills, targeting mismatch recall 0.95 to 0.99 in CI; a second check that the report accounts for every listed medicine |

The full tier's accuracy gain over the frugal tier is a hypothesis the harness measures per tier, not a claim. On the synthetic battery both tiers currently score recall 1.0, because the fixtures are easy for the code path; the gain would only show on real, harder photos.

## The architecture: the product ships its own AI gateway

PillTray serves OpenAI-compatible endpoints (`/v1/models`, `/v1/chat/completions`, `/v1/embeddings`) from inside the app, and every AI feature calls those endpoints. Nothing talks to a vendor API directly. One environment variable picks the backend:

- `stub` (default): deterministic, rule-based. No model, no keys. This is what CI and the demo run.
- `local`: an OpenAI-compatible server on your own hardware (Ollama, llama.cpp, vLLM). Tray photos never leave the home or clinic. This is the deployment the product is built for.
- `upstream`: any OpenAI-compatible provider, for teams that accept that trade-off.

This gateway is the shared platform skeleton across this weekly product series. Week 1's [Discharge Decoded](https://github.com/rtmalikian/discharge-decoded) shipped the gateway and redaction gate, Week 2's [Prior-Auth Co-Pilot](https://github.com/rtmalikian/prior-auth-copilot) reused it for prior auth, Week 3's [WoundDelta](https://github.com/rtmalikian/wound-delta) added vision tokens and tiers, and Week 4 keeps the skeleton and swaps in the reconciliation domain module. See docs/ARCHITECTURE.md.

## Quickstart

```bash
git clone https://github.com/rtmalikian/pill-tray
cd pill-tray
cp .env.example .env
docker compose up --build
# open http://localhost:8000
```

Or without Docker:

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --port 8000
```

Try a synthetic demo in the UI (the same fixtures CI measures), or:

```bash
curl -X POST "http://localhost:8000/api/demo/reconcile?scenario=std-unexpected-blue" \
  -H "X-Tier: frugal"
```

## API sketch

| Route | What it does |
|---|---|
| `GET /v1/models` | Lists `pill-tray-frugal`, `pill-tray-full`, and the stub model |
| `POST /v1/chat/completions` | OpenAI-shaped chat, tier by model alias or `X-Tier` header |
| `POST /v1/embeddings` | OpenAI-shaped embeddings (regimen descriptors, cached) |
| `POST /api/regimens` | Create an expected list (label passes the PHI redaction gate); descriptors embedded once |
| `GET /api/regimens/{id}` | Regimen, including which embeddings are cached |
| `POST /api/regimens/{id}/trays` | Upload a tray photo (PNG/JPEG, max 8 MB) and get the diff |
| `POST /api/regimens/{id}/reconcile` | Reconcile from detector-style descriptors directly |
| `POST /api/demo/reconcile?scenario=...` | Synthetic tray with known ground truth, reconciled live |

## Tests

```bash
.venv/bin/python -m pytest -q   # 30 tests
```

The suite covers closed-set scoring, the detector on rendered trays, the reconcile pipeline in both tiers, the gateway and its ledger, the API end to end, the PHI redaction gate and the advice-language check, and the eval harness gates described above.

## Roadmap

Issues #1 to #5 are open as collaboration magnets: a labelled real-photo validation set, a real detector/OCR front end for imprint reading, FHIR MedicationStatement export, a pharmacist confirmation workflow with a signed-off diff, and multi-tray (multi-week) adherence trending. Contributions welcome, especially from pharmacists willing to say where the matching rules are wrong.

## License

MIT. Built by Raphael Malikian (https://github.com/rtmalikian) as Week 4 of a weekly open-source clinical AI series.
