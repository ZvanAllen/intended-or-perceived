import json
import sqlite3
from contextlib import closing

import pytest

from intended_or_perceived.budget import GEMINI, GEMINI_CARBON, OPENAI, BudgetLedger
from intended_or_perceived.coverage_report import CONDITIONS, build_report


def write_run(path, subset, models):
    (path / "samples").mkdir(parents=True)
    header = {
        "run_id": path.name,
        "subset": subset,
        "models": models,
        "conditions": CONDITIONS,
        "stimuli": {
            f"clip{i:03d}": {"sha256": "media"}
            for i in range(300 if subset == "main" else 24)
        },
        "prompts": {
            name: {
                "sha256": "prompt",
                "file": name + ".txt",
                "family": name.split("-")[0],
            }
            for name in CONDITIONS
        },
        "manifest_sha256": "manifest",
    }
    (path / "inputs.json").write_text(json.dumps(header), encoding="utf-8")
    return header


def write_row(path, model, sample, *, completion, status, **extra):
    row = {
        "run_id": path.name,
        "model": model,
        "condition": "P1-R1",
        "sample_id": sample,
        "prompt": "P1",
        "prompt_file": "P1-R1.txt",
        "manifest_sha256": "manifest",
        "media_sha256": "media",
        "prompt_sha256": "prompt",
        "status": status,
        "completion": completion,
        "attempts": 1,
        "served_model": model.split("/", 1)[1],
        "started_at": "2026-11-14T23:00:00Z",
        **extra,
    }
    (path / "samples" / f"{sample}.json").write_text(json.dumps(row), encoding="utf-8")


def test_operational_coverage_reports_strict_amended_and_budget(tmp_path):
    main, carbon_main, pilot = (
        tmp_path / name for name in ("main", "main/third-model", "third-pilot")
    )
    write_run(main, "main", (OPENAI, GEMINI))
    write_run(pilot, "pilot", (GEMINI_CARBON,))
    write_row(
        main,
        OPENAI,
        "clip000",
        completion='```json\n{"label":"Anger","confidence":45}\n```',
        status="parse_error",
    )
    write_row(
        main,
        OPENAI,
        "clip001",
        completion=None,
        status="request_error",
        attempts=2,
        error=503,
    )
    write_row(
        pilot,
        GEMINI_CARBON,
        "clip002",
        completion="sensitive sentinel",
        status="refusal",
        stop_reason="content_filter",
    )
    ledger = BudgetLedger(tmp_path / "budget.sqlite3")
    with closing(sqlite3.connect(ledger.path)) as db, db:
        db.execute(
            """INSERT INTO calls(model, condition, sample_id, requested_at, status, reserved_nanodollars)
               VALUES (?, 'P1-R1', 'clip001', '2026-11-14', 'ambiguous', 100000000)""",
            (OPENAI,),
        )
        db.execute("INSERT INTO call_runs(call_id, run_id) VALUES (1, 'main')")
    report = build_report(main, carbon_main, pilot, ledger.path)
    assert "Carbon main coverage is pending" in report
    assert (
        f"| main | `{OPENAI}` | P1-R1 | 0/300 | 1/300 | 1/0 | 0/0 | 0/0 | 0/0 | 1/1 | 298 | 1 | 1 |"
        in report
    )
    assert (
        f"| pilot | `{GEMINI_CARBON}` | P1-R1 | 0/24 | 0/24 | 0/0 | 0/0 | 1/1" in report
    )
    assert "US$0.1000 held" in report and "US$24.9000" in report
    assert all(
        value not in report for value in ("sensitive sentinel", "Anger", '"confidence"')
    )

    write_run(carbon_main, "main", (GEMINI_CARBON,))
    write_row(
        carbon_main,
        GEMINI_CARBON,
        "clip000",
        completion='{"label":"Anger","confidence":50}',
        status="valid",
    )
    report = build_report(main, carbon_main, pilot, ledger.path)
    assert "Carbon main coverage is pending" not in report
    assert f"| main | `{GEMINI_CARBON}` | P1-R1 | 1/300 | 1/300" in report


def test_coverage_rejects_checkpoint_hash_drift(tmp_path):
    main = tmp_path / "main"
    write_run(main, "main", (OPENAI, GEMINI))
    write_row(
        main,
        OPENAI,
        "clip000",
        completion="",
        status="parse_error",
        media_sha256="wrong",
    )
    ledger = BudgetLedger(tmp_path / "budget.sqlite3")
    with pytest.raises(ValueError, match="does not match its frozen plan"):
        build_report(main, tmp_path / "no-main", tmp_path / "no-pilot", ledger.path)
