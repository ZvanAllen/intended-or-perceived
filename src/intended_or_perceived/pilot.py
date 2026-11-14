"""Run the authorized 24-clip pilot and summarize its coverage and cost."""

import argparse
import csv
import hashlib
import json
import logging
import os
import re
from collections import Counter
from pathlib import Path

from dotenv import dotenv_values

from intended_or_perceived.budget import BudgetLedger, BudgetStop
from intended_or_perceived.evaluation import (
    CONDITIONS,
    MODEL_IDS,
    PilotStopped,
    run_pilot,
)
from intended_or_perceived.scoring import EMOTIONS, parse_output

NANO_PER_DOLLAR = 1_000_000_000
PILOT_CALLS_PER_MODEL = 120
MAIN_CALLS_PER_MODEL = 1500
_JSON_FENCE = re.compile(r"```(?:json)?[^\S\n]*\n(.*?)\n```", re.IGNORECASE | re.DOTALL)


def load_project_keys(dotenv_path: Path) -> None:
    dotenv = dotenv_values(dotenv_path, interpolate=False) if dotenv_path.is_file() else {}
    variables = ("OPENAI_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY")
    for name in variables:
        value = (os.environ.get(name) or dotenv.get(name) or "").strip()
        if value:
            os.environ[name] = value
    if not os.environ.get("OPENAI_API_KEY") or not any(
        os.environ.get(name) for name in variables[1:]
    ):
        raise SystemExit("Pilot needs OPENAI_API_KEY and GOOGLE_API_KEY or GEMINI_API_KEY.")


def _cost(records: list[dict]) -> tuple[float, float]:
    charges = sum(row["charged_nanodollars"] or 0 for row in records)
    holds = sum(
        row["reserved_nanodollars"]
        for row in records
        if row["charged_nanodollars"] is None
    )
    return charges / NANO_PER_DOLLAR, holds / NANO_PER_DOLLAR


def write_report(
    rows: list[dict], ledger: BudgetLedger, report_path: Path, manifest_path: Path,
) -> str:
    records = ledger.records()
    lines = [
        "# Gate 1 pilot report",
        "",
        "The planned pilot has 24 clips and five conditions per model. Coverage",
        "uses all planned calls as the denominator. Unknown outputs include schema",
        "failures, out-of-set labels, refusals, incomplete output and request errors.",
        "",
        "| Model | Condition | Valid / planned | Parse errors | Other unknown | Missing |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for model in MODEL_IDS:
        for condition in CONDITIONS:
            status = Counter(
                row["status"]
                for row in rows
                if row["model"] == model and row["condition"] == condition
            )
            observed = sum(status.values())
            other = observed - status["valid"] - status["parse_error"]
            lines.append(
                f"| `{model}` | {condition} | {status['valid']}/24 | "
                f"{status['parse_error']} | {other} | {24 - observed} |"
            )

    lines += ["", "| Model | Coverage | Parse-failure rate |", "| --- | ---: | ---: |"]
    for model in MODEL_IDS:
        outputs = Counter(row["status"] for row in rows if row["model"] == model)
        responses = sum(outputs.values()) - outputs["request_error"]
        rate = f"{outputs['parse_error'] / responses:.1%}" if responses else "Unavailable"
        lines.append(
            f"| `{model}` | {outputs['valid']}/{PILOT_CALLS_PER_MODEL} "
            f"({outputs['valid'] / PILOT_CALLS_PER_MODEL:.1%}) | {rate} |"
        )
    lines += ["", "Parse-failure rates use received responses as the denominator."]
    lines += [
        "", "## Forced-choice predicted labels", "",
        "| Model | Condition | Anger | Disgust | Fear | Happy | Neutral | Sad | Unknown |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    neutral_counts = []
    for model in MODEL_IDS:
        for condition in CONDITIONS[:-1]:
            counts = Counter(
                row.get("label") for row in rows
                if row["model"] == model and row["condition"] == condition
            )
            neutral_counts.append(counts["Neutral"])
            values = " | ".join(str(counts[label]) for label in (*EMOTIONS, None))
            lines.append(f"| `{model}` | {condition} | {values} |")
    if len(rows) == 2 * PILOT_CALLS_PER_MODEL:
        lines += [
            "",
            f"Neutral accounted for {min(neutral_counts)} to {max(neutral_counts)} of 24 scheduled clips in every forced-choice run.",
        ]
    outcomes = Counter(row["status"] for row in rows)
    if len(rows) != 2 * PILOT_CALLS_PER_MODEL or outcomes["request_error"]:
        lines += [
            "",
            f"Pilot outcomes recorded for {len(rows)}/{2 * PILOT_CALLS_PER_MODEL} cells.",
        ]

    gemini_distribution_errors = [
        row for row in rows
        if row["model"] == MODEL_IDS[1] and row["condition"] == "P3"
        and row["status"] == "parse_error"
    ]
    if gemini_distribution_errors:
        fenced = [
            match.group(1) for row in gemini_distribution_errors
            if (match := _JSON_FENCE.fullmatch(row["completion"].strip()))
        ]
        valid_without_fence = sum(parse_output(text, "P3").status == "valid" for text in fenced)
        lines += [
            "", "## Distribution prompt diagnosis", "",
            (
                f"Gemini produced {len(gemini_distribution_errors)} P3 parse errors. "
                f"{len(fenced)} of those completions used Markdown fences. "
                f"{valid_without_fence} would meet the schema after unwrapping."
            ),
            (
                "The original strict scoring stands. The main-run prompt `P3-v2.txt` clarifies "
                "raw JSON formatting and asks for an explicit sum check. Live validation of the revision is pending."
            ),
        ]

    lines += [
        "", "## API cost in USD", "",
        "| Model | HTTP generation attempts | Metered cost | Unresolved holds | Mean per received response |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    full_projection = 0.0
    all_conditions_observed = True
    for model in MODEL_IDS:
        attempts = [row for row in records if row["model"] == model]
        model_rows = [row for row in rows if row["model"] == model]
        received = [row for row in model_rows if row["status"] != "request_error"]
        all_conditions_observed &= len(model_rows) == PILOT_CALLS_PER_MODEL and {
            row["condition"] for row in received
        } == set(CONDITIONS)
        cost, holds = _cost(attempts)
        mean_text = "Unavailable"
        if received:
            mean = cost / len(received)
            full_projection += mean * MAIN_CALLS_PER_MODEL
            mean_text = f"${mean:.6f}"
        lines.append(f"| `{model}` | {len(attempts)} | ${cost:.4f} | ${holds:.4f} | {mean_text} |")

    charged, held = _cost(records)
    lines += ["", f"Metered so far **${charged:.4f}**. Unresolved holds **${held:.4f}**."]
    missing_split = sum(row.get("cost_basis") == "upper_bound_missing_audio_split" for row in records)
    if missing_split:
        lines += [
            (
                f"{missing_split} OpenAI requests lacked an audio token split. Their input cost "
                "uses the higher audio rate as an upper bound."
            ),
        ]
    if any(row.get("cost_basis") == "upper_bound_openai_cache" for row in records):
        lines += ["Metering used the regular input rate for OpenAI cached tokens."]
    if all_conditions_observed:
        total = charged + full_projection
        lines += [
            f"Projected fresh main run **${full_projection:.2f}**.",
            f"Projected project total with pilot **${total:.2f}** against the US$25 cap.",
            "The projection applies each provider’s metered mean per received response to 1,500 fresh calls.",
        ]
        if held:
            lines += [
                f"Budget planning total with existing unresolved holds **${total + held:.2f}**.",
                "The ledger retains those holds for cap enforcement. Future connection failures or retries can add cost.",
            ]
        if total + held > 25:
            lines += ["The projection exceeds the cap. Main-run dispatch is blocked."]
    else:
        lines += ["A full-run projection requires recorded outcomes and received responses across both models and all five conditions."]

    with manifest_path.open(encoding="utf-8", newline="") as stream:
        pilot_clips = [row for row in csv.DictReader(stream) if row["pilot"] == "1"]
    durations = [float(row["duration_seconds"]) for row in pilot_clips]
    lines += ["", "## Stimuli", ""]
    if durations:
        lines += [
            (
                f"The manifest marks {len(durations)} pilot MP3s, with durations ranging from "
                f"{min(durations):.2f} to {max(durations):.2f} seconds."
            ),
            "The four upstream-flagged defective MP3s were outside the eligible pool.",
            "One additional silent recording was replaced before freeze, outside the pilot subset.",
        ]
    statuses = Counter(row["status"] for row in rows)
    lines += [
        f"Request errors recorded in transcripts: {statuses['request_error']}.",
        "See the model and condition table for received output status.",
        f"Manifest SHA-256 `{hashlib.sha256(manifest_path.read_bytes()).hexdigest()}`.",
    ]
    unknown_counts = {name: count for name, count in sorted(statuses.items()) if name != "valid"}
    if unknown_counts:
        lines += [
            "", "Recorded unknowns", "",
            *[f"- {name.replace('_', ' ').title()} — {count}" for name, count in unknown_counts.items()],
        ]
    dates = sorted({row["started_at"][:10] for row in rows if row.get("started_at")})
    if dates:
        lines += ["", "UTC run date(s) " + ", ".join(dates) + "."]
    versions = sorted({row["served_model"] for row in rows if row.get("served_model")})
    if versions:
        lines += ["", "Served model IDs " + ", ".join(f"`{name}`" for name in versions) + "."]
    lines += ["", "Main-run dispatch requires a separate approval."]
    report = "\n".join(lines) + "\n"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Send the frozen pilot to both APIs")
    parser.add_argument("--report-only", action="store_true", help="Summarize saved pilot files")
    args = parser.parse_args()
    if args.live == args.report_only:
        parser.error("Choose --live or --report-only")

    root = Path.cwd()
    private = root / "results/private"
    run_dir = private / "pilot"
    ledger_path = private / "project_budget.sqlite3"
    manifest_path = root / "data/manifest.csv"
    transcript = run_dir / "transcripts.jsonl"
    report_path = root / "results/PILOT_REPORT.md"
    if args.report_only:
        if not ledger_path.is_file() or not transcript.is_file():
            parser.error("The saved pilot ledger and transcript are required")
        rows = [json.loads(line) for line in transcript.read_text(encoding="utf-8").splitlines()]
        write_report(rows, BudgetLedger(ledger_path), report_path, manifest_path)
        return

    load_project_keys(root / ".env")
    for name in ("httpx", "httpcore", "openai", "google_genai", "google.genai"):
        logging.getLogger(name).setLevel(logging.CRITICAL)

    ledger = BudgetLedger(ledger_path)
    try:
        run_pilot(
            manifest_path=manifest_path,
            stimuli_dir=root / "data/local/stimuli",
            prompts_dir=root / "prompts",
            run_dir=run_dir,
            ledger=ledger,
        )
    except (PilotStopped, BudgetStop) as error:
        raise SystemExit(str(error)) from None
    finally:
        if transcript.is_file():
            rows = [json.loads(line) for line in transcript.read_text(encoding="utf-8").splitlines()]
            write_report(rows, ledger, report_path, manifest_path)


if __name__ == "__main__":
    main()
