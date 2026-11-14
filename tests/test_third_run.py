import json

from intended_or_perceived.budget import GEMINI_CARBON
from intended_or_perceived.evaluation import CONDITIONS
from intended_or_perceived.third_run import pilot_report


class Ledger:
    def __init__(self, cost, held):
        self.cost = cost
        self.held = held

    def records(self, run_id):
        records = [
            {
                "condition": condition,
                "charged_nanodollars": self.cost,
                "reserved_nanodollars": None,
                "served_model": GEMINI_CARBON.split("/")[1],
                "thinking_tokens": 20,
            }
            for condition in CONDITIONS
            for _ in range(24)
        ]
        records.append(
            {
                "condition": "P1-R1",
                "charged_nanodollars": None,
                "reserved_nanodollars": self.held,
                "served_model": None,
                "thinking_tokens": None,
            }
        )
        return records

    def committed_nanodollars(self, *, third=False):
        return (0 if third else 4_000_000_000) + 120 * self.cost + self.held


def test_pilot_counts_strict_conditions_and_projected_holds(tmp_path):
    outcomes = [
        {
            "condition": condition,
            "status": "valid",
            "label": "Fear" if condition != "P3" else None,
            "distribution": {"Fear": 0.5, "Neutral": 0.5},
        }
        for condition in CONDITIONS
        for _ in range(24)
    ]
    outcomes[-1].update(status="incomplete")
    path = tmp_path / "transcripts.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in outcomes), encoding="utf-8")

    report, gates = pilot_report(tmp_path, Ledger(5_000_000, 1_000_000), GEMINI_CARBON)
    assert gates["strict_coverage"] and gates["third_cap"] and gates["project_cap"]
    assert gates["projected_main_nano"] == 7_512_500_000
    assert "Fear:Neutral 23" in report
    assert "incomplete 1" in report

    _, gates = pilot_report(tmp_path, Ledger(7_000_000, 0), GEMINI_CARBON)
    assert not gates["third_cap"]
