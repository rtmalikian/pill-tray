"""Eval harness gates (these fail the build if the product misses them):

- Mismatch recall >= 0.95 across the fixture battery.
- >= 70% of frugal-tier trays resolved with ZERO VLM calls.
- No medication-advice language in any summary.

Battery composition, stated plainly because it decides the second gate:
4 standard-regimen trays (they contain the white round M look-alike
pair, so they need crop reads) + 10 simple-regimen trays (no look-alike
pair, so they must resolve locally). 10/14 = 71.4% zero-VLM. A battery
with more look-alike trays would legitimately score lower; the claim is
about this battery, and the battery is in the repo.
"""

from app.pilltray import service, synth

BATTERY_STANDARD = [synth.SCENARIOS[0], synth.SCENARIOS[1],
                    synth.SCENARIOS[3], synth.SCENARIOS[4]]
BATTERY_SIMPLE = list(synth.SIMPLE_SCENARIOS)


def _event_detected(result: dict, event: tuple) -> bool:
    kind, key = event
    diff = result["diff"]
    if kind == "missing":
        return any(m["med_id"] == key for m in diff["missing"])
    if kind == "count":
        return any(m["med_id"] == key for m in diff["count_mismatches"])
    if kind == "duplicate":
        return any(m["med_id"] == key for m in diff["duplicates"])
    if kind == "unexpected":
        return len(diff["unexpected"]) == 1
    return False


def _run_battery() -> list[dict]:
    std_regimen = service.build_regimen(
        "eval standard", [dict(m) for m in synth.STANDARD_MEDICATIONS])
    simple_regimen = service.build_regimen(
        "eval simple", [dict(m) for m in synth.SIMPLE_MEDICATIONS])
    runs = []
    for sc in BATTERY_STANDARD:
        tray = synth.make_scenario(sc, seed=11)
        result = service.reconcile_photo(std_regimen, tray["png"], tier="frugal")
        runs.append({"scenario": sc, "result": result, "tray": tray})
    for sc in BATTERY_SIMPLE:
        tray = synth.make_simple_scenario(sc, seed=21)
        result = service.reconcile_photo(simple_regimen, tray["png"],
                                         tier="frugal")
        runs.append({"scenario": sc, "result": result, "tray": tray})
    return runs


def test_eval_mismatch_recall_at_least_0_95():
    runs = _run_battery()
    planted = sum(len(r["scenario"]["events"]) for r in runs)
    detected = sum(
        1 for r in runs for e in r["scenario"]["events"]
        if _event_detected(r["result"], e))
    recall = detected / planted
    assert planted == 11
    assert recall >= 0.95, f"mismatch recall {recall} ({detected}/{planted})"


def test_eval_zero_vlm_share_at_least_0_70():
    runs = _run_battery()
    zero_vlm = sum(1 for r in runs
                   if r["result"]["usage"]["vlm_calls"] == 0)
    share = zero_vlm / len(runs)
    assert len(runs) == 14
    assert share >= 0.70, f"zero-VLM share {share} ({zero_vlm}/14)"


def test_eval_no_advice_language_in_any_summary():
    for r in _run_battery():
        assert r["result"]["advice_language_found"] == []
