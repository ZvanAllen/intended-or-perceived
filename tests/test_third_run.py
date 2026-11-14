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
            "prompt": condition.split("-")[0],
            "completion": (
                '{"label":"Fear","confidence":50}'
                if condition != "P3"
                else '{"Anger":0,"Disgust":0,"Fear":50,"Happy":0,"Neutral":50,"Sad":0}'
            ),
        }
        for condition in CONDITIONS
        for _ in range(24)
    ]
    outcomes[-1].update(status="incomplete", stop_reason="max_tokens")
    for row in outcomes[:6]:
        row.update(
            status="parse_error", completion=f"```json\n{row['completion']}\n```"
        )
    path = tmp_path / "transcripts.jsonl"
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in outcomes), encoding="utf-8"
    )

    report, gates = pilot_report(tmp_path, Ledger(5_000_000, 1_000_000), GEMINI_CARBON)
    assert not gates["strict_coverage"]
    assert gates["amended_coverage"] and gates["third_cap"] and gates["project_cap"]
    assert "| P1-R1 | 18/24 | 24/24 | parse_error 6 | None |" in report
    assert gates["projected_main_nano"] == 7_512_500_000
    assert "Fear:Neutral 23" in report
    assert "incomplete 1" in report

    _, gates = pilot_report(tmp_path, Ledger(7_000_000, 0), GEMINI_CARBON)
    assert not gates["third_cap"]
