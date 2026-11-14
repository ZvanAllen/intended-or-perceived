from intended_or_perceived.pilot import CONDITIONS, MODEL_IDS, write_report


def test_reports_observed_cost_and_fresh_main_projection(tmp_path):
    class Ledger:
        def records(self):
            return [
                {"model": model, "charged_nanodollars": 120_000_000, "reserved_nanodollars": 0}
                for model in MODEL_IDS
            ]

    manifest = tmp_path / "manifest.csv"
    manifest.write_text("pilot,duration_seconds\n1,2.5\n0,12\n", encoding="utf-8")
    report = tmp_path / "report.md"
    rows = [
        {"model": model, "condition": condition, "status": "valid"}
        for model in MODEL_IDS
        for condition in CONDITIONS
        for _ in range(24)
    ]

    complete = write_report(rows, Ledger(), report, manifest)
    assert "Projected project total with pilot **$3.24**" in complete
    assert "120/120 (100.0%)" in complete
    assert report.read_text(encoding="utf-8") == complete

    partial = write_report(rows[:-1], Ledger(), report, manifest)
    assert "119/120 (99.2%)" in partial
    assert "Projected project total" not in partial

    rows[0]["status"] = "request_error"

    class LedgerWithHold(Ledger):
        def records(self):
            return [
                *super().records(),
                {
                    "model": MODEL_IDS[0],
                    "charged_nanodollars": None,
                    "reserved_nanodollars": 4_000_000_000,
                },
            ]

    report_with_hold = write_report(rows, LedgerWithHold(), report, manifest)
    assert "Unresolved holds **$4.0000**" in report_with_hold
    assert "Budget planning total with existing unresolved holds **$7.25**" in report_with_hold
