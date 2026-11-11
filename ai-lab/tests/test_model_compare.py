from experiments.model_compare.run import combine


def test_combine_weights_scores_and_skips_days_a_model_misses():
    scores = {"a": {("X", 1): 2.0, ("X", 2): 4.0}, "b": {("X", 1): -1.0}}
    assert combine(scores, {"a": 3, "b": 1}) == {("X", 1): 1.25}
