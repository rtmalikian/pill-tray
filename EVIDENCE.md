# Evidence base — PillTray Set-Difference

Every load-bearing claim in the README traces to a row below: claim → full
citation → evidence tier → what it proves / does not prove. Tiers follow the
project evidence standard: Tier 1 = systematic review / meta-analysis /
guideline / authoritative compendium; Tier 2 = RCT / large cohort / validated
measurement study on real patients; Tier 3 = small observational / pilot;
Tier 4 = vendor / press / synthetic results, labelled as such and never
dressed as independent evidence.

All citations below were opened and checked on 2026-10-31. This file records
an evidence audit of the claims, not clinical validation of the app:
PillTray's own real-world efficacy is unproven until a labelled validation
set exists (roadmap issue #1). Its own eval numbers (mismatch recall 1.0,
zero-VLM share 71.4%) come from synthetic fixtures rendered by code in this
repo and are **Tier 4**: they prove the pipeline computes the right diff
from the features it reads, nothing about real pill photos.

| Claim | Full citation + link | Tier | What it proves | What it does NOT prove |
|---|---|---|---|---|
| ~43% of adults 65+ take 5+ prescription medicines | Innes GK, Ogden CL, Crentsil V, Concato J, Fakhouri TH. Prescription Medication Use Among Older Adults in the US. *JAMA Intern Med.* 2024;184(9):1121–1123. https://pmc.ncbi.nlm.nih.gov/articles/PMC11217884/ | Tier 2 — NHANES, n = 14,917 aged 65+, 1999–March 2020, past-30-day use validated by container / pharmacy printout | Polypharmacy (≥5) rose 23.6% (1999–2000) to 43.0% (95% CI 40.0–46.6%) in 2017–March 2020; mean medicines 3.0 → 4.3 | That the figure is current for 2025–2026, that it covers institutionalised adults (NHANES excludes them; response rate fell to 46.5% in 2017–Mar 2020), or that polypharmacy alone creates a need for photo reconciliation |
| Prescription container labels are widely misunderstood | Primary: Wolf MS et al. To err is human: patient misinterpretations of prescription drug label instructions. *Patient Educ Couns.* 2007;67(3):293–300. https://pubmed.ncbi.nlm.nih.gov/17587533/ — Secondary summary stating the 46% figure: Jeetu G, Girish T. Prescription Drug Labeling Medication Errors: A Big Deal for Pharmacists. *J Young Pharm.* 2010;2(1):107–11. https://pmc.ncbi.nlm.nih.gov/articles/PMC3035877/ | Tier 3 — Wolf: n = 395, in-person interviews, 3 primary-care clinics, 5 common medications; Jeetu is a narrative review, not the primary study | Per-label misunderstanding in Wolf ranged 8–33%; low literacy 63% vs marginal 51% vs adequate 38% misunderstanding (p < 0.001). A follow-up Davis et al. study (n = 359, 10 labels) found understanding only 53–89% per label and summarised the earlier work as "nearly half" misunderstanding. The 46% "at least one label" summary is plausible from that programme but is not in Wolf's abstract — cite Wolf as primary and Jeetu only as the secondary source of the 46% aggregation | A general "primary-care adults" rate today, a rate for older adults specifically, or that misunderstanding a label equals taking the wrong pill — this was a comprehension / demonstration task, not observed administration |
| 69.2% of older adults with low literacy and polypharmacy reported a self-administration error in the last 6 months | Ghassab-Abdollahi N, Nadrian H, Shaseb E, Kheirollahi N, Hashemiparast M. Self-administration medication errors at home and its predictors among illiterate and low-literate community-dwelling older adults with polypharmacy. *PLoS ONE.* 2024;19(4):e0302177. https://journals.plos.org/plosone/article%3Fid=10.1371/journal.pone.0302177 | Tier 3 — single-city cross-sectional study, Tabriz, Iran, n = 276 | In that defined population — age 60+, illiterate or ≤5 years' education, taking ≥5 medicines, community-dwelling, excluding dementia / nursing-home / homebound — 69.2% had ≥1 self-administration error in the last 6 months; ~16% had ≥4; most common were forgetting, improper timing, improper taking with food, lower dose, forgetting doctor's instructions; ~18% reported an adverse event after a mistake | A US or general older-adult rate; a causal role for literacy alone (illiteracy, doctor-visit pattern, number of medicines and medication beliefs were all predictors); or that photo-matching would prevent the dominant errors — forgetting and timing, not pill identification, topped the list |
| Systematic review found 25 generic pill-identification apps | Ciapponi A, Donato M, Gülmezoglu AM, Alconada T, Bardach A. Mobile apps for detecting falsified and substandard drugs: A systematic review. *PLoS ONE.* 2021;16(2):e0246061. https://www.ncbi.nlm.nih.gov/pmc/articles/PMC7861418/ | Tier 1 systematic review (Jan 2020 search), but scoped to falsified/substandard-drug detection, not reconciliation | 25 apps included (8 App Store, 8 Google Play, 8 both, 1 via Scholar/MedRxiv) plus 16 websites; most used imprint, colour or shape, only a few offered photo or barcode detection; mean MARS quality 3.17 ("acceptable"); authors found a "remarkable evidence gap" on accuracy and only one accuracy report | That none did closed-set reconciliation against the patient's own list, or that none was self-hostable open source — the review did not code either feature. That second clause needs PillTray's own dated audit, not this citation |
| Medication reconciliation reduces discrepancies — but with what certainty? | Redmond P, Grimes TC, McDonnell R, Boland F, Hughes C, Fahey T. Impact of medication reconciliation for improving transitions of care. *Cochrane Database Syst Rev.* 2018;8:CD010791. https://www.cochrane.org/evidence/CD010791_what-interventions-improve-accuracy-and-continuity-medication-lists-patients-move-between-healthcare | Tier 1 Cochrane review, very-low-certainty evidence for its main outcome | 25 RCTs, 6,995 participants, mostly pharmacist-delivered, hospital / transition settings: pooled RR 0.53 (95% CI 0.42–0.67; 20 studies, 4,629 participants) for having ≥1 discrepancy — but the authors' conclusion is that the effect is uncertain because certainty is very low, with no certainty on adverse drug events or healthcare utilisation | That reconciliation — let alone an automated photo version, at home, without a pharmacist — improves clinical outcomes, prevents harm, or reduces admissions. It supports "discrepancies are common and worth checking," not "reconciliation is proven effective" |
| Closed-set matching of pills against the patient's own small list | No direct study found in searches for photo-matching against a patient's own list as a reconciliation method | — (absence of evidence) | Nothing yet — this is a finding, not a licence to claim it. A smaller candidate set should logically be easier than open-set identification over thousands of pills, but that is reasoning, not a measured accuracy | That closed-set photo matching is accurate, safe, or superior to manual checking. It must be presented as an unvalidated method until tested |

## Known gaps

1. **Closed-set photo reconciliation accuracy: no direct study found.**
   Closing this needs a prospective home-photo study with ground truth =
   pharmacist-verified bottle list; report per-medicine sensitivity,
   false-positive rate, and adjudicated cause for every "missing" item
   (not photographed / obscured / misrecognised / genuinely absent),
   stratified by lighting, pill similarity, and number of medicines.
2. **"Missing = photo problem vs real gap" frequency: no quantification
   found.** The report cannot distinguish these causes today, which is why
   the README says to retake or manually confirm before acting. The
   adjudication arm of Gap 1 would yield the split directly.
3. **Reconciliation → outcomes:** Cochrane 2018 is very-low certainty and
   hospital-based. Closing this needs an RCT of home photo-reconciliation
   (with pharmacist review) vs usual care, powered for discrepancies and
   adverse drug events / utilisation — not just list accuracy.
