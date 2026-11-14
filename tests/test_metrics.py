from math import log2

import pytest

from intended_or_perceived.metrics import (
    accuracy,
    actor_bootstrap,
    baseline_accuracies,
    brier,
    classification_metrics,
    fleiss_kappa,
    flip_rate,
    jensen_shannon,
    label_change_rate,
    mean,
    score_range,
    spearman,
)
from intended_or_perceived.scoring import EMOTIONS


def test_mean_omits_undefined_without_coercing_to_zero():
    assert mean([1, None, 0, 0]) == pytest.approx(1 / 3)
    assert mean([None]) is None
    with pytest.raises(ValueError, match="None"):
        mean([float("inf")])


def test_accuracy_matches_ties_and_omits_unknown():
    predicted = ["Fear", None, "Neutral", "Sad"]
    reference = ["Fear:Happy", "Disgust", "Sad", {"Neutral", "Sad"}]
    assert accuracy(predicted, reference) == pytest.approx(2 / 3)
    assert accuracy([None], ["Anger"]) is None
    with pytest.raises(ValueError):
        accuracy(predicted, reference[:-1])


def test_baselines_count_pluralities_once_and_break_ties_canonically():
    reference = ["Neutral:Sad:Neutral", "Fear", "Anger:Fear", "Anger"]
    assert baseline_accuracies(reference) == {
        "always_neutral": 0.25,
        "majority": 0.5,
        "majority_label": "Anger",
    }
    assert baseline_accuracies([]) == dict.fromkeys(
        ("always_neutral", "majority", "majority_label")
    )
    with pytest.raises(ValueError):
        baseline_accuracies(["anger"])


def test_classification_metrics_orientation_and_closed_form():
    predicted = ["Anger", "Fear", "Fear", "Neutral", "Anger", None]
    reference = ["Anger", "Anger", "Fear", "Neutral", "Neutral", "Neutral"]
    result = classification_metrics(predicted, reference)
    assert result["confusion"] == [
        [1, 0, 1, 0, 0, 0],
        [0, 0, 0, 0, 0, 0],
        [0, 0, 1, 0, 0, 0],
        [0, 0, 0, 0, 0, 0],
        [1, 0, 0, 0, 1, 0],
        [0, 0, 0, 0, 0, 0],
    ]
    # F1s 1/2, 0, 2/3, 0, 2/3, 0. MCC numerator 5*3 - 8, denominator 16.
    assert result["macro_f1"] == pytest.approx(11 / 36)
    assert result["mcc"] == pytest.approx(7 / 16)


def test_classification_undefined_mcc_and_empty_macro():
    result = classification_metrics(["Neutral", "Neutral"], ["Neutral", "Neutral"])
    assert result["macro_f1"] == pytest.approx(1 / 6)
    assert result["mcc"] is None
    result = classification_metrics([None], ["Neutral"])
    assert result["confusion"] == [[0] * 6 for _ in range(6)]
    assert result["macro_f1"] is result["mcc"] is None
    with pytest.raises(ValueError, match="single study labels"):
        classification_metrics(["Neutral"], ["Neutral:Anger"])


def test_actor_bootstrap_resamples_whole_unequal_clusters_with_shared_draws():
    # Seed 1 gives draws AB, BA, AA, BB with sorted actors A, B. A has one
    # clip and B has three. The four differences are 1/4, 1/4, -1, 2/3.
    result = actor_bootstrap(
        ["A", "B", "B", "B"],
        {"intended": [1, 0, 0, 1], "perceived": [0, 1, 1, 1]},
        differences={"delta": ("perceived", "intended")},
        replicates=4,
        seed=1,
    )
    assert result["intended"] == pytest.approx(
        {"estimate": 1 / 2, "lower": 83 / 240, "upper": 77 / 80}
    )
    assert result["perceived"] == pytest.approx(
        {"estimate": 3 / 4, "lower": 9 / 160, "upper": 157 / 160}
    )
    assert result["delta"] == pytest.approx(
        {"estimate": 1 / 4, "lower": -29 / 32, "upper": 61 / 96}
    )


def test_actor_bootstrap_paired_missingness_and_undefined_intervals():
    columns = {"a": [None, 0.75, 1], "b": [0, 0.25, None], "empty": [None] * 3}
    outcomes = actor_bootstrap(["A", "B", "B"], columns, differences={"d": ("a", "b")})
    # Only the first clip by B has scores in both columns. Some draws omit B.
    assert outcomes["d"] == {"estimate": 0.5, "lower": 0.5, "upper": 0.5}
    assert outcomes["empty"] == dict.fromkeys(("estimate", "lower", "upper"))
    assert actor_bootstrap([], {"a": []}) == {"a": outcomes["empty"]}
    assert outcomes == actor_bootstrap(
        ["A", "B", "B"], columns, differences={"d": ("a", "b")}
    )
    with pytest.raises(ValueError, match="align"):
        actor_bootstrap(["A"], {"a": [0, 1]})


def test_spearman_average_tied_ranks_and_undefined_correlations():
    # Centered ranks (-1,-1,1/2,3/2) and (-3/2,0,0,3/2) have
    # covariance numerator 15/4 and each sum of squared ranks is 9/2.
    assert spearman([1, 1, 2, 3, None], [1, 2, 2, 3, 1]) == pytest.approx(5 / 6)
    assert spearman([1, 2, 3], [9, 8, 7]) == -1
    assert spearman([0, 0, 0], [1, 2, 3]) is None
    assert spearman([1], [2]) is None
    assert spearman([], []) is None


def test_distribution_metrics_brier_sum_and_js_base_two():
    angry = [1, 0, 0, 0, 0, 0]
    fear = [0, 0, 1, 0, 0, 0]
    half = dict(zip(EMOTIONS, [0.5, 0, 0.5, 0, 0, 0], strict=True))
    assert jensen_shannon(angry, angry) == 0
    assert jensen_shannon(angry, fear) == 1
    assert jensen_shannon(angry, half) == pytest.approx(1.5 - 0.75 * log2(3))
    assert jensen_shannon(half, angry) == jensen_shannon(angry, half)
    assert brier(angry, angry) == 0
    assert brier(angry, fear) == 2
    assert brier(angry, half) == 0.5
    assert jensen_shannon([1, 5e-324, 0, 0, 0, 0], angry) >= 0
    with pytest.raises(ValueError, match="summing to one"):
        brier([0.5, 0, 0, 0, 0, 0], fear)


def test_repeat_metrics_share_complete_rows_and_handle_no_expected_disagreement():
    ratings = [
        ["Anger", "Anger", "Fear"],
        ["Fear", "Fear", "Fear"],
        ["Anger", "Anger", "Anger"],
        [None, "Sad", "Happy"],
    ]
    # P_obs 7/9 from clip agreements 1/3, 1 and 1. P_expected 41/81
    # from pooled Anger and Fear proportions 5/9 and 4/9.
    assert fleiss_kappa(ratings) == pytest.approx(11 / 20)
    assert flip_rate(ratings) == pytest.approx(1 / 3)
    assert fleiss_kappa([["Anger", "Fear", "Neutral"]] * 2) == -0.5
    assert fleiss_kappa([["Fear"] * 3] * 2) is None
    assert flip_rate([["Fear"] * 3] * 2) == 0
    assert fleiss_kappa([[None, "Fear", "Fear"]]) is None
    assert flip_rate([[None, "Fear", "Fear"]]) is None
    with pytest.raises(ValueError, match="same number"):
        fleiss_kappa([["Fear", "Fear"], ["Anger", "Fear", "Fear"]])


def test_score_range_and_prompt_change_use_complete_pairs():
    assert score_range([0.3, 0.5, 0.4]) == pytest.approx(0.2)
    assert score_range([0.3, None]) is None
    assert score_range([]) is None
    assert label_change_rate(["Anger", "Fear", None], ["Neutral", "Fear", "Sad"]) == 0.5
    assert label_change_rate([None], ["Anger"]) is None
