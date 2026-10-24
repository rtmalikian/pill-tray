"""Closed-set scoring: identical meds score high, look-alikes tie."""

from app.pilltray import features


def _cand(med_id, colour, shape, size, bucket):
    return {"med_id": med_id, "colour": colour, "shape": shape,
            "size": size, "marking_bucket": bucket}


def test_exact_match_scores_at_ceiling():
    obs = {"colour": "white", "shape": "round", "size": "M",
           "marking_bucket": "some"}
    scored = features.score_candidates(
        obs, [_cand("a", "white", "round", "M", "some")])
    assert scored[0]["score"] == 0.90
    assert features.classify(scored) == "confident"


def test_lookalike_pair_ties_and_is_ambiguous():
    # Lisinopril (3 marks) vs Amlodipine (4 marks): same colour, shape,
    # size, and coarse bucket. The coarse pass must NOT guess.
    obs = {"colour": "white", "shape": "round", "size": "M",
           "marking_bucket": "some"}
    cands = [_cand("med-1", "white", "round", "M", "some"),
             _cand("med-2", "white", "round", "M", "some"),
             _cand("med-3", "yellow", "oval", "L", "few")]
    scored = features.score_candidates(obs, cands)
    assert scored[0]["score"] == scored[1]["score"] == 0.90
    assert features.classify(scored) == "ambiguous"


def test_unknown_colour_pill_is_unmatched_not_guessed():
    obs = {"colour": "blue", "shape": "round", "size": "M",
           "marking_bucket": "few"}
    cands = [_cand("med-1", "white", "round", "M", "some"),
             _cand("med-3", "yellow", "oval", "L", "few")]
    scored = features.score_candidates(obs, cands)
    assert features.classify(scored) == "unmatched"


def test_marking_bucket_boundaries():
    assert features.marking_bucket(2) == "few"
    assert features.marking_bucket(3) == "some"
    assert features.marking_bucket(4) == "some"
    assert features.marking_bucket(5) == "many"
    assert features.marking_bucket(54, from_px=True) == "some"
    assert features.marking_bucket(90, from_px=True) == "many"
