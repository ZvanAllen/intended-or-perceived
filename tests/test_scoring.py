import pytest

from intended_or_perceived.scoring import (
    label_matches,
    parse_output,
    parse_recorded_output,
)


def test_forced_choice():
    parsed = parse_output('{"label":"anger","confidence":97.5}', "P1")
    assert (parsed.status, parsed.label, parsed.confidence) == ("valid", "Anger", 97.5)
    assert label_matches(parsed.label, "Anger:Disgust") is True
    assert label_matches(parsed.label, "Neutral:Disgust") is False


@pytest.mark.parametrize(
    ("completion", "stop", "status"),
    [
        ('```json\n{"label":"Anger","confidence":5}\n```', None, "parse_error"),
        ('{"label":"Anger","confidence":true}', None, "parse_error"),
        ('{"label":"Anger","confidence":NaN}', None, "parse_error"),
        ('{"label":"Anger","label":"Sad","confidence":0}', None, "parse_error"),
        ('{"label":"Surprise","confidence":90}', None, "out_of_set"),
        ("", "content_filter", "refusal"),
        ('{"label":"Anger","confidence":5}', "max_tokens", "incomplete"),
    ],
)
def test_unknowns(completion, stop, status):
    parsed = parse_output(completion, "P2", stop_reason=stop)
    assert parsed.status == status
    assert label_matches(parsed.label, "Anger") is None


def test_distribution():
    obj = '{"Anger":5,"Disgust":0,"Fear":5,"Happy":70,"Neutral":10,"Sad":10}'
    parsed = parse_output(obj, "P3")
    assert parsed.status == "valid"
    assert parsed.distribution["Happy"] == 0.7
    assert sum(parsed.distribution.values()) == pytest.approx(1)
    assert parse_output(obj.replace("70", "71"), "P3").status == "parse_error"


@pytest.mark.parametrize(
    ("prompt", "payload"),
    [
        ("P1", '{"label":"Anger","confidence":5}'),
        ("P2", '{"label":"Sad","confidence":50}'),
        ("P3", '{"Anger":5,"Disgust":0,"Fear":5,"Happy":70,"Neutral":10,"Sad":10}'),
    ],
)
@pytest.mark.parametrize("marker", ["```json", "```", "````JSON", "~~~json"])
def test_unwrap_exactly_one_complete_fence(prompt, payload, marker):
    end = marker.rstrip("jsonJSON")
    fenced = f" \r\n{marker}\r\n{payload}\r\n{end}\r\n  "
    expected = parse_output(payload, prompt)
    assert expected.status == "valid"
    assert parse_output(fenced, prompt, unwrap_fence=False).status == "parse_error"
    assert parse_output(fenced, prompt, unwrap_fence=True) == expected


@pytest.mark.parametrize(
    "template",
    [
        "prefix\n```json\n%s\n```",
        "```json\n%s\n```\ntrailing text",
        "```json\n%s\n```\n```json\n{}\n```",
        "````json\n```json\n%s\n```\n````",
        "```json\n%s\n~~~",
        "````json\n%s\n```",
        "```json\n%s",
        "```json %s```",
    ],
)
def test_ambiguous_incomplete_and_nested_fences_remain_unknown(template):
    payload = '{"label":"Sad","confidence":50}'
    assert (
        parse_output(template % payload, "P1", unwrap_fence=True).status
        == "parse_error"
    )


def test_reparse_keeps_schema_and_stop_status_rules():
    row = {
        "prompt": "P1",
        "completion": '```json\n{"label":"surprise","confidence":40}\n```',
    }
    assert parse_recorded_output(row).status == "out_of_set"
    assert parse_recorded_output(row, unwrap_fence=False).status == "parse_error"
    for status, stop in [("refusal", "content_filter"), ("incomplete", "max_tokens")]:
        assert parse_recorded_output({**row, "stop_reason": stop}).status == status
    assert (
        parse_recorded_output({"status": "request_error", "completion": None}).status
        == "request_error"
    )
    assert row["completion"].startswith("```json")
