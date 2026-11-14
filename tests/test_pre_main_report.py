from intended_or_perceived.pre_main import write_audio_report, write_pre_main_report


def test_transcription_checks_only_words_and_preserves_mismatch(tmp_path):
    model = "test/example"
    gains = [
        {
            "sample_id": sample_id,
            "expected_words": "It's eleven o'clock.",
            "source_rms_dbfs": "-40",
            "source_peak_dbfs": "-20",
            "applied_gain_db": "19",
        }
        for sample_id in ("clip001", "clip002")
    ]
    d1 = [
        {
            "model": model,
            "sample_id": "clip001",
            "status": "valid",
            "completion": "IT’S ELEVEN O’CLOCK!",
        },
        {
            "model": model,
            "sample_id": "clip002",
            "status": "valid",
            "completion": "It is eleven o'clock.",
        },
    ]
    path = tmp_path / "diagnostic.md"

    write_audio_report(path, {"clips": 300}, gains, [], d1, [], (model,))

    report = path.read_text(encoding="utf-8")
    assert "1/2 (50.0%)" in report
    assert "clip002 | It's eleven o'clock. | It is eleven o'clock." in report
    assert "clip001 | It's eleven o'clock." not in report


def test_revised_prompt_report_keeps_strict_and_fence_counts_separate(tmp_path):
    class Ledger:
        def records(self):
            return []

    model = "test/example"
    payload = '{"Anger":0,"Disgust":0,"Fear":0,"Happy":0,"Neutral":100,"Sad":0}'
    revised = [
        {"model": model, "status": "valid", "completion": payload},
        {
            "model": model,
            "status": "parse_error",
            "completion": f"```json\n{payload}\n```",
        },
        {
            "model": model,
            "status": "parse_error",
            "completion": f"```json\n{payload}\n``` extra",
        },
    ]
    path = tmp_path / "p3.md"

    strict = write_pre_main_report(path, revised, Ledger(), (model,))

    assert strict == {model: 1}
    assert "1/24 | 1 |" in path.read_text(encoding="utf-8")
