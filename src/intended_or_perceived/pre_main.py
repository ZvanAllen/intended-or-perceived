"""Run authorized diagnostics or simulate the full main evaluation locally."""

import argparse
import csv
import json
import logging
from collections import Counter
from html import escape
from pathlib import Path

from intended_or_perceived.audio_diagnostic import normalized_words
from intended_or_perceived.budget import BudgetLedger, BudgetStop
from intended_or_perceived.pilot import (
    _JSON_FENCE,
    NANO_PER_DOLLAR,
    _cost,
    load_project_keys,
)
from intended_or_perceived.scoring import EMOTIONS, parse_output

_RUN_IDS = ("diagnostic-d1", "diagnostic-gain", "diagnostic-p3-v2")


def _records(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _csv_rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def _markdown_cell(text: str | None) -> str:
    if text is None:
        return "Unknown"
    return (
        escape(text, quote=False)
        .replace("|", r"\|")
        .replace("\r\n", "\n")
        .replace("\n", "<br>")
    )


def _label_table(rows: list[dict], models: tuple[str, ...]) -> list[str]:
    lines = [
        "| Model | Anger | Disgust | Fear | Happy | Neutral | Sad | Unknown |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for model in models:
        counts = Counter(row.get("label") for row in rows if row["model"] == model)
        values = [str(counts[label]) for label in (*EMOTIONS, None)]
        lines.append(f"| `{model}` | " + " | ".join(values) + " |")
    return lines


def write_audio_report(
    path: Path,
    levels: dict,
    gains: list[dict],
    pilot: list[dict],
    transcriptions: list[dict],
    adjusted: list[dict],
    models: tuple[str, ...],
) -> None:
    original = [row for row in pilot if row["condition"] == "P1-R1"]
    expected = {row["sample_id"]: row["expected_words"] for row in gains}
    observed = {(row["model"], row["sample_id"]): row for row in transcriptions}
    exact = Counter()
    mismatches = []
    for model in models:
        for sample_id, words in expected.items():
            result = observed.get((model, sample_id), {})
            heard = (
                result.get("completion") if result.get("status") == "valid" else None
            )
            if heard is not None and normalized_words(heard) == normalized_words(words):
                exact[model] += 1
            else:
                mismatches.append(
                    f"| `{model}` | {sample_id} | {_markdown_cell(words)} | {_markdown_cell(heard)} |"
                )

    labels = {
        (name, row["model"], row["sample_id"]): row.get("label")
        for name, rows in (("original", original), ("adjusted", adjusted))
        for row in rows
    }
    lines = [
        "# Audio diagnostic",
        "",
        "## Original-level transcription",
        "",
        "Exact match lowercases and strips punctuation and collapses consecutive whitespace. Each denominator is the 24 scheduled clips.",
        "The reference is the scripted CREMA-D sentence. A difference can reflect the actor’s wording or a transcription error. Exact matches show that the words were recoverable in this condition.",
        "",
        "| Model | Exact match |",
        "| --- | ---: |",
        *[
            f"| `{model}` | {exact[model]}/{len(gains)} ({exact[model] / len(gains):.1%}) |"
            for model in models
        ],
    ]
    if mismatches:
        lines += [
            "",
            "### Mismatches",
            "",
            "| Model | Clip | Expected | Returned |",
            "| --- | --- | --- | --- |",
            *mismatches,
        ]
    lines += [
        "",
        "## Original-level predicted labels (pilot P1-R1)",
        "",
        *_label_table(original, models),
        "",
        "## Peak-adjusted predicted labels (diagnostic P1)",
        "",
        *_label_table(adjusted, models),
        "",
        "## Audio levels",
        "",
        "The diagnostic used one linear gain per clip to target −1 dBFS peak, followed by conversion to 16-bit mono WAV at the native sample rate. Per-clip gain removes the between-clip loudness differences present during the listener task. The loudest clip in the 300 is already near full scale, leaving essentially no room for a single positive gain across the set before clipping.",
        "The adjusted clips were sent as WAV, and the original-level runs used MP3. This comparison changes level and input format and uses one generation per clip and model at each level.",
        "",
        "Original-level full-set measurements are in the table below.",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        *[
            f"| {name.replace('_', ' ')} | {value} |"
            for name, value in levels.items()
            if isinstance(value, (float, int))
        ],
        "",
        "| Clip | Original RMS dBFS | Original peak dBFS | Gain dB | OpenAI original | OpenAI adjusted | Gemini original | Gemini adjusted |",
        "| --- | ---: | ---: | ---: | --- | --- | --- | --- |",
    ]
    for gain in gains:
        sample_id = gain["sample_id"]
        values = [
            sample_id,
            *[
                f"{float(gain[name]):.2f}"
                for name in ("source_rms_dbfs", "source_peak_dbfs", "applied_gain_db")
            ],
            *[
                labels.get((version, model, sample_id)) or "Unknown"
                for model in models
                for version in ("original", "adjusted")
            ],
        ]
        lines.append("| " + " | ".join(values) + " |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def write_pre_main_report(
    path: Path, revised: list[dict], ledger: BudgetLedger, models: tuple[str, ...]
) -> dict[str, int]:
    strict = Counter()
    recovered = Counter()
    for row in revised:
        model = row["model"]
        if row["status"] == "valid":
            strict[model] += 1
        elif (text := row.get("completion")) and (
            match := _JSON_FENCE.fullmatch(text.strip())
        ):
            recovered[model] += (
                parse_output(
                    match.group(1), "P3", stop_reason=row.get("stop_reason")
                ).status
                == "valid"
            )
    records = ledger.records()
    total_charge, total_holds = _cost(records)
    diagnostic_charge, diagnostic_holds = _cost(
        [record for record in records if record.get("run_id") in _RUN_IDS]
    )
    request_errors = sum(row["status"] == "request_error" for row in revised)
    lines = [
        "# Pre-main evaluation checks",
        "",
        "## P3-v2 validation",
        "",
        "| Model | Strict valid | Fenced failures that pass after unwrapping |",
        "| --- | ---: | ---: |",
        *[
            f"| `{model}` | {strict[model]}/24 | {recovered[model]} |"
            for model in models
        ],
        "",
        "The strict parser was applied to both models. The unwrapping column is an offline check of failed responses.",
        f"Request errors before a completion: {request_errors}.",
        "",
        "## Metering and projection",
        "",
        f"Additional diagnostics and prompt validation metered **US${diagnostic_charge:.4f}**, with **US${diagnostic_holds:.4f}** in unresolved diagnostic reservations, against their shared US$0.50 ceiling.",
        f"Cumulative project spend is **US${total_charge:.4f}** with **US${total_holds:.4f}** held. Current uncommitted headroom is **US${25 - total_charge - total_holds:.2f}**.",
    ]
    _add_projection(lines, records, total_charge + total_holds, models)
    if len(revised) < 24 * len(models):
        lines += [
            "",
            f"Validation outcomes recorded so far for {len(revised)} of {24 * len(models)} cells.",
        ]
    elif any(strict[model] < 23 for model in models):
        lines += [
            "",
            "Strict coverage fell below 23/24 for at least one model. The prompt was kept fixed and the parser fallback is pending Zack’s decision.",
        ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return dict(strict)


def _add_projection(
    lines: list[str], records: list[dict], committed: float, models: tuple[str, ...]
) -> None:
    occupied = set()
    projected = 0.0
    for model in models:
        for condition in ("P1-R1", "P1-R2", "P1-R3", "P2", "P3"):
            run_id = "diagnostic-p3-v2" if condition == "P3" else "pilot"
            values = [
                row["charged_nanodollars"]
                for row in records
                if row["model"] == model
                and row["condition"] == condition
                and (row.get("run_id") or "pilot") == run_id
                and row["http_status"] == 200
                and row["charged_nanodollars"] is not None
            ]
            if values:
                occupied.add((model, condition))
                projected += 300 * sum(values) / (len(values) * NANO_PER_DOLLAR)
    if len(occupied) == 5 * len(models):
        lines += [
            f"The projected fresh 3,000-call audio run is **US${projected:.2f}**, leaving **US${25 - committed - projected:.2f}** after current charges and holds.",
            "This estimate uses observed mean HTTP 200 costs from the original-level forced-choice pilot and the P3-v2 rerun. Retries and gain-adjusted stimulus costs can change the estimate.",
        ]


def main() -> None:
    from intended_or_perceived.evaluation import (
        MODEL_IDS,
        STUDY_CONDITIONS,
        Condition,
        PilotStopped,
        PreparedStimulus,
        mock_model_factory,
        run_evaluation,
    )

    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument(
        "--diagnostics", action="store_true", help="Run authorized A/B calls"
    )
    action.add_argument(
        "--dry-run", action="store_true", help="Simulate the complete main run"
    )
    action.add_argument(
        "--report-only", action="store_true", help="Summarize saved A/B calls"
    )
    args = parser.parse_args()
    root = Path.cwd()
    manifest = root / "data/manifest.csv"
    private = root / "results/private"
    common = {
        "manifest_path": manifest,
        "stimuli_dir": root / "data/local/stimuli",
        "prompts_dir": root / "prompts",
    }
    if args.dry_run:
        rows = run_evaluation(
            **common,
            run_dir=private / "main-dry-run",
            run_id="main-dry-run",
            subset="main",
            authorization="offline mock only",
            model_factory=mock_model_factory,
        )
        print(
            f"Dry run recorded {len(rows)} cells with a local mock model.", flush=True
        )
        return

    if args.diagnostics:
        load_project_keys(root / ".env")
        for name in ("httpx", "httpcore", "openai", "google_genai", "google.genai"):
            logging.getLogger(name).setLevel(logging.CRITICAL)
    ledger = BudgetLedger(private / "project_budget.sqlite3")
    diagnostic_dir = root / "data/local/diagnostic"
    gains = _csv_rows(diagnostic_dir / "manifest.csv")
    levels = json.loads((diagnostic_dir / "levels.json").read_text(encoding="utf-8"))
    overrides = {
        row["sample_id"]: PreparedStimulus(
            path=root / row["media_path"], sha256=row["media_sha256"]
        )
        for row in gains
    }
    specifications = (
        (_RUN_IDS[0], Condition("D1", "D1", "diagnostic/D1-transcribe.txt"), None),
        (_RUN_IDS[1], Condition("P1", "P1", "P1.txt"), overrides),
        (_RUN_IDS[2], STUDY_CONDITIONS[-1], None),
    )
    if args.diagnostics:
        recorded = ledger.records()
        if not any(row["run_id"] == "pilot" for row in recorded):
            raise SystemExit(
                "The original project ledger is required for diagnostic dispatch."
            )
    try:
        if args.diagnostics:
            for run_id, condition, stimuli in specifications:
                run_evaluation(
                    **common,
                    run_dir=private / run_id,
                    run_id=run_id,
                    subset="pilot",
                    conditions=(condition,),
                    ledger=ledger,
                    stimuli=stimuli,
                    authorization="November 14 Gate 1 review tasks A and B, combined US$0.50",
                )
    except (BudgetStop, PilotStopped) as error:
        raise SystemExit(str(error)) from None
    finally:
        original = _records(private / "pilot/transcripts.jsonl")
        transcription, adjusted, revised = [
            _records(private / run_id / "transcripts.jsonl") for run_id in _RUN_IDS
        ]
        write_audio_report(
            root / "results/AUDIO_DIAGNOSTIC.md",
            levels,
            gains,
            original,
            transcription,
            adjusted,
            MODEL_IDS,
        )
        write_pre_main_report(
            root / "results/PRE_MAIN_REPORT.md", revised, ledger, MODEL_IDS
        )


if __name__ == "__main__":
    main()
