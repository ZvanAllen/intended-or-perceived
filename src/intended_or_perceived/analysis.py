"""Reproduce the frozen study analysis offline from the saved main runs."""

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from statistics import fmean

from intended_or_perceived.coverage_report import CONDITIONS, UNKNOWN, Run
from intended_or_perceived.human_baseline import listener_baselines
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
    score_range,
    spearman,
)
from intended_or_perceived.scoring import (
    EMOTIONS,
    parse_recorded_output,
    unwrap_markdown_fence,
)
from intended_or_perceived.third_run import ORIGINAL_MANIFEST

MODELS = (
    "openai/gpt-audio-1.5",
    "google/gemini-3.5-flash-lite",
    "google/gemini-4-carbon",
)
PARSERS = ("amended", "strict")
REFERENCES = ("intended", "perceived")
STRATA = ("low", "middle", "high")


def _write_csv(path: Path, rows: list[dict]) -> None:
    keys = dict.fromkeys(key for row in rows for key in row)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(keys), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _reference(clip, reference):
    return (
        clip["intended_emotion"] if reference == "intended" else clip["voice_majority"]
    )


def _matches(label, target):
    return int(label in target.split(":"))


def _argmax(distribution):
    maximum = max(distribution.values())
    return ":".join(label for label in EMOTIONS if distribution[label] == maximum)


def _digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_main(path, models, clips, manifest_hash):
    run = Run.read(path, "main", models)
    if run.manifest_hash != manifest_hash or run.stimuli.keys() != clips.keys():
        raise ValueError("Main checkpoint differs from the frozen manifest")
    saved = {}
    file = path / "transcripts.jsonl"
    for line in file.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        model, condition, sample = (
            row[key] for key in ("model", "condition", "sample_id")
        )
        key = model, condition, sample
        prompt = run.prompts[condition]
        if (
            key in saved
            or model not in models
            or sample not in clips
            or row["run_id"] != run.run_id
            or row["manifest_sha256"] != manifest_hash
            or row["media_sha256"] != clips[sample]["media_sha256"]
            or row["media_sha256"] != run.stimuli[sample]["sha256"]
            or (row["prompt"], row["prompt_file"], row["prompt_sha256"])
            != (prompt["family"], prompt["file"], prompt["sha256"])
        ):
            raise ValueError("A completion differs from the frozen main-run grid")
        saved[key] = row
    if len(saved) != len(models) * len(clips) * len(CONDITIONS):
        raise ValueError("The main-run grid is incomplete")
    return saved, run


def _responses(saved, clips, tables):
    indexed = {}
    for parser in PARSERS:
        for (model, condition, sample), row in saved.items():
            parsed = parse_recorded_output(row, unwrap_fence=parser == "amended")
            old = (
                row.get("strict_status", row["status"]) if parser == "strict" else None
            )
            if old is not None and old != parsed.status:
                raise ValueError("Strict re-parse disagrees with the recorded status")
            if (
                parser == "amended"
                and "strict_status" in row
                and row["status"] != parsed.status
            ):
                raise ValueError("Amended re-parse disagrees with the recorded status")
            clip = clips[sample]
            verdict = {
                "parser": parser,
                "model": model,
                "condition": condition,
                "sample_id": sample,
                "status": parsed.status,
                "label": parsed.label,
                "confidence": parsed.confidence,
                "intended_match": (
                    _matches(parsed.label, clip["intended_emotion"])
                    if parsed.label
                    else None
                ),
                "perceived_match": (
                    _matches(parsed.label, clip["voice_majority"])
                    if parsed.label
                    else None
                ),
                "probability_argmax": _argmax(parsed.distribution)
                if parsed.distribution
                else None,
            }
            if parsed.distribution:
                probs = [parsed.distribution[label] for label in EMOTIONS]
                human = [
                    int(clip[f"voice_{code}"]) / int(clip["voice_n"])
                    for code in "ADFHNS"
                ]
                verdict.update(
                    jensen_shannon=jensen_shannon(probs, human),
                    brier=brier(probs, human),
                )
                verdict.update(
                    {
                        f"p_{label.lower()}": parsed.distribution[label]
                        for label in EMOTIONS
                    }
                )
            indexed[parser, model, condition, sample] = verdict
            tables["per_clip_predictions"].append(verdict)
    return indexed


def _accuracy_row(
    parser, model, condition, scope, level, reference, wanted, valid, clips, labels
):
    targets = [_reference(clips[sample], reference) for sample in valid]
    return {
        "parser": parser,
        "model": model,
        "condition": condition,
        "scope": scope,
        "level": level,
        "reference": reference,
        "n_planned": len(wanted),
        "n_valid": len(valid),
        "n_actors": len({clips[sample]["actor"] for sample in valid}),
        "coverage": len(valid) / len(wanted) if wanted else None,
        "accuracy": accuracy(labels, targets),
        **baseline_accuracies(targets),
    }


def _descriptive_accuracy(parser, model, conditions, clips, tables):
    sample_ids = list(clips)
    untied = [sample for sample in sample_ids if clips[sample]["voice_tie"] == "0"]
    levels = {
        "stratum": STRATA,
        "intended_emotion": EMOTIONS,
        "intensity": ("LO", "MD", "HI", "XX"),
    }
    for condition in CONDITIONS[:-1]:
        responses = conditions[condition]
        for reference in REFERENCES:
            for scope, level, wanted in [
                ("sample", "all", sample_ids),
                ("sample", "untied", untied),
                *(
                    (
                        name,
                        value,
                        [
                            sample
                            for sample in sample_ids
                            if clips[sample][name] == value
                        ],
                    )
                    for name, values in levels.items()
                    for value in values
                    if name != "stratum" or condition == "P1-R1"
                ),
            ]:
                valid = [
                    sample
                    for sample in wanted
                    if responses[sample]["label"] is not None
                ]
                labels = [responses[sample]["label"] for sample in valid]
                row = _accuracy_row(
                    parser,
                    model,
                    condition,
                    scope,
                    level,
                    reference,
                    wanted,
                    valid,
                    clips,
                    labels,
                )
                tables["accuracies"].append(row)
                if parser == "amended" and scope == "stratum":
                    tables["figure2"].append(
                        {
                            "model": model,
                            "reference": reference,
                            "stratum": level,
                            "estimate": row["accuracy"],
                            "n_valid": row["n_valid"],
                            "n_planned": row["n_planned"],
                            "neutral_estimate": row["always_neutral"],
                            "majority_estimate": row["majority"],
                        }
                    )
                if scope == "sample" and (reference == "intended" or level == "untied"):
                    metrics = classification_metrics(
                        labels,
                        [_reference(clips[sample], reference) for sample in valid],
                    )
                    tables["classification"].append(
                        {
                            "parser": parser,
                            "model": model,
                            "condition": condition,
                            "sample": level,
                            "reference": reference,
                            "n_valid": len(valid),
                            "macro_f1": metrics["macro_f1"],
                            "mcc": metrics["mcc"],
                        }
                    )
                    for observed, counts in zip(
                        EMOTIONS, metrics["confusion"], strict=True
                    ):
                        tables["confusion_matrices"].append(
                            {
                                "parser": parser,
                                "model": model,
                                "condition": condition,
                                "sample": level,
                                "reference": reference,
                                "reference_label": observed,
                                **dict(zip(EMOTIONS, counts, strict=True)),
                            }
                        )


def _primary(parser, model, responses, clips, human, tables):
    valid = [sample for sample in clips if responses[sample]["label"] is not None]
    actors = [clips[sample]["actor"] for sample in valid]
    columns = {
        **{
            ref: [responses[sample][f"{ref}_match"] for sample in valid]
            for ref in REFERENCES
        },
        **{
            f"human_{ref}": [human[sample][f"listener_{ref}"] for sample in valid]
            for ref in REFERENCES
        },
    }
    intervals = actor_bootstrap(
        actors, columns, differences={"gap": ("perceived", "intended")}
    )
    for reference in REFERENCES:
        baseline = baseline_accuracies(
            [_reference(clips[sample], reference) for sample in valid]
        )
        interval, listeners = (
            intervals[key] for key in (reference, f"human_{reference}")
        )
        row = {
            "parser": parser,
            "model": model,
            "reference": reference,
            "n_valid": len(valid),
            "n_actors": len(set(actors)),
            "estimate": interval["estimate"],
            "ci_low": interval["lower"],
            "ci_high": interval["upper"],
            "human_estimate": listeners["estimate"],
            "human_ci_low": listeners["lower"],
            "human_ci_high": listeners["upper"],
            "neutral_estimate": baseline["always_neutral"],
            "majority_estimate": baseline["majority"],
            "majority_label": baseline["majority_label"],
        }
        tables["primary_accuracy"].append(row)
        if parser == "amended":
            tables["figure1"].append(row)
    tables["reference_gaps"].append(
        {
            "parser": parser,
            "model": model,
            "n_valid": len(valid),
            "n_actors": len(set(actors)),
            **intervals["gap"],
        }
    )
    tables["confidence_agreement"].append(
        {
            "parser": parser,
            "model": model,
            "n_valid": len(valid),
            "n_planned": len(clips),
            "spearman": spearman(
                [responses[sample]["confidence"] for sample in valid],
                [float(clips[sample]["voice_agreement"]) for sample in valid],
            ),
        }
    )


def _non_neutral_plurality(parser, model, responses, clips):
    """Compare both references in the exploratory subset defined by listener votes."""
    eligible = [
        sample
        for sample, clip in clips.items()
        if "Neutral" not in clip["voice_majority"].split(":")
    ]
    valid = [sample for sample in eligible if responses[sample]["label"] is not None]
    actors = [clips[sample]["actor"] for sample in valid]
    columns = {
        reference: [responses[sample][f"{reference}_match"] for sample in valid]
        for reference in REFERENCES
    }
    intervals = actor_bootstrap(actors, columns)
    return [
        {
            "parser": parser,
            "model": model,
            "condition": "P1-R1",
            "reference": reference,
            "n_eligible": len(eligible),
            "n_valid": len(valid),
            "n_actors": len(set(actors)),
            **intervals[reference],
            **baseline_accuracies(
                _reference(clips[sample], reference) for sample in valid
            ),
        }
        for reference in REFERENCES
    ]


def _coverage_and_labels(parser, model, conditions, tables):
    for condition, responses in conditions.items():
        values = list(responses.values())
        counts = Counter(row["status"] for row in values)
        base = {"parser": parser, "model": model, "condition": condition}
        tables["coverage"].append(
            {
                **base,
                "n_planned": len(values),
                "n_valid": counts["valid"],
                **{kind: counts[kind] for kind in UNKNOWN},
            }
        )
        key = "probability_argmax" if condition == "P3" else "label"
        labels = Counter(row[key] for row in values if row["status"] == "valid")
        for label in [*EMOTIONS, *sorted(labels.keys() - set(EMOTIONS)), "Unknown"]:
            tables["predicted_labels"].append(
                {
                    **base,
                    "label": label,
                    "count": len(values) - counts["valid"]
                    if label == "Unknown"
                    else labels[label],
                }
            )
        if condition == "P3":
            valid = [row for row in values if row["status"] == "valid"]
            fields = [
                "jensen_shannon",
                "brier",
                *(f"p_{label.lower()}" for label in EMOTIONS),
            ]
            tables["distribution_forecasts"].append(
                {
                    **base,
                    "n_valid": len(valid),
                    "n_planned": len(values),
                    **{
                        f"mean_{field}": fmean(row[field] for row in valid)
                        if valid
                        else None
                        for field in fields
                    },
                }
            )


def _stability(parser, model, conditions, clips, tables):
    p1 = tuple(CONDITIONS[:3])
    complete = [
        sample
        for sample in clips
        if all(conditions[name][sample]["label"] is not None for name in p1)
    ]
    ratings = [
        [conditions[name][sample]["label"] for name in p1] for sample in complete
    ]
    flip = flip_rate(ratings)
    kappa = fleiss_kappa(ratings)
    paired = [
        sample
        for sample in clips
        if all(
            conditions[name][sample]["label"] is not None for name in ("P1-R1", "P2")
        )
    ]
    for reference in REFERENCES:
        repeat_rows = []
        for name in p1:
            labels = [conditions[name][sample]["label"] for sample in complete]
            row = _accuracy_row(
                parser,
                model,
                name,
                "repeat",
                "three valid P1 labels",
                reference,
                list(clips),
                complete,
                clips,
                labels,
            )
            tables["accuracies"].append(row)
            repeat_rows.append(row)
        estimates = [row["accuracy"] for row in repeat_rows]
        repeat = {
            "parser": parser,
            "model": model,
            "reference": reference,
            "n_complete": len(complete),
            "n_planned": len(clips),
            "flip_rate": flip,
            "fleiss_kappa": kappa,
            **dict(zip((f"{name}_accuracy" for name in p1), estimates, strict=True)),
            "accuracy_range": score_range(estimates),
            **{
                name: repeat_rows[0][name]
                for name in ("always_neutral", "majority", "majority_label")
            },
        }
        tables["repeat_stability"].append(repeat)
        if parser == "amended":
            tables["figure3"].append(repeat)

        pairs = []
        for name in ("P1-R1", "P2"):
            labels = [conditions[name][sample]["label"] for sample in paired]
            row = _accuracy_row(
                parser,
                model,
                name,
                "prompt_pair",
                "both prompts valid",
                reference,
                list(clips),
                paired,
                clips,
                labels,
            )
            tables["accuracies"].append(row)
            pairs.append((labels, row))
        (earlier, first), (later, second) = pairs
        tables["prompt_stability"].append(
            {
                "parser": parser,
                "model": model,
                "reference": reference,
                "n_paired": len(paired),
                "n_planned": len(clips),
                "label_change_rate": label_change_rate(earlier, later),
                "p1_accuracy": first["accuracy"],
                "p2_accuracy": second["accuracy"],
                "p2_minus_p1": second["accuracy"] - first["accuracy"]
                if paired
                else None,
                **{
                    name: first[name]
                    for name in ("always_neutral", "majority", "majority_label")
                },
            }
        )
    for sample in clips:
        labels = [conditions[name][sample]["label"] for name in p1]
        p2 = conditions["P2"][sample]["label"]
        tables["per_clip_stability"].append(
            {
                "parser": parser,
                "model": model,
                "sample_id": sample,
                **dict(zip(p1, labels, strict=True)),
                "P2": p2,
                "p1_any_flip": int(len(set(labels)) > 1) if all(labels) else None,
                "p1_r1_to_p2_flip": int(labels[0] != p2) if labels[0] and p2 else None,
            }
        )


def _format_checks(saved, indexed, tables, output):
    carbon = MODELS[2]
    groups = {}
    prose = []
    for (model, condition, sample), row in saved.items():
        text = row.get("completion") or ""
        result = indexed["amended", model, condition, sample]
        if model == carbon:
            group = "fenced" if unwrap_markdown_fence(text) != text else "unfenced"
            label = result["label"] or result["probability_argmax"] or "Unknown"
            groups.setdefault((condition, group), Counter())[label] += 1
        if (
            model == MODELS[0]
            and condition == "P3"
            and result["status"] == "parse_error"
            and text.lstrip()[:1].isalpha()
        ):
            prose.append((sample, text))
    table_lines = [
        "| Condition | Format | Anger | Disgust | Fear | Happy | Neutral | Sad | Tied argmax | Unknown | Total |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: |",
    ]
    for condition in CONDITIONS:
        for group in ("fenced", "unfenced"):
            counts = groups.get((condition, group), Counter())
            ties = sorted(counts.keys() - {*EMOTIONS, "Unknown"})
            tie_text = ", ".join(f"{label} ({counts[label]})" for label in ties) or "—"
            values = [
                condition,
                group,
                *(counts[label] for label in EMOTIONS),
                tie_text,
                counts["Unknown"],
                counts.total(),
            ]
            table_lines.append("| " + " | ".join(map(str, values)) + " |")
            for label in [*EMOTIONS, *ties, "Unknown"]:
                tables["carbon_fence_counts"].append(
                    {
                        "condition": condition,
                        "format": group,
                        "label": label,
                        "count": counts[label],
                        "total": counts.total(),
                    }
                )

    prose_examples = dict(prose)
    lines = [
        "# Exploratory output-format checks",
        "",
        "## Carbon label counts by fence status",
        "",
        "These counts use amended outputs. P3 uses the largest predicted share and keeps ties explicit. The groups have different sizes.",
        "",
        *table_lines,
        "",
        "## OpenAI P3 prose responses",
        "",
        f"OpenAI P3 returned {len(prose)} of 300 responses that began with prose and failed the JSON schema. The two completions below are reproduced verbatim.",
        "",
    ]
    for sample in ("clip124", "clip210"):
        if sample in prose_examples:
            lines.extend(
                [f"### {sample}", "", "```text", prose_examples[sample], "```", ""]
            )
    (output / "FORMAT_CHECKS.md").write_text(
        "\n".join(lines), encoding="utf-8", newline="\n"
    )


def analyze(root: Path, output: Path) -> None:
    path = root / "data/manifest.csv"
    manifest_hash = _digest(path)
    if manifest_hash != ORIGINAL_MANIFEST:
        raise ValueError("The manifest differs from the approved source")
    with path.open(encoding="utf-8", newline="") as stream:
        clips = {row["sample_id"]: row for row in csv.DictReader(stream)}
    if len(clips) != 300:
        raise ValueError("Expected exactly 300 frozen clips")
    main = root / "results/private/main"
    original, orig = _read_main(main, MODELS[:2], clips, manifest_hash)
    third, carbon = _read_main(main / "third-model", MODELS[2:], clips, manifest_hash)
    if carbon.prompts != orig.prompts or carbon.stimuli != orig.stimuli:
        raise ValueError("The main runs use different prompts or stimuli")
    for prompt in orig.prompts.values():
        if _digest(root / "prompts" / prompt["file"]) != prompt["sha256"]:
            raise ValueError("A prompt differs from the recorded hash")
    saved = original | third
    human = listener_baselines(list(clips.values()), root / "data/local/metadata")
    output.mkdir(parents=True, exist_ok=True)
    tables = {
        name: []
        for name in (
            "accuracies",
            "classification",
            "confusion_matrices",
            "primary_accuracy",
            "reference_gaps",
            "confidence_agreement",
            "distribution_forecasts",
            "coverage",
            "predicted_labels",
            "repeat_stability",
            "prompt_stability",
            "per_clip_predictions",
            "per_clip_stability",
            "carbon_fence_counts",
            "figure1",
            "figure2",
            "figure3",
            "sample_counts",
            "per_clip_listeners",
            "exploratory_non_neutral_plurality",
        )
    }
    indexed = _responses(saved, clips, tables)
    for field in ("stratum", "actor", "sentence", "intended_emotion", "intensity"):
        counts = Counter(clip[field] for clip in clips.values())
        tables["sample_counts"].extend(
            {"field": field, "level": level, "n": count}
            for level, count in sorted(counts.items())
        )
    for sample, clip in clips.items():
        tables["per_clip_listeners"].append(
            {
                "sample_id": sample,
                "actor": clip["actor"],
                "sentence": clip["sentence"],
                "intended_emotion": clip["intended_emotion"],
                "intensity": clip["intensity"],
                "stratum": clip["stratum"],
                "voice_majority": clip["voice_majority"],
                "voice_agreement": clip["voice_agreement"],
                "voice_tie": clip["voice_tie"],
                **human[sample],
            }
        )
    for parser in PARSERS:
        for model in MODELS:
            by_condition = {
                condition: {
                    sample: indexed[parser, model, condition, sample]
                    for sample in clips
                }
                for condition in CONDITIONS
            }
            _descriptive_accuracy(parser, model, by_condition, clips, tables)
            _primary(parser, model, by_condition["P1-R1"], clips, human, tables)
            tables["exploratory_non_neutral_plurality"].extend(
                _non_neutral_plurality(parser, model, by_condition["P1-R1"], clips)
            )
            _coverage_and_labels(parser, model, by_condition, tables)
            _stability(parser, model, by_condition, clips, tables)
    _format_checks(saved, indexed, tables, output)
    for name, rows in tables.items():
        _write_csv(output / f"{name}.csv", rows)

    provenance = {
        "manifest_sha256": manifest_hash,
        "prompt_files": orig.prompts,
        "models": list(MODELS),
        "served_models": {
            model: sorted(
                {
                    r["served_model"]
                    for r in saved.values()
                    if r["model"] == model and r["served_model"]
                }
            )
            for model in MODELS
        },
        "main_run_utc_dates": sorted({r["started_at"][:10] for r in saved.values()}),
        "raw_transcript_sha256": {
            run.run_id: _digest(run.path / "transcripts.jsonl")
            for run in (orig, carbon)
        },
        "bootstrap": {"replicates": 2000, "seed": 20261112, "cluster": "actor"},
    }
    (output / "provenance.json").write_text(
        json.dumps(provenance, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"Wrote {len(tables)} tables for {len(saved)} main-run cells to {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=Path("results/analysis"))
    args = parser.parse_args()
    analyze(args.root, args.output)


if __name__ == "__main__":
    main()
