"""Detector: synthetic trays segment into the pills that were rendered."""

from app.pilltray import detector, synth


def test_clean_standard_tray_detects_all_pills():
    tray = synth.make_tray(synth._expand(synth.full_counts()), seed=11)
    arr = detector.load_image(tray["png"])
    pills = detector.detect_pills(arr)
    assert len(pills) == 7  # 2 + 1 + 1 + 2 + 1
    colours = sorted(p["colour"] for p in pills)
    assert colours.count("white") == 3
    assert colours.count("yellow") == 1
    assert colours.count("purple") == 2
    assert colours.count("orange") == 1


def test_detected_features_match_rendered_pills():
    med = dict(synth.STANDARD_MEDICATIONS[2])  # yellow oval L, 2 marks
    tray = synth.make_tray([med], seed=3)
    pills = detector.detect_pills(detector.load_image(tray["png"]))
    assert len(pills) == 1
    p = pills[0]
    assert p["colour"] == "yellow"
    assert p["shape"] == "oval"
    assert p["size"] == "L"
    assert p["marking_bucket"] == "few"
    # Two 6x3 strokes = 36 dark pixels, exactly.
    assert p["marking_exact"] == 36


def test_capsule_reads_as_oblong_not_oval():
    med = dict(synth.STANDARD_MEDICATIONS[3])  # purple oblong M
    tray = synth.make_tray([med], seed=3)
    pills = detector.detect_pills(detector.load_image(tray["png"]))
    assert len(pills) == 1
    assert pills[0]["shape"] == "oblong"


def test_lookalike_pair_differ_only_in_marking_exact():
    meds = [synth.STANDARD_MEDICATIONS[0], synth.STANDARD_MEDICATIONS[1]]
    tray = synth.make_tray(meds, seed=3)
    pills = detector.detect_pills(detector.load_image(tray["png"]))
    assert len(pills) == 2
    for p in pills:
        assert p["colour"] == "white"
        assert p["shape"] == "round"
        assert p["size"] == "M"
        assert p["marking_bucket"] == "some"
    counts = sorted(p["marking_exact"] for p in pills)
    assert counts == [54, 72]  # 3 strokes vs 4 strokes, 18 px each
