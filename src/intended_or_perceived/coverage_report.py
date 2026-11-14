"""Compare strict and amended operational coverage from saved run checkpoints."""

import argparse
import json
import re
import sqlite3
from collections import Counter, defaultdict
from contextlib import closing
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from intended_or_perceived.budget import GEMINI, GEMINI_CARBON, OPENAI
from intended_or_perceived.scoring import parse_recorded_output

CONDITIONS = ("P1-R1", "P1-R2", "P1-R3", "P2", "P3")
UNKNOWN = ("parse_error", "out_of_set", "refusal", "incomplete", "request_error")
_SAFE_ID = re.compile(r"[A-Za-z0-9_.:/-]{1,120}")


@dataclass(frozen=True)
class Run:
    path: Path
    run_id: str
    subset: str
    models: tuple[str, ...]
    stimuli: dict
    prompts: dict
    manifest_hash: str

    @classmethod
    def read(cls, path: Path, subset: str, models: tuple[str, ...]):
        header = json.loads((path / "inputs.json").read_text(encoding="utf-8"))
        size = 300 if subset == "main" else 24
        if (
            header["subset"] != subset
            or tuple(header["models"]) != models
            or tuple(header["conditions"]) != CONDITIONS
            or len(header["stimuli"]) != size
            or not _SAFE_ID.fullmatch(header["run_id"])
        ):
            raise ValueError(f"Unexpected checkpoint plan in {path.name}")
        return cls(
            path,
            header["run_id"],
            subset,
            models,
            header["stimuli"],
            header["prompts"],
            header["manifest_sha256"],
        )


@dataclass
class Coverage:
    strict: Counter = field(default_factory=Counter)
    amended: Counter = field(default_factory=Counter)
    retried: int = 0
    twice_failed: int = 0
    served: set[str] = field(default_factory=set)
    dates: set[str] = field(default_factory=set)


def _run_counts(run: Run):
    groups = defaultdict(Coverage)
    seen = set()
    for path in (run.path / "samples").glob("*.json"):
        row = json.loads(path.read_text(encoding="utf-8"))
        model, condition, sample = (
            row[key] for key in ("model", "condition", "sample_id")
        )
        cell = (model, condition, sample)
        if (
            cell in seen
            or model not in run.models
            or condition not in CONDITIONS
            or sample not in run.stimuli
            or row["run_id"] != run.run_id
            or row["manifest_sha256"] != run.manifest_hash
            or row["media_sha256"] != run.stimuli[sample]["sha256"]
            or row["prompt_sha256"] != run.prompts[condition]["sha256"]
            or row["prompt_file"] != run.prompts[condition]["file"]
            or row["prompt"] != run.prompts[condition]["family"]
        ):
            raise ValueError(
                f"Checkpoint does not match its frozen plan in {run.run_id}"
            )
        seen.add(cell)
        strict = parse_recorded_output(row, unwrap_fence=False).status
        amended = parse_recorded_output(row, unwrap_fence=True).status
        if strict not in {"valid", *UNKNOWN} or amended not in {"valid", *UNKNOWN}:
            raise ValueError(f"Unexpected operational status in {run.run_id}")
        group = groups[model, condition]
        group.strict[strict] += 1
        group.amended[amended] += 1
        retried = row["attempts"] == 2
        group.retried += retried
        group.twice_failed += (
            retried
            and strict == "request_error"
            and row.get("error")
            not in {
                "BudgetStop",
                "RequestRejected",
                "A previously reserved request has no recoverable completion",
            }
        )
        served = row.get("served_model")
        if isinstance(served, str) and _SAFE_ID.fullmatch(served):
            group.served.add(served)
        for timestamp in (row.get("started_at"), row.get("finished_at")):
            if timestamp:
                group.dates.add(
                    datetime.fromisoformat(timestamp).astimezone(UTC).date().isoformat()
                )
    return groups


def _ledger_snapshot(path: Path):
    uri = f"{path.resolve().as_uri()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=15)) as db:
        db.execute("BEGIN")
        cap = db.execute(
            "SELECT cap_nanodollars FROM project_budget WHERE id = 1"
        ).fetchone()[0]
        costs = db.execute(
            """
            SELECT COALESCE(r.run_id, 'pilot'), c.model, COUNT(*),
                   COALESCE(SUM(c.charged_nanodollars), 0),
                   SUM(CASE WHEN c.charged_nanodollars IS NULL
                            THEN c.reserved_nanodollars ELSE 0 END)
              FROM calls c LEFT JOIN call_runs r ON r.call_id = c.id
             GROUP BY 1, 2
            """
        ).fetchall()
    return cap, costs


def _usd(nanodollars):
    return f"US${nanodollars / 1_000_000_000:.4f}"


def build_report(
    main_dir: Path, carbon_main_dir: Path, carbon_pilot_dir: Path, ledger: Path
) -> str:
    incumbent = Run.read(main_dir, "main", (OPENAI, GEMINI))
    runs = [incumbent]
    for path, subset in ((carbon_pilot_dir, "pilot"), (carbon_main_dir, "main")):
        if (path / "inputs.json").is_file():
            run = Run.read(path, subset, (GEMINI_CARBON,))
            if (
                run.manifest_hash != incumbent.manifest_hash
                or run.prompts != incumbent.prompts
                or not run.stimuli.keys() <= incumbent.stimuli.keys()
                or any(
                    stimulus != incumbent.stimuli[sample]
                    for sample, stimulus in run.stimuli.items()
                )
            ):
                raise ValueError(
                    "Carbon checkpoint differs from the frozen study inputs"
                )
            runs.append(run)

    lines = [
        "# Strict and amended operational coverage",
        "",
        "Strict requires a raw JSON object. Amended coverage allows a single enclosing Markdown fence and retains the same schema checks. Counts use all planned clips as the denominator.",
        "Unknown columns show strict/amended counts. Both classifications use saved responses.",
        "",
    ]
    if not any(run.subset == "main" and GEMINI_CARBON in run.models for run in runs):
        lines.extend(
            [
                "Carbon main coverage is pending. Available Carbon pilot rows use the 24-clip pilot denominator.",
                "",
            ]
        )
    lines.extend(
        [
            "| Phase | Model | Condition | Strict valid | Amended valid | JSON/schema error | Out of set | Refusal | Incomplete | Request error | Missing | Retried | Failed twice |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    cap, costs = _ledger_snapshot(ledger)
    costs_by_model = {
        (run, model): (attempts, charged, held)
        for run, model, attempts, charged, held in costs
    }
    metadata = []
    for run in runs:
        groups = _run_counts(run)
        planned = len(run.stimuli)
        for model in run.models:
            model_served = set()
            model_dates = set()
            for condition in CONDITIONS:
                group = groups[model, condition]
                strict, amended = group.strict, group.amended
                fields = [
                    run.subset,
                    f"`{model}`",
                    condition,
                    f"{strict['valid']}/{planned}",
                    f"{amended['valid']}/{planned}",
                    *[f"{strict[kind]}/{amended[kind]}" for kind in UNKNOWN],
                    str(planned - strict.total()),
                    str(group.retried),
                    str(group.twice_failed),
                ]
                lines.append("| " + " | ".join(fields) + " |")
                model_served.update(group.served)
                model_dates.update(group.dates)
            served = (
                ", ".join(f"`{identifier}`" for identifier in sorted(model_served))
                or "Pending"
            )
            dates = (
                " to ".join(sorted({min(model_dates), max(model_dates)}))
                if model_dates
                else "Pending"
            )
            attempts, charged, held = costs_by_model.get((run.run_id, model), (0, 0, 0))
            metadata.append(
                f"| {run.subset} | `{model}` | {served} | {dates} | {attempts} | {_usd(charged)} | {_usd(held)} |"
            )
    total_charge = sum(row[3] for row in costs)
    total_held = sum(row[4] for row in costs)
    lines.extend(
        [
            "",
            "| Phase | Model | Served model IDs | UTC dates | Generation attempts | Metered | Holds |",
            "| --- | --- | --- | --- | ---: | ---: | ---: |",
            *metadata,
            "",
            f"Project metered {_usd(total_charge)} with {_usd(total_held)} held. Remaining headroom is {_usd(cap - total_charge - total_held)} under the {_usd(cap)} cap.",
        ]
    )
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    private = Path("results/private")
    parser.add_argument(
        "--ledger", type=Path, default=private / "project_budget.sqlite3"
    )
    parser.add_argument("--main-dir", type=Path, default=private / "main")
    parser.add_argument(
        "--carbon-main-dir", type=Path, default=private / "main/third-model"
    )
    parser.add_argument(
        "--carbon-pilot-dir", type=Path, default=private / "third-pilot-gemini-4-carbon"
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = build_report(
        args.main_dir, args.carbon_main_dir, args.carbon_pilot_dir, args.ledger
    )
    if args.output:
        args.output.write_text(report, encoding="utf-8", newline="\n")
    else:
        print(report, end="")


if __name__ == "__main__":
    main()
