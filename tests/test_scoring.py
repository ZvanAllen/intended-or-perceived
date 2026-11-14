import pytest

from intended_or_perceived.scoring import label_matches, parse_output


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
