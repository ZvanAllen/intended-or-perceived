"""Launch or report the prespecified higher-tier Gemini arm."""

import argparse
import hashlib
import json
import logging
import statistics
import subprocess
from collections import Counter
from pathlib import Path

from intended_or_perceived.budget import (
    GEMINI_CARBON,
    THIRD_GEMINI_MODELS,
    BudgetLedger,
    BudgetStop,
    model_output_limit,
)
from intended_or_perceived.evaluation import (
    CONDITIONS,
    PilotStopped,
    ThirdModelUnavailable,
    run_evaluation,
)
from intended_or_perceived.pilot import load_project_keys
from intended_or_perceived.scoring import EMOTIONS

NANO_PER_USD = 1_000_000_000
VALID_PER_CONDITION = 23
PILOT_PER_CONDITION = 24
MAIN_PER_CONDITION = 300
THIRD_NANO_CAP = 10 * NANO_PER_USD
PROJECT_NANO_CAP = 25 * NANO_PER_USD
ORIGINAL_MANIFEST = "0742e730a95a51cefc97b942358a078e5712cb2415a406e7bf733e6ffe5d741e"
FROZEN_PROMPTS = {
    "P1.txt": "87aa3b697b275ae5b28e0bbd7a241fd2ab714eb1788fede6f90e63997ab79e47",
    "P2.txt": "3a7c90e00813f6c77f70a3842683d9625f9f0cb5686d546b29902998f97cfd3f",
    "P3-v2.txt": "1ef36e9cbef7106066a95698758f33c2e1fd6ed84e8dd3dfa7b7cb515dc8b994",
}


def _money(nano: float) -> str:
    return f"US${nano / NANO_PER_USD:.4f}"


def _exposure(record: dict) -> int:
    actual = record["charged_nanodollars"]
    return record["reserved_nanodollars"] if actual is None else actual


def _labels(row: dict) -> str:
    if row["status"] != "valid":
        return "Unknown"
    if row["label"] is not None:
        return row["label"]
    distribution = row["distribution"]
    best = max(distribution.values())
    return ":".join(label for label in EMOTIONS if distribution.get(label) == best)


def pilot_report(
    pilot_dir: Path, ledger: BudgetLedger, model_id: str
) -> tuple[str, dict]:
    transcript = pilot_dir / "transcripts.jsonl"
    rows = (
        [
            json.loads(line)
            for line in transcript.read_text(encoding="utf-8").splitlines()
        ]
        if transcript.is_file()
        else []
    )
    run_id = _run_id(model_id, "pilot")
    attempts = ledger.records(run_id=run_id)
    charged = sum(row["charged_nanodollars"] or 0 for row in attempts)
    holds = sum(
        _exposure(row) for row in attempts if row["charged_nanodollars"] is None
    )
    served = sorted({row["served_model"] for row in attempts if row["served_model"]})
    lines = [
        "# Higher-tier Gemini pilot",
        "",
        f"Requested model `{model_id}`. Combined output cap {model_output_limit(model_id)} tokens. Sampling and thinking use provider defaults.",
        "Served model IDs "
        + (", ".join(f"`{name}`" for name in served) or "unavailable")
        + ".",
        "",
        "| Condition | Valid / planned | Unknown types | Mean metered cost per recorded cell | Mean thinking tokens | Max thinking tokens |",
        "| --- | ---: | --- | ---: | ---: | ---: |",
    ]
    distributions = []
    coverage = {}
    projected = 0
    for condition in CONDITIONS:
        group = [row for row in rows if row["condition"] == condition]
        statuses = Counter(row["status"] for row in group)
        coverage[condition] = statuses["valid"]
        states = {
            name: count for name, count in sorted(statuses.items()) if name != "valid"
        }
        pending = PILOT_PER_CONDITION - len(group)
        unknowns = [f"{name} {count}" for name, count in states.items()]
        if pending:
            unknowns.append(f"missing {pending}")
        request_rows = [row for row in attempts if row["condition"] == condition]
        metered = sum(row["charged_nanodollars"] or 0 for row in request_rows)
        mean = _money(metered / len(group)) if group else "—"
        thinking = [
            row["thinking_tokens"]
            for row in request_rows
            if row["thinking_tokens"] is not None
        ]
        mean_thinking = f"{statistics.mean(thinking):.1f}" if thinking else "—"
        max_thinking = str(max(thinking)) if thinking else "—"
        lines.append(
            f"| {condition} | {statuses['valid']}/24 | {', '.join(unknowns) or 'None'} | {mean} | {mean_thinking} | {max_thinking} |"
        )
        if len(group) == PILOT_PER_CONDITION:
            projected += (
                sum(_exposure(row) for row in request_rows)
                * MAIN_PER_CONDITION
                / PILOT_PER_CONDITION
            )
        labels = Counter(_labels(row) for row in group)
        distributions.append(
            f"| {condition} | "
            + ", ".join(f"{label} {count}" for label, count in sorted(labels.items()))
            + " |"
        )

    current = ledger.committed_nanodollars()
    third_current = ledger.committed_nanodollars(third=True)
    completed = len(rows) == PILOT_PER_CONDITION * len(CONDITIONS)
    gates = {
        "complete": completed,
        "strict_coverage": completed
        and all(count >= VALID_PER_CONDITION for count in coverage.values()),
        "projected_main_nano": projected if completed else None,
        "third_cap": completed and projected <= THIRD_NANO_CAP,
        "project_cap": completed and current + projected < PROJECT_NANO_CAP,
    }
    lines += [
        "",
        "| Condition | Predicted label counts (P3 uses tied largest shares) |",
        "| --- | --- |",
        *distributions,
        "",
        f"Pilot metered {_money(charged)}. Outstanding pilot reservations {_money(holds)}.",
    ]
    if completed:
        lines += [
            f"Projected fresh 1,500-call cost {_money(projected)}. This scales exposure, including unresolved attempts, within each condition.",
            f"Projected project exposure {_money(current + projected)}. Projected third-arm exposure including pilot calls {_money(third_current + projected)}.",
        ]
    unmet = [
        name.replace("_", " ")
        for name, passed in gates.items()
        if name != "projected_main_nano" and not passed
    ]
    if unmet:
        lines += ["", "Unmet operational gates: " + ", ".join(unmet) + "."]
    return "\n".join(lines) + "\n", gates


def _run_id(model_id: str, phase: str) -> str:
    return f"third-{phase}-{model_id.split('/', 1)[1]}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("pilot", "report", "main"))
    parser.add_argument("--model", choices=THIRD_GEMINI_MODELS, default=GEMINI_CARBON)
    parser.add_argument(
        "--freeze", help="Full SHA of the approved third-arm code and source lock"
    )
    parser.add_argument(
        "--verified-offline",
        action="store_true",
        help="Attest that the pinned offline checks passed",
    )
    args = parser.parse_args()
    root = Path.cwd()
    private = root / "results/private"
    main_dir = private / "main"
    pilot_dir = private / _run_id(args.model, "pilot")
    ledger = BudgetLedger(private / "project_budget.sqlite3")

    if args.phase == "report":
        report, gates = pilot_report(pilot_dir, ledger, args.model)
        (root / "results/THIRD_MODEL_PILOT_REPORT.md").write_text(
            report, encoding="utf-8", newline="\n"
        )
        print(json.dumps(gates))
        return

    if not args.verified_offline or not args.freeze:
        parser.error(
            "Live third-arm dispatch requires the frozen commit and passed offline checks"
        )
    if (
        subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        != args.freeze
    ):
        parser.error("The requested freeze is not checked out")
    if subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=no"], text=True
    ).strip():
        parser.error("The tracked workspace differs from the requested freeze")
    manifest = root / "data/manifest.csv"
    if hashlib.sha256(manifest.read_bytes()).hexdigest() != ORIGINAL_MANIFEST:
        parser.error("The manifest differs from the approved original-level freeze")
    for name, digest in FROZEN_PROMPTS.items():
        if hashlib.sha256((root / "prompts" / name).read_bytes()).hexdigest() != digest:
            parser.error(f"{name} differs from the approved prompt freeze")
    if len(list((main_dir / "samples").glob("*.json"))) != 3000:
        parser.error("The two-model main run must finish before the third arm")
    if args.phase == "main":
        _, gates = pilot_report(pilot_dir, ledger, args.model)
        if not all(
            gates[name]
            for name in ("complete", "strict_coverage", "third_cap", "project_cap")
        ):
            parser.error("The third model did not meet its live main-run gates")

    load_project_keys(root / ".env")
    for name in ("httpx", "httpcore", "openai", "google_genai", "google.genai"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
    try:
        run_evaluation(
            manifest_path=manifest,
            stimuli_dir=root / "data/local/stimuli",
            prompts_dir=root / "prompts",
            run_dir=pilot_dir if args.phase == "pilot" else main_dir / "third-model",
            run_id=_run_id(args.model, args.phase),
            subset=args.phase,
            model_ids=(args.model,),
            ledger=ledger,
            authorization=f"Zack conditional third-model approval, November 14, 2026; freeze {args.freeze}",
            main_approved=args.phase == "main",
        )
    except ThirdModelUnavailable as error:
        print(str(error))
        raise SystemExit(42) from None
    except (BudgetStop, PilotStopped) as error:
        raise SystemExit(str(error)) from None


if __name__ == "__main__":
    main()
