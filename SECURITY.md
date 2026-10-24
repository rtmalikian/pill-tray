# Security and honest limits

PillTray handles photos of people's medicines and a list of what they
are supposed to take. That is health data, and getting it wrong has
consequences in both directions: a missed wrong pill, or a false alarm
that makes someone stop a medicine they need. This document states
plainly what the software does, what it does not do, and what a real
deployment must add.

## What this software is

A reconciliation aid. It compares a tray photo with an expected list
and shows only the difference, for a pharmacist or clinician to review.
**It is not a medical device. It does not diagnose, treat, or rule out
any condition. It does not give medication advice of any kind: it never
says anything is safe to take, and never suggests starting, stopping,
skipping, or changing a dose.** Every output says a pharmacist or
clinician confirms the tray. A "missing" flag means a listed medicine
was not seen in the photo. A photo can miss pills that are hidden,
stacked, or out of frame, so a missing flag is not proof the medicine
is absent from the home.

## The regulatory boundary, stated plainly

Software that organises a medication list and flags differences for a
professional to review is positioned here as information and decision
support. Software that tells a patient what to take, or that claims to
identify medicines definitively, can fall under medical-device
regulation (in the US, FDA device rules; elsewhere, the local
equivalent). This project deliberately stays on the review side of that
line: no identification claims, no safety claims, no advice language,
and a banned-phrase test that fails the build if advice language
appears. If you extend it, know that adding advice or identification
claims can change its regulatory status, and get real regulatory advice
first. Nothing in this repository is legal or regulatory advice.

## Accuracy limits

- The eval numbers in the README (mismatch recall 1.0, zero-VLM share
  71.4%) are measured on **synthetic fixtures**: drawn pills on a flat
  tray, rendered by code in this repo, read by a detector that names
  against the same palette. They prove the pipeline computes the right
  diff from the features it reads. They do not prove accuracy on real
  pill photos, real imprint reading, glare, shadows, overlapping or
  stacked pills, pills in bottles, or handwriting on labels. Real-photo
  accuracy is unknown until someone runs the labelled validation set in
  roadmap issue #1.
- The detector is a colour-segmentation heuristic, not a trained model.
  It needs separated pills on a tray background that differs from every
  pill colour. Pills that touch merge into one component; a component
  far bigger than any pill is skipped, which surfaces as a missing flag
  rather than a hallucinated pill. That failure mode is documented in
  the code because it is the honest one, but it is still a failure mode.
- Imprint reading in v0.1.0 is a marking-count measurement on synthetic
  renders, not OCR. A real deployment must replace that slot with a
  real imprint reader (OCR or a VLM crop read) and re-measure. The
  architecture has the slot ready: the crop-read dispatch point in
  `app/pilltray/service.py`.
- The closed set is only as good as the expected list. A stale or wrong
  list makes the diff wrong in the direction of the list. The product
  never checks the list against a pharmacy or chart; that is the
  deploying clinician's job, and the README says so.

## Photo and PHI handling

- **Self-hosting is the privacy story.** Run the `local` backend
  (Ollama, llama.cpp, vLLM) and tray photos never leave the home or
  clinic hardware. The default `stub` backend also sends nothing
  anywhere: summaries are templated from the diff.
- **The `upstream` backend is a trade-off, not a default.** Point the
  gateway at a third-party provider and tray crops and descriptors
  leave the building. That decision belongs to the deploying
  organisation, with the right agreements in place.
- **Labels pass the redaction gate** (`app/safety.py`): emails, phone
  numbers, SSNs, dates of birth, MRNs, member IDs, street addresses,
  and labelled patient names are stripped from regimen labels before
  storage. Logs record redaction kinds and counts, never values. Tray
  photos themselves are not redacted; treat stored photos as PHI.
- **Storage in v0.1.0 is in-memory.** Restarting the app drops regimens
  and photos. That is a pilot limitation, and in one sense a safety
  property. A real deployment needs encrypted storage, access control,
  retention rules, and audit logs; none of those ship here and none
  should be improvised.

## The human rule

A pharmacist or clinician reviews the diff. The patient-facing summary
says so, every section of the report is labelled for review, and no
setting in this codebase turns a flag into advice given to a patient.
Do not wire reconciliation reports to automatic messages telling
patients what to take without clinical governance.
