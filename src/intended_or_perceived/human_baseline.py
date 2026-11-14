"""Individual listener baselines from retained CREMA-D voice votes."""

from collections import Counter, defaultdict
from collections.abc import Mapping
from math import isclose
from pathlib import Path
from statistics import mean
from typing import TypedDict

from .dataset import (
    EMOTIONS,
    FILENAME_PATTERN,
    RAW,
    SOURCE_HASHES,
    VOTE_LABELS,
    agreement_stratum,
    cached_source,
    plurality,
    response_key,
    rows,
    vote_tuple,
)


class ListenerBaseline(TypedDict):
    listener_intended: float
    listener_perceived: float
    listener_count: int
    listener_response_count: int


def _score_clip(
    raters: Mapping[str, Counter[str]], counts: Counter[str], intended: str
) -> ListenerBaseline:
    if len(raters) < 2:
        raise ValueError(
            "Leave-one-rater-out scoring needs at least two retained listeners"
        )
    intended_matches = []
    perceived_matches = []
    for responses in raters.values():
        remaining_plurality = plurality(vote_tuple(counts - responses))
        n = responses.total()
        intended_matches.append(responses[intended] / n)
        perceived_matches.append(
            sum(responses[label] for label in remaining_plurality) / n
        )
    return {
        "listener_intended": mean(intended_matches),
        "listener_perceived": mean(perceived_matches),
        "listener_count": len(raters),
        "listener_response_count": counts.total(),
    }


def listener_baselines(
    manifest_rows: list[dict[str, str]], metadata: Path
) -> dict[str, ListenerBaseline]:
    """Validate a manifest join and return equally weighted rater scores per clip."""
    for relative, digest in SOURCE_HASHES.items():
        cached_source(metadata / relative, f"{RAW}/{relative}", digest, online=False)

    stimulus_numbers = {
        row["Filename"]: int(row["Stimulus_Number"])
        for row in rows(metadata / "SentenceFilenames.csv")
    }
    samples = {}
    sample_ids = set()
    for row in manifest_rows:
        sample_id = row["sample_id"]
        stem = row["filename"].removesuffix(".mp3")
        match = FILENAME_PATTERN.fullmatch(stem)
        if match is None or stem not in stimulus_numbers:
            raise ValueError(f"Unknown CREMA-D stimulus for {sample_id}")
        actor, sentence, emotion, intensity = match.groups()
        if (
            sample_id in sample_ids
            or stimulus_numbers[stem] in samples
            or row["filename"] != f"{stem}.mp3"
            or row["actor"] != actor
            or row["sentence"] != sentence
            or row["intended_emotion"] != EMOTIONS[emotion]
            or row["intensity"] != intensity
        ):
            raise ValueError(f"Inconsistent manifest identity for {sample_id}")
        samples[stimulus_numbers[stem]] = (row, stem)
        sample_ids.add(sample_id)

    delayed = {
        response_key(row)
        for row in rows(metadata / "finishedEmoResponses.csv")
        if row["queryType"] == "1" and row["ttr"] != "NULL" and int(row["ttr"]) > 10_000
    }
    ballots = defaultdict(lambda: defaultdict(Counter))
    for row in rows(metadata / "finishedResponses.csv"):
        if row["queryType"] != "1" or response_key(row) in delayed:
            continue
        stimulus_number = int(row["clipNum"])
        if stimulus_number not in samples:
            continue
        sample, stem = samples[stimulus_number]
        if (
            row["clipName"] != stem
            or row["respEmo"] not in VOTE_LABELS
            or not row["localid"]
        ):
            raise ValueError(
                f"Invalid retained voice response for {sample['sample_id']}"
            )
        ballots[stimulus_number][row["localid"]][row["respEmo"]] += 1

    published = {}
    for row in rows(metadata / "processedResults/tabulatedVotes.csv"):
        modality, stimulus_number = divmod(int(row[""]), 100_000)
        if modality == 1 and stimulus_number in samples:
            published[stimulus_number] = (
                row["fileName"],
                tuple(int(row[code]) for code in VOTE_LABELS),
                int(row["numResponses"]),
            )

    vote_by_emotion = {name: code for code, name in VOTE_LABELS.items()}
    baseline = {}
    for stimulus_number, (row, stem) in samples.items():
        raters = ballots[stimulus_number]
        counts = Counter()
        for responses in raters.values():
            counts.update(responses)
        sample_id = row["sample_id"]
        counts_by_label = vote_tuple(counts)
        total = counts.total()
        if (
            total < 6
            or (stem, counts_by_label, total) != published.get(stimulus_number)
            or counts_by_label
            != tuple(int(row[f"voice_{code}"]) for code in VOTE_LABELS)
            or total != int(row["voice_n"])
        ):
            raise ValueError(
                f"Voice votes disagree with the frozen manifest or published table for {sample_id}"
            )
        tied_labels = plurality(counts_by_label)
        if (
            ":".join(VOTE_LABELS[code] for code in tied_labels) != row["voice_majority"]
            or int(len(tied_labels) > 1) != int(row["voice_tie"])
            or not isclose(
                max(counts_by_label) / total,
                float(row["voice_agreement"]),
                abs_tol=1e-8,
            )
            or agreement_stratum(counts_by_label) != row["stratum"]
        ):
            raise ValueError(
                f"Voice plurality or agreement disagrees with the frozen manifest for {sample_id}"
            )
        baseline[sample_id] = _score_clip(
            raters, counts, vote_by_emotion[row["intended_emotion"]]
        )
    return baseline
