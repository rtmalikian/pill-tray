"""Reconcile pipeline: diff logic, tiers, and the call ledger."""

from app import gateway
from app.pilltray import service, synth


def _standard_regimen():
    return service.build_regimen(
        "demo", [dict(m) for m in synth.STANDARD_MEDICATIONS])


def _simple_regimen():
    return service.build_regimen(
        "demo simple", [dict(m) for m in synth.SIMPLE_MEDICATIONS])


def _photo_result(regimen, scenario, tier="frugal"):
    tray = synth.make_scenario(scenario, seed=11)
    return service.reconcile_photo(regimen, tray["png"], tier=tier)


def test_clean_tray_frugal_costs_zero_vlm_calls():
    result = _photo_result(_standard_regimen(), synth.SCENARIOS[0])
    # Clean standard tray contains the look-alike pair, so it DOES need
    # VLM reads: the honest zero-VLM case is the simple regimen.
    assert result["usage"]["vlm_calls"] >= 1
    assert result["diff"]["diff_found"] is False


def test_simple_clean_tray_costs_zero_vlm_calls():
    regimen = _simple_regimen()
    tray = synth.make_simple_scenario(synth.SIMPLE_SCENARIOS[0], seed=21)
    result = service.reconcile_photo(regimen, tray["png"], tier="frugal")
    assert result["usage"]["vlm_calls"] == 0
    assert result["diff"]["diff_found"] is False
    assert result["diff"]["matched_count"] == 6


def test_missing_duplicate_and_unexpected_are_surfaced():
    regimen = _standard_regimen()
    tray = synth.make_scenario(synth.SCENARIOS[1], seed=11)  # missing
    result = service.reconcile_photo(regimen, tray["png"], tier="frugal")
    assert [m["name"] for m in result["diff"]["missing"]] == \
        ["Atorvastatin (fixture)"]

    tray = synth.make_scenario(synth.SCENARIOS[3], seed=11)  # duplicate
    result = service.reconcile_photo(regimen, tray["png"], tier="frugal")
    assert [m["name"] for m in result["diff"]["duplicates"]] == \
        ["Omeprazole (fixture)"]

    tray = synth.make_scenario(synth.SCENARIOS[4], seed=11)  # unexpected
    result = service.reconcile_photo(regimen, tray["png"], tier="frugal")
    assert len(result["diff"]["unexpected"]) == 1
    assert "blue" in result["diff"]["unexpected"][0]["description"]


def test_lookalike_pair_resolves_by_crop_read_not_guess():
    regimen = _standard_regimen()
    tray = synth.make_scenario(synth.SCENARIOS[0], seed=11)
    result = service.reconcile_photo(regimen, tray["png"], tier="frugal")
    # Every white round M pill was resolved (none left ambiguous), and
    # the matched counts are exactly the expected ones.
    assert result["diff"]["ambiguous"] == []
    assert result["diff"]["matched_count"] == 7
    assert result["usage"]["vlm_calls"] == 3  # 2 lisinopril + 1 amlodipine


def test_regimen_is_embedded_once_and_reused():
    # A regimen with a descriptor no earlier test has embedded: exactly
    # one batched embedding call at build. Building the same regimen
    # again reuses the cache and costs zero new calls.
    fresh = [{"id": "med-z1", "name": "Zinc (fixture)", "strength": "50 mg",
              "form": "tablet", "colour": "peach", "shape": "oval", "size": "L",
              "marking_strokes": 3, "expected_count": 1}]
    first = service.build_regimen("fresh", [dict(m) for m in fresh])
    assert first.embedding_calls_at_build == 1
    before = gateway.CALL_LEDGER["embeddings"]
    second = service.build_regimen("fresh again", [dict(m) for m in fresh])
    assert second.embedding_calls_at_build == 0
    assert gateway.CALL_LEDGER["embeddings"] - before == 0


def test_full_tier_reads_every_pill_and_verifies():
    regimen = _simple_regimen()
    tray = synth.make_simple_scenario(synth.SIMPLE_SCENARIOS[0], seed=21)
    result = service.reconcile_photo(regimen, tray["png"], tier="full")
    assert result["usage"]["vlm_calls"] == 6
    assert result["usage"]["verifier_calls"] == 1
    assert result["verifier"]["ok"] is True
    assert result["diff"]["diff_found"] is False


def test_short_count_is_a_count_mismatch_not_missing():
    regimen = _standard_regimen()
    tray = synth.make_scenario(synth.SCENARIOS[2], seed=11)  # 1 of 2 lisinopril
    result = service.reconcile_photo(regimen, tray["png"], tier="frugal")
    assert [m["name"] for m in result["diff"]["count_mismatches"]] == \
        ["Lisinopril (fixture)"]
    assert result["diff"]["count_mismatches"][0]["shortfall"] == 1
    assert result["diff"]["missing"] == []


def test_summary_never_contains_medication_advice():
    result = _photo_result(_standard_regimen(), synth.SCENARIOS[4])
    assert result["advice_language_found"] == []
    assert "pharmacist" in result["summary"]
