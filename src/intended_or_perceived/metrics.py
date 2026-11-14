"""Compute study metrics on the caller's eligible clips."""

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from math import floor, fsum, isclose, isfinite, log2, sqrt
from random import Random

from intended_or_perceived.scoring import EMOTIONS

Reference = str | Iterable[str]
ProbabilityVector = Sequence[float] | Mapping[str, float]
_LABEL_INDEX = {label: index for index, label in enumerate(EMOTIONS)}


def mean(values: Iterable[float | None]) -> float | None:
    """Average finite observations, leaving an empty denominator undefined."""
    present = [value for value in values if value is not None]
    if not all(isfinite(value) for value in present):
        raise ValueError("Use None for undefined observations")
    return fsum(present) / len(present) if present else None


def _reference_labels(reference: Reference) -> set[str]:
    labels = set(reference.split(":") if isinstance(reference, str) else reference)
    if not labels or not labels <= _LABEL_INDEX.keys():
        raise ValueError("A reference must contain one or more study labels")
    return labels


def accuracy(
    predictions: Iterable[str | None], references: Iterable[Reference]
) -> float | None:
    """Count a match on any tied label and omit unknown predictions."""
    return mean(
        prediction in _reference_labels(reference)
        for prediction, reference in zip(predictions, references, strict=True)
        if prediction is not None
    )


def baseline_accuracies(
    references: Iterable[Reference],
) -> dict[str, float | str | None]:
    """Evaluate fixed Neutral and majority predictions on the supplied references."""
    counts = Counter()
    size = 0
    for reference in references:
        counts.update(_reference_labels(reference))
        size += 1
    if not size:
        return {"always_neutral": None, "majority": None, "majority_label": None}
    majority = max(EMOTIONS, key=counts.__getitem__)
    return {
        "always_neutral": counts["Neutral"] / size,
        "majority": counts[majority] / size,
        "majority_label": majority,
    }


def classification_metrics(
    predictions: Iterable[str | None], references: Iterable[Reference]
) -> dict[str, list[list[int]] | float | None]:
    """Compute single-label metrics with true rows and predicted columns in study order."""
    size = len(EMOTIONS)
    confusion = [[0] * size for _ in range(size)]
    for prediction, reference in zip(predictions, references, strict=True):
        if prediction is None:
            continue
        labels = _reference_labels(reference)
        if len(labels) != 1 or prediction not in _LABEL_INDEX:
            raise ValueError("Multiclass metrics require single study labels")
        actual = labels.pop()
        confusion[_LABEL_INDEX[actual]][_LABEL_INDEX[prediction]] += 1

    actual_counts = list(map(sum, confusion))
    predicted_counts = list(map(sum, zip(*confusion, strict=True)))
    true_positives = [confusion[index][index] for index in range(size)]
    total = sum(actual_counts)
    if not total:
        return {"confusion": confusion, "macro_f1": None, "mcc": None}

    # Include all six study labels. A class absent from both marginals
    # contributes zero to the fixed-label macro average.
    sums = map(sum, zip(actual_counts, predicted_counts, strict=True))
    f1_by_class = [
        2 * true_positive / denominator if denominator else 0.0
        for true_positive, denominator in zip(true_positives, sums, strict=True)
    ]
    accuracy_covariance = total * sum(true_positives) - sum(
        actual * predicted
        for actual, predicted in zip(actual_counts, predicted_counts, strict=True)
    )
    actual_variance = total**2 - sum(count**2 for count in actual_counts)
    predicted_variance = total**2 - sum(count**2 for count in predicted_counts)
    denominator = sqrt(actual_variance * predicted_variance)
    return {
        "confusion": confusion,
        "macro_f1": fsum(f1_by_class) / size,
        "mcc": accuracy_covariance / denominator if denominator else None,
    }


def _percentile(ordered: Sequence[float], probability: float) -> float:
    position = (len(ordered) - 1) * probability
    index = floor(position)
    fraction = position - index
    if not fraction:
        return ordered[index]
    return ordered[index] + fraction * (ordered[index + 1] - ordered[index])


def actor_bootstrap(
    actors: Sequence[str],
    columns: Mapping[str, Sequence[float | None]],
    *,
    differences: Mapping[str, tuple[str, str]] | None = None,
    replicates: int = 2000,
    seed: int = 20261112,
) -> dict[str, dict[str, float | None]]:
    """Draw sorted actor IDs with replacement and keep their clips paired.

    Input columns hold per-clip values and may mark an unavailable observation
    with None. Differences use only the paired nonmissing clips. Percentile
    bounds use linear interpolation and omit undefined replicates.
    """
    if replicates < 1:
        raise ValueError("At least one bootstrap replicate is required")
    if any(len(column) != len(actors) for column in columns.values()):
        raise ValueError("Actor IDs and bootstrap columns must align")
    eligible = dict(columns)
    for name, (left, right) in (differences or {}).items():
        if name in eligible or left not in columns or right not in columns:
            raise ValueError(
                "Bootstrap differences require distinct names and existing columns"
            )
        eligible[name] = [
            x - y if x is not None and y is not None else None
            for x, y in zip(columns[left], columns[right], strict=True)
        ]
    intervals = {
        name: {"estimate": mean(column), "lower": None, "upper": None}
        for name, column in eligible.items()
    }
    actor_ids = sorted(set(actors))
    if not actor_ids:
        return intervals

    indices = {actor: index for index, actor in enumerate(actor_ids)}
    aggregates = {}
    for name, column in eligible.items():
        if intervals[name]["estimate"] is None:
            continue
        sums = [0.0] * len(actor_ids)
        counts = [0] * len(actor_ids)
        for actor, value in zip(actors, column, strict=True):
            if value is not None:
                index = indices[actor]
                sums[index] += value
                counts[index] += 1
        aggregates[name] = (sums, counts)

    random = Random(seed)
    draws = {name: [] for name in aggregates}
    population = range(len(actor_ids))
    for _ in range(replicates):
        sampled = random.choices(population, k=len(population))
        for name, (sums, counts) in aggregates.items():
            denominator = sum(counts[index] for index in sampled)
            if denominator:
                draws[name].append(fsum(sums[index] for index in sampled) / denominator)
    for name, values in draws.items():
        if values:
            values.sort()
            intervals[name].update(
                lower=_percentile(values, 0.025), upper=_percentile(values, 0.975)
            )
    return intervals


def _ranks(values: Sequence[float]) -> list[float]:
    ordered = sorted(range(len(values)), key=values.__getitem__)
    ranks = [0.0] * len(values)
    start = 0
    while start < len(ordered):
        end = start + 1
        while end < len(ordered) and values[ordered[start]] == values[ordered[end]]:
            end += 1
        average_rank = (start + 1 + end) / 2
        for index in ordered[start:end]:
            ranks[index] = average_rank
        start = end
    return ranks


def spearman(x: Iterable[float | None], y: Iterable[float | None]) -> float | None:
    """Return Pearson correlation of average ranks for complete pairs."""
    pairs = [
        (a, b) for a, b in zip(x, y, strict=True) if a is not None and b is not None
    ]
    if len(pairs) < 2:
        return None
    a, b = zip(*pairs, strict=True)
    if not all(map(isfinite, (*a, *b))):
        raise ValueError("Use None for undefined observations")
    middle = (len(pairs) + 1) / 2
    a_centered = [rank - middle for rank in _ranks(a)]
    b_centered = [rank - middle for rank in _ranks(b)]
    denominator = sqrt(
        fsum(rank**2 for rank in a_centered) * fsum(rank**2 for rank in b_centered)
    )
    covariance = fsum(
        left * right for left, right in zip(a_centered, b_centered, strict=True)
    )
    return covariance / denominator if denominator else None


def _probabilities(vector: ProbabilityVector) -> tuple[float, ...]:
    if isinstance(vector, Mapping):
        if vector.keys() != _LABEL_INDEX.keys():
            raise ValueError("A distribution must include all six study labels")
        values = tuple(vector[label] for label in EMOTIONS)
    else:
        values = tuple(vector)
    if (
        len(values) != len(EMOTIONS)
        or not all(0 <= value <= 1 for value in values)
        or not isclose(fsum(values), 1, abs_tol=1e-8)
    ):
        raise ValueError("A distribution must have six probabilities summing to one")
    return values


def jensen_shannon(p: ProbabilityVector, q: ProbabilityVector) -> float:
    """Base-2 Jensen–Shannon divergence from zero for identity to one for disjoint support."""
    terms = []
    for left, right in zip(_probabilities(p), _probabilities(q), strict=True):
        if not (left or right):
            continue
        # Compute log2 of the midpoint without halving a tiny subnormal value.
        log_midpoint = log2(left + right) - 1
        if left:
            terms.append(left * (log2(left) - log_midpoint))
        if right:
            terms.append(right * (log2(right) - log_midpoint))
    return max(0.0, fsum(terms) / 2)


def brier(p: ProbabilityVector, q: ProbabilityVector) -> float:
    """Sum squared distances over the six outcome probabilities."""
    return fsum(
        (left - right) ** 2
        for left, right in zip(_probabilities(p), _probabilities(q), strict=True)
    )


def _repeat_counts(ratings: Iterable[Sequence[str | None]]) -> list[Counter[str]]:
    rows = [Counter(row) for row in ratings if None not in row]
    if rows:
        repeats = sum(rows[0].values())
        if repeats < 2 or any(
            sum(counts.values()) != repeats or not counts.keys() <= _LABEL_INDEX.keys()
            for counts in rows
        ):
            raise ValueError("Repeat rows must contain the same number of study labels")
    return rows


def fleiss_kappa(ratings: Iterable[Sequence[str | None]]) -> float | None:
    """Estimate Fleiss' kappa over clips with a complete set of repeat labels."""
    rows = _repeat_counts(ratings)
    if not rows:
        return None
    repeats = sum(rows[0].values())
    totals = Counter()
    agreeing_pairs = 0
    for counts in rows:
        totals.update(counts)
        agreeing_pairs += sum(count * (count - 1) for count in counts.values())
    assignments = len(rows) * repeats
    expected_numerator = sum(count**2 for count in totals.values())
    denominator = assignments**2 - expected_numerator
    if not denominator:
        return None
    return (agreeing_pairs * assignments - expected_numerator * (repeats - 1)) / (
        denominator * (repeats - 1)
    )


def flip_rate(ratings: Iterable[Sequence[str | None]]) -> float | None:
    """Return the fraction of complete clips with at least one changed repeat label."""
    return mean(len(counts) > 1 for counts in _repeat_counts(ratings))


def score_range(scores: Iterable[float | None]) -> float | None:
    """Compute the range on a common denominator, requiring each score."""
    scores = tuple(scores)
    if not scores or any(score is None for score in scores):
        return None
    if not all(map(isfinite, scores)):
        raise ValueError("Use None for undefined observations")
    return max(scores) - min(scores)


def label_change_rate(
    first: Iterable[str | None], second: Iterable[str | None]
) -> float | None:
    """Return the label change rate over pairs of valid responses."""
    return mean(
        a != b
        for a, b in zip(first, second, strict=True)
        if a is not None and b is not None
    )
