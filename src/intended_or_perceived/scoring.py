"""Parse and score model outputs without altering the original completion."""

import json
from dataclasses import asdict, dataclass
from decimal import Decimal

EMOTIONS = ("Anger", "Disgust", "Fear", "Happy", "Neutral", "Sad")
_LABELS = {name.casefold(): name for name in EMOTIONS}


@dataclass(frozen=True)
class ParsedOutput:
    status: str
    label: str | None = None
    confidence: float | None = None
    distribution: dict[str, float] | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("Duplicate JSON key")
        obj[key] = value
    return obj


def _invalid_constant(_: str) -> None:
    raise ValueError("Non-finite JSON number")


def _is_percentage(value: object) -> bool:
    return isinstance(value, Decimal) and value.is_finite() and 0 <= value <= 100


def parse_output(
    text: str, prompt: str, *, stop_reason: str | None = None
) -> ParsedOutput:
    """Validate a forced-choice or distribution completion."""
    prompt = prompt.upper()
    if prompt not in {"P1", "P2", "P3"}:
        raise ValueError(f"Unknown prompt version {prompt!r}")
    if stop_reason in {"content_filter", "safety", "model_refusal", "refusal"}:
        return ParsedOutput("refusal")
    if stop_reason in {"length", "max_tokens", "model_length"}:
        return ParsedOutput("incomplete")

    try:
        obj = json.loads(
            text,
            parse_int=Decimal,
            parse_float=Decimal,
            parse_constant=_invalid_constant,
            object_pairs_hook=_unique_object,
        )
    except (ValueError, ArithmeticError, RecursionError):
        return ParsedOutput("parse_error")
    if not isinstance(obj, dict):
        return ParsedOutput("parse_error")

    if prompt == "P3":
        if set(obj) != set(EMOTIONS) or not all(map(_is_percentage, obj.values())):
            return ParsedOutput("parse_error")
        if abs(sum(obj.values()) - 100) > Decimal("0.000001"):
            return ParsedOutput("parse_error")
        return ParsedOutput(
            "valid", distribution={name: float(obj[name]) / 100 for name in EMOTIONS}
        )

    if set(obj) != {"label", "confidence"} or not isinstance(obj["label"], str):
        return ParsedOutput("parse_error")
    label = _LABELS.get(obj["label"].casefold())
    if label is None:
        return ParsedOutput("out_of_set")
    if not _is_percentage(obj["confidence"]):
        return ParsedOutput("parse_error")
    return ParsedOutput("valid", label=label, confidence=float(obj["confidence"]))


def label_matches(label: str | None, reference: str) -> bool | None:
    """Score a label against a possibly tied plurality; preserve unknowns."""
    return None if label is None else label in reference.split(":")
