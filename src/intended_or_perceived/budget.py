"""Reserve model spend before each HTTP generation and persist billable usage."""

import base64
import binascii
import io
import json
import math
import re
import sqlite3
import wave
from contextlib import closing, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from pathlib import Path
from time import monotonic

import httpx

OPENAI = "openai/gpt-audio-1.5"
GEMINI = "google/gemini-3.5-flash-lite"
GEMINI_CARBON = "google/gemini-4-carbon"
GEMINI_ARGON = "google/gemini-4-argon"
GEMINI_HYDROGEN = "google/gemini-4-hydrogen"
GEMINI_FLASH_38 = "google/gemini-3.8-flash"
THIRD_GEMINI_MODELS = (GEMINI_CARBON, GEMINI_ARGON, GEMINI_HYDROGEN, GEMINI_FLASH_38)
PROJECT_CAP_NANODOLLARS = 25_000_000_000
DIAGNOSTIC_CAP_NANODOLLARS = 500_000_000
MAX_OUTPUT_TOKENS = 256
THIRD_MAX_OUTPUT_TOKENS = 1024
OPENAI_HOST = "api.openai.com"
GOOGLE_HOST = "generativelanguage.googleapis.com"

# USD per million tokens, expressed as integer nanodollars per token.
OPENAI_TEXT_INPUT = 2_500
OPENAI_AUDIO_INPUT = 32_000
OPENAI_TEXT_OUTPUT = 10_000
OPENAI_AUDIO_OUTPUT = 64_000
GEMINI_INPUT = 300
GEMINI_CACHED_INPUT = 30
GEMINI_OUTPUT = 2_500
INPUT_LIMIT = {
    OPENAI: 128_000,
    **dict.fromkeys((GEMINI, *THIRD_GEMINI_MODELS), 1_048_576),
}

# Documented paid Standard introductory rates and their last advertised day.
# On that last UTC day, stop before dispatch so a request cannot overlap a
# regional billing cutover. Reverify published rates before enabling later runs.
_GEMINI_PRICE_EXPIRY = {
    GEMINI_CARBON: date(2026, 11, 30),
    GEMINI_ARGON: date(2026, 11, 30),
    GEMINI_FLASH_38: date(2026, 12, 31),
}
_GEMINI_RATES = {
    GEMINI: (GEMINI_INPUT, GEMINI_CACHED_INPUT, GEMINI_OUTPUT),
    GEMINI_CARBON: (2_000, 100, 10_000),
    GEMINI_ARGON: (2_000, 100, 10_000),
    GEMINI_HYDROGEN: (1_500, 75, 7_500),
    GEMINI_FLASH_38: (750, 75, 3_750),
}

_SCOPE = ContextVar("budget_scope", default=None)
_IDENTIFIER = re.compile(r"[A-Za-z0-9_.:-]{1,120}")
_GOOGLE_FILE = re.compile(r"/v1beta/files/[A-Za-z0-9._-]+")
_GOOGLE_FILE_MIME = {"audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav"}
_STANDARD_GEMINI_TIERS = (None, "standard", "unspecified", "STANDARD", "UNSPECIFIED")
_DURATION_PAD_SECONDS = 0.1
# Twice Google's published 32 tokens per second and over eight times the observed
# GPT-Audio pilot rate. Add framing allowances to the audio and text estimates.
_AUDIO_TOKENS_PER_SECOND = 64
_AUDIO_FRAMING_TOKENS = 16
_TEXT_FRAMING_TOKENS = 128
_WIRE_OVERHEAD_BYTES = 4096


class BudgetStop(RuntimeError):
    """The spend cap or a pricing assumption prevents further model requests."""


class RequestRejected(RuntimeError):
    """A request was rejected before dispatch by the provider allowlist."""


class ProviderRequestError(RuntimeError):
    """A provider rejected billing, authentication or another request prerequisite."""

    def __init__(self, model: str, http_status: int):
        self.http_status = http_status
        super().__init__(f"{model} rejected the request (HTTP {http_status})")


class OptionalModelUnavailable(ProviderRequestError):
    """The verified generation endpoint reported that this optional model is unavailable."""


class ProviderTransportError(RuntimeError):
    """A network failure with an optional already-received HTTP status."""

    def __init__(self, model: str, http_status: int | None):
        self.http_status = http_status
        detail = (
            "before a response" if http_status is None else f"after HTTP {http_status}"
        )
        super().__init__(f"{model} transport failed {detail}")


def model_output_limit(model: str) -> int:
    if model not in INPUT_LIMIT:
        raise ValueError("Model does not have verified pricing")
    return (
        THIRD_MAX_OUTPUT_TOKENS if model in THIRD_GEMINI_MODELS else MAX_OUTPUT_TOKENS
    )


def _gemini_rates(model: str, as_of: date | None = None) -> tuple[int, int, int]:
    expiry = _GEMINI_PRICE_EXPIRY.get(model)
    if expiry is not None and (as_of or datetime.now(UTC).date()) >= expiry:
        raise BudgetStop(
            "Optional model's introductory Gemini tariff needs re-verification"
        )
    return _GEMINI_RATES[model]


def _require_model_scope(model: str, run_id: str) -> None:
    if run_id.startswith("third-") != (model in THIRD_GEMINI_MODELS):
        raise RequestRejected("Optional models may only be used in a third-model run")


@dataclass(frozen=True)
class _Scope:
    condition: str
    sample_id: str
    run_id: str
    media_duration_seconds: float | None
    media_bytes: bytes | None
    prompt_bytes: bytes | None


@contextmanager
def budget_scope(
    condition: str,
    sample_id: str,
    *,
    run_id: str = "pilot",
    media_duration_seconds: float | None = None,
    media_bytes: bytes | None = None,
    prompt_bytes: bytes | None = None,
):
    """Attach only opaque experiment identifiers to the request ledger."""
    if any(
        not _IDENTIFIER.fullmatch(value) for value in (condition, sample_id, run_id)
    ):
        raise RequestRejected("Invalid experiment request identifiers")
    token = _SCOPE.set(
        _Scope(
            condition,
            sample_id,
            run_id,
            media_duration_seconds,
            media_bytes,
            prompt_bytes,
        )
    )
    try:
        yield
    finally:
        _SCOPE.reset(token)


@dataclass(frozen=True)
class ReservationProfile:
    """Largest verified stimulus and prompt in the run's frozen request envelope."""

    max_duration_seconds: float
    max_media_bytes: int
    max_prompt_bytes: int

    def __post_init__(self):
        if (
            not math.isfinite(self.max_duration_seconds)
            or self.max_duration_seconds <= 0
            or min(self.max_media_bytes, self.max_prompt_bytes) <= 0
        ):
            raise ValueError("Reservation dimensions must be positive and finite")

    @property
    def max_wire_bytes(self) -> int:
        # Base64 expansion plus worst-case JSON ASCII escape overhead for prompt text.
        return (
            4 * math.ceil(self.max_media_bytes / 3)
            + 6 * self.max_prompt_bytes
            + _WIRE_OVERHEAD_BYTES
        )

    def max_reservation_nanodollars(self, model: str) -> int:
        return _reservation(
            model,
            model_output_limit(model),
            *_input_bounds(self.max_duration_seconds, self.max_prompt_bytes),
        )


def _input_bounds(duration: float, prompt_length: int) -> tuple[int, int]:
    return (
        math.ceil((duration + _DURATION_PAD_SECONDS) * _AUDIO_TOKENS_PER_SECOND)
        + _AUDIO_FRAMING_TOKENS,
        prompt_length + _TEXT_FRAMING_TOKENS,
    )


@dataclass(frozen=True)
class Usage:
    charged_nanodollars: int
    cost_basis: str
    response_id: str | None
    served_model: str | None
    input_tokens: int | None
    input_audio_tokens: int | None
    input_cached_tokens: int | None
    output_tokens: int | None
    output_audio_tokens: int | None
    thinking_tokens: int | None


class BudgetLedger:
    def __init__(self, path: Path, cap_nanodollars: int = PROJECT_CAP_NANODOLLARS):
        if not 0 < cap_nanodollars <= PROJECT_CAP_NANODOLLARS:
            raise ValueError("The budget must be positive and at most US$25")
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.cap_nanodollars = cap_nanodollars
        with closing(self._connect()) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS calls (
                    id INTEGER PRIMARY KEY,
                    model TEXT NOT NULL,
                    condition TEXT NOT NULL,
                    sample_id TEXT NOT NULL,
                    requested_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    reserved_nanodollars INTEGER NOT NULL,
                    charged_nanodollars INTEGER,
                    latency_ms INTEGER,
                    http_status INTEGER,
                    served_model TEXT,
                    response_id TEXT,
                    input_tokens INTEGER,
                    input_audio_tokens INTEGER,
                    input_cached_tokens INTEGER,
                    output_tokens INTEGER,
                    output_audio_tokens INTEGER,
                    thinking_tokens INTEGER,
                    cost_basis TEXT
                );
                CREATE TABLE IF NOT EXISTS project_budget (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    cap_nanodollars INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS call_runs (
                    call_id INTEGER PRIMARY KEY REFERENCES calls(id),
                    run_id TEXT NOT NULL
                );
                """
            )
            connection.execute(
                "INSERT OR IGNORE INTO project_budget VALUES (1, ?)", (cap_nanodollars,)
            )
            recorded_cap = connection.execute(
                "SELECT cap_nanodollars FROM project_budget WHERE id = 1"
            ).fetchone()[0]
            if recorded_cap != cap_nanodollars:
                raise BudgetStop(
                    "The requested cap differs from the durable project cap"
                )

    def _connect(self):
        return sqlite3.connect(self.path, timeout=30)

    @staticmethod
    def _committed(connection, *, run_pattern: str | None = None) -> int:
        subset = ""
        parameters = ()
        if run_pattern is not None:
            subset = " JOIN call_runs r ON r.call_id = calls.id WHERE r.run_id GLOB ?"
            parameters = (run_pattern,)
        return connection.execute(
            "SELECT COALESCE(SUM(COALESCE(charged_nanodollars, reserved_nanodollars)), 0)"
            " FROM calls" + subset,
            parameters,
        ).fetchone()[0]

    def committed_nanodollars(
        self, *, diagnostic: bool = False, third: bool = False
    ) -> int:
        if diagnostic and third:
            raise ValueError("Select one run family or the complete ledger")
        pattern = "third-*" if third else "diagnostic-*" if diagnostic else None
        with closing(self._connect()) as connection:
            return self._committed(connection, run_pattern=pattern)

    def records(self, run_id: str | None = None) -> list[dict]:
        select = (
            "SELECT calls.*, COALESCE(r.run_id, 'pilot') AS run_id FROM calls"
            " LEFT JOIN call_runs r ON r.call_id = calls.id"
        )
        parameters = ()
        if run_id is not None:
            select += " WHERE COALESCE(r.run_id, 'pilot') = ?"
            parameters = (run_id,)
        with closing(self._connect()) as connection:
            connection.row_factory = sqlite3.Row
            return [
                dict(row)
                for row in connection.execute(select + " ORDER BY calls.id", parameters)
            ]

    def reserve(self, model: str, amount: int) -> int:
        scope = _SCOPE.get()
        if scope is None:
            raise RequestRejected("Request is outside an active experiment sample")
        if model not in INPUT_LIMIT or amount <= 0:
            raise RequestRejected("Invalid model budget reservation")
        _require_model_scope(model, scope.run_id)
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            breach = connection.execute(
                "SELECT 1 FROM calls WHERE status = 'limit_exceeded' LIMIT 1"
            ).fetchone()
            if breach:
                raise BudgetStop("A prior response exceeded a verified request bound")
            if self._committed(connection) + amount > self.cap_nanodollars:
                raise BudgetStop(
                    "Project budget cannot cover the next request reservation"
                )
            if (
                scope.run_id.startswith("diagnostic-")
                and self._committed(connection, run_pattern="diagnostic-*") + amount
                > DIAGNOSTIC_CAP_NANODOLLARS
            ):
                raise BudgetStop(
                    "US$0.50 diagnostic budget cannot cover the next request"
                )
            row = connection.execute(
                "INSERT INTO calls (model, condition, sample_id, requested_at, status, "
                "reserved_nanodollars) VALUES (?, ?, ?, ?, 'reserved', ?)",
                (
                    model,
                    scope.condition,
                    scope.sample_id,
                    datetime.now(UTC).isoformat(),
                    amount,
                ),
            )
            connection.execute(
                "INSERT INTO call_runs (call_id, run_id) VALUES (?, ?)",
                (row.lastrowid, scope.run_id),
            )
            return row.lastrowid

    def finish(
        self,
        call_id: int,
        usage: Usage | None,
        latency_ms: int,
        http_status: int | None,
        *,
        bound_exceeded: bool = False,
    ) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            reservation = connection.execute(
                "SELECT reserved_nanodollars FROM calls WHERE id = ? AND status = 'reserved'",
                (call_id,),
            ).fetchone()
            if reservation is None:
                raise BudgetStop("Request has no open reservation")
            if usage is None:
                status = "limit_exceeded" if bound_exceeded else "ambiguous"
                connection.execute(
                    "UPDATE calls SET status = ?, latency_ms = ?, http_status = ?"
                    " WHERE id = ?",
                    (status, latency_ms, http_status, call_id),
                )
                return
            exceeded = bound_exceeded or usage.charged_nanodollars > reservation[0]
            status = "limit_exceeded" if exceeded else "settled"
            connection.execute(
                "UPDATE calls SET status = ?, charged_nanodollars = ?, latency_ms = ?,"
                " http_status = ?, served_model = ?, response_id = ?, input_tokens = ?,"
                " input_audio_tokens = ?, input_cached_tokens = ?, output_tokens = ?,"
                " output_audio_tokens = ?, thinking_tokens = ?, cost_basis = ? WHERE id = ?",
                (
                    status,
                    usage.charged_nanodollars,
                    latency_ms,
                    http_status,
                    usage.served_model,
                    usage.response_id,
                    usage.input_tokens,
                    usage.input_audio_tokens,
                    usage.input_cached_tokens,
                    usage.output_tokens,
                    usage.output_audio_tokens,
                    usage.thinking_tokens,
                    usage.cost_basis,
                    call_id,
                ),
            )
        if exceeded:
            raise BudgetStop("Response usage exceeded the request reservation")


def _first_party(request, host: str) -> bool:
    url = request.url
    return (
        url.scheme == "https"
        and url.host == host
        and url.port in (None, 443)
        and not url.username
        and not url.password
        and request.headers.get("host") in (host, f"{host}:443")
    )


def _check_scope(profile: ReservationProfile) -> _Scope:
    scope = _SCOPE.get()
    if (
        scope is None
        or not isinstance(scope.media_bytes, bytes)
        or not isinstance(scope.prompt_bytes, bytes)
        or scope.media_duration_seconds is None
        or not math.isfinite(scope.media_duration_seconds)
        or not 0 < scope.media_duration_seconds <= profile.max_duration_seconds
        or not 0 < len(scope.media_bytes) <= profile.max_media_bytes
        or not 0 < len(scope.prompt_bytes) <= profile.max_prompt_bytes
    ):
        raise RequestRejected(
            "Stimulus or prompt exceeds the verified request envelope"
        )
    if scope.media_bytes.startswith(b"RIFF"):
        try:
            with wave.open(io.BytesIO(scope.media_bytes)) as audio:
                duration = audio.getnframes() / audio.getframerate()
                is_pcm = audio.getsampwidth() == 2 and audio.getnchannels() == 1
        except (EOFError, wave.Error, ZeroDivisionError):
            raise RequestRejected("WAV media has an invalid PCM header") from None
        if (
            not is_pcm
            or abs(duration - scope.media_duration_seconds) > _DURATION_PAD_SECONDS
        ):
            raise RequestRejected("WAV media differs from the verified PCM envelope")
    return scope


def validate_google_files_request(
    request, *, profile: ReservationProfile | None = None
) -> None:
    """Allow only the free first-party Files API upload, poll and deletion paths."""
    if _first_party(request, GOOGLE_HOST):
        path = request.url.path
        if request.method == "POST" and path == "/upload/v1beta/files":
            if profile is not None:
                scope = _check_scope(profile)
                _validate_google_upload(request, scope.media_bytes)
            return
        if request.method in ("GET", "DELETE") and _GOOGLE_FILE.fullmatch(path):
            return
    raise RequestRejected(
        "Request does not match an allowed Google Files API operation"
    )


def _validate_google_upload(request, expected_media: bytes) -> None:
    command = request.headers.get("x-goog-upload-command", "")
    offset = request.headers.get("x-goog-upload-offset", "")
    if command == "start":
        if request.headers.get("x-goog-upload-header-content-length") == str(
            len(expected_media)
        ):
            return
    elif (
        command in ("upload", "upload, finalize")
        and offset.isascii()
        and offset.isdecimal()
    ):
        start = int(offset)
        media = request.content
        end = start + len(media)
        if (
            media
            and end <= len(expected_media)
            and media == expected_media[start:end]
            and (command == "upload" or end == len(expected_media))
        ):
            return
    raise RequestRejected("Gemini Files upload differs from the verified stimulus")


def _text_matches(part: dict, expected: bytes) -> bool:
    text = part.get("text")
    return (
        isinstance(text, str)
        and text.encode("utf-8", errors="surrogatepass") == expected
    )


def _validate_wire_input(model, payload, scope):
    # Both pinned adapters emit one user message containing one audio part plus one prompt.
    if model == OPENAI:
        messages = payload.get("messages")
        source_key, parts_key = "input_audio", "content"
    else:
        messages = payload.get("contents")
        source_key, parts_key = "fileData", "parts"
    if not isinstance(messages, list) or len(messages) != 1:
        raise RequestRejected("Generation must carry one verified user message")
    message = _object(messages[0])
    parts = message.get(parts_key)
    if message.get("role") != "user" or not isinstance(parts, list) or len(parts) != 2:
        raise RequestRejected(
            "Generation does not match the verified audio and prompt shape"
        )
    sources = [_object(part) for part in parts if source_key in _object(part)]
    prompts = [_object(part) for part in parts if "text" in _object(part)]
    if (
        len(sources) != 1
        or len(prompts) != 1
        or not _text_matches(prompts[0], scope.prompt_bytes)
    ):
        raise RequestRejected("Generation input differs from the verified prompt")
    source = _object(sources[0][source_key])
    is_wav = scope.media_bytes.startswith(b"RIFF")
    if model == OPENAI:
        try:
            media = base64.b64decode(source.get("data", ""), validate=True)
        except (ValueError, TypeError, binascii.Error):
            raise RequestRejected("OpenAI request audio is not valid base64") from None
        expected_format = "wav" if is_wav else "mp3"
        if (
            set(source) == {"data", "format"}
            and source["format"] == expected_format
            and media == scope.media_bytes
        ):
            return
    elif set(source) in ({"fileUri", "mimeType"}, {"file_uri", "mime_type"}):
        uri = source.get("fileUri", source.get("file_uri"))
        media_type = source.get("mimeType", source.get("mime_type"))
        trusted_uri = isinstance(uri, str) and uri.startswith(
            f"https://{GOOGLE_HOST}/v1beta/files/"
        )
        if (
            trusted_uri
            and _GOOGLE_FILE.fullmatch(uri.removeprefix(f"https://{GOOGLE_HOST}"))
            and isinstance(media_type, str)
            and media_type in _GOOGLE_FILE_MIME
            and is_wav == (media_type in ("audio/wav", "audio/x-wav"))
        ):
            return
    raise RequestRejected("Generation input differs from the verified stimulus")


def _token_count(value) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _object(value) -> dict:
    return value if isinstance(value, dict) else {}


def _identifier(value) -> str | None:
    return value if isinstance(value, str) and _IDENTIFIER.fullmatch(value) else None


def _sanitize_usage(usage: Usage, request) -> Usage:
    authorization = request.headers.get("authorization", "")
    secrets = (
        authorization.removeprefix("Bearer "),
        request.headers.get("x-goog-api-key", ""),
    )
    values = {
        field: None
        for field in ("served_model", "response_id")
        if (value := getattr(usage, field))
        and any(secret and secret in value for secret in secrets)
    }
    return replace(usage, **values) if values else usage


def _openai_usage(payload: dict) -> Usage | None:
    usage = _object(payload.get("usage"))
    input_tokens = _token_count(usage.get("prompt_tokens"))
    output_tokens = _token_count(usage.get("completion_tokens"))
    if input_tokens is None or output_tokens is None:
        return None
    prompt = _object(usage.get("prompt_tokens_details"))
    completion = _object(usage.get("completion_tokens_details"))
    input_audio = _token_count(prompt.get("audio_tokens"))
    output_audio = _token_count(completion.get("audio_tokens"))
    cached = _token_count(prompt.get("cached_tokens"))
    if (input_audio is not None and input_audio > input_tokens) or (
        output_audio is not None and output_audio > output_tokens
    ):
        return None
    billed_audio = input_tokens if input_audio is None else input_audio
    charge = (
        billed_audio * OPENAI_AUDIO_INPUT
        + (input_tokens - billed_audio) * OPENAI_TEXT_INPUT
        + output_tokens * OPENAI_TEXT_OUTPUT
        + (output_audio or 0) * (OPENAI_AUDIO_OUTPUT - OPENAI_TEXT_OUTPUT)
    )
    cost_basis = "provider_usage"
    if input_audio is None:
        cost_basis = "upper_bound_missing_audio_split"
    elif cached:
        cost_basis = "upper_bound_openai_cache"
    return Usage(
        charge,
        cost_basis,
        _identifier(payload.get("id")),
        _identifier(payload.get("model")),
        input_tokens,
        input_audio,
        cached,
        output_tokens,
        output_audio,
        _token_count(completion.get("reasoning_tokens")),
    )


def _gemini_usage(payload: dict, rates: tuple[int, int, int]) -> Usage | None:
    usage = _object(payload.get("usageMetadata"))
    input_tokens = _token_count(usage.get("promptTokenCount"))
    total_tokens = _token_count(usage.get("totalTokenCount"))
    if input_tokens is None or total_tokens is None:
        return None
    candidates = _token_count(usage.get("candidatesTokenCount", 0))
    thinking = _token_count(usage.get("thoughtsTokenCount", 0))
    cached = _token_count(usage.get("cachedContentTokenCount", 0))
    if (
        candidates is None
        or thinking is None
        or cached is None
        or cached > input_tokens
    ):
        return None
    output_tokens = candidates + thinking
    if input_tokens + output_tokens != total_tokens:
        return None
    details = usage.get("promptTokensDetails")
    audio_details = [
        _token_count(entry.get("tokenCount"))
        for entry in (details if isinstance(details, list) else [])
        if isinstance(entry, dict) and entry.get("modality") == "AUDIO"
    ]
    input_audio = (
        sum(audio_details) if audio_details and None not in audio_details else None
    )
    input_rate, cached_rate, output_rate = rates
    charge = (input_tokens - cached) * input_rate + cached * cached_rate
    charge += output_tokens * output_rate
    return Usage(
        charge,
        "provider_usage",
        _identifier(payload.get("responseId")),
        _identifier(payload.get("modelVersion")),
        input_tokens,
        input_audio,
        cached,
        output_tokens,
        None,
        thinking,
    )


def _output_limit(model: str, payload: dict) -> int:
    expected = model.split("/", 1)[1]
    if model == OPENAI:
        output_fields = [
            payload[k] for k in ("max_tokens", "max_completion_tokens") if k in payload
        ]
        if len(output_fields) != 1 or payload.get("model") != expected:
            raise RequestRejected(
                "OpenAI generation must use the pinned model and an output limit"
            )
        output = output_fields[0]
        if (
            payload.get("modalities") not in (None, ["text"])
            or payload.get("audio") is not None
            or payload.get("stream") not in (None, False)
            or payload.get("n") not in (None, 1)
            or payload.get("service_tier") != "default"
            or payload.get("store") not in (None, False)
            or payload.get("tools")
            or payload.get("functions")
            or payload.get("web_search_options")
            or payload.get("moderation")
            or payload.get("prompt_cache_options")
            or payload.get("prediction")
        ):
            raise RequestRejected(
                "OpenAI generation must use standard, single text output"
            )
    else:
        generation = _object(payload.get("generationConfig"))
        output = generation.get("maxOutputTokens")
        if (
            generation.get("responseModalities") not in (None, ["TEXT"])
            or generation.get("candidateCount") not in (None, 1)
            or payload.get("tools")
            or payload.get("cachedContent")
            or payload.get("systemInstruction")
            or payload.get("serviceTier") not in _STANDARD_GEMINI_TIERS
            or generation.get("serviceTier") not in _STANDARD_GEMINI_TIERS
            or generation.get("thinkingConfig") not in (None, {"includeThoughts": True})
        ):
            raise RequestRejected(
                "Gemini generation must use standard, single text output"
            )
        if model in THIRD_GEMINI_MODELS and (
            payload.get("continuationToken") is not None
            or generation.get("continuationToken") is not None
            or generation.get("automaticContinuation") not in (None, False)
        ):
            raise RequestRejected("Optional model must use one generation hop")
    if type(output) is not int or not 0 < output <= model_output_limit(model):
        raise RequestRejected("Generation request lacks a bounded output token limit")
    return output


def _reservation(
    model: str,
    output: int,
    audio: int,
    text: int,
    *,
    rates: tuple[int, int, int] | None = None,
) -> int:
    if model == OPENAI:
        return (
            audio * OPENAI_AUDIO_INPUT
            + text * OPENAI_TEXT_INPUT
            + output * OPENAI_TEXT_OUTPUT
        )
    input_rate, _, output_rate = rates or _gemini_rates(model)
    return (audio + text) * input_rate + output * output_rate


def _optional_model_unavailable(model: str, http_status: int, error: dict) -> bool:
    if http_status == 404 and error.get("code") == "model_not_found":
        return True
    expected_status = {403: "PERMISSION_DENIED", 404: "NOT_FOUND"}.get(http_status)
    if expected_status is None or error.get("status") != expected_status:
        return False
    message = error.get("message")
    if not isinstance(message, str):
        return False
    # GenerateContent uses the same status code for missing audio Files and
    # denied projects. Only classify responses that identify the requested model.
    model_name = model.split("/", 1)[1]
    names_model = bool(
        re.search(rf"(?<![\w-]){re.escape(model_name)}(?![\w-])", message)
    )
    reasons = (
        "not found",
        "not supported",
        "not available",
        "does not exist",
        "access to",
    )
    return names_model and any(reason in message.lower() for reason in reasons)


def _serves_requested_model(served, expected: str, *, optional: bool) -> bool:
    if not isinstance(served, str):
        return served is None and not optional
    if optional:
        # Prefer the stable ID. A numbered snapshot is still the same model;
        # an alternate named variant or preview is not a verified tariff.
        return bool(re.fullmatch(rf"{re.escape(expected)}(?:-\d+(?:-\d+)*)?", served))
    return served == expected or served.startswith(expected + "-")


class BudgetTransport(httpx.AsyncBaseTransport):
    """Meter physical HTTP dispatch so SDK retries and continuations also reserve spend."""

    def __init__(
        self,
        ledger: BudgetLedger,
        model: str,
        *,
        transport=None,
        profile: ReservationProfile | None = None,
    ):
        if model not in INPUT_LIMIT:
            raise ValueError("Model does not have verified pricing")
        self._ledger = ledger
        self._model = model
        self._service_model = model.split("/", 1)[1]
        self._profile = profile
        self._transport = (
            transport if transport is not None else httpx.AsyncHTTPTransport(retries=0)
        )

    async def handle_async_request(self, request):
        scope = _SCOPE.get()
        if scope is None:
            raise RequestRejected("Request is outside an active experiment sample")
        _require_model_scope(self._model, scope.run_id)
        if self._profile is None and scope.run_id != "pilot":
            raise RequestRejected("The run requires a verified request envelope")
        if self._model == OPENAI:
            generation = (
                _first_party(request, OPENAI_HOST)
                and request.method == "POST"
                and request.url.path == "/v1/chat/completions"
                and not request.url.query
            )
            if not generation:
                raise RequestRejected(
                    "Request does not match the pinned OpenAI endpoint"
                )
        else:
            generation = (
                _first_party(request, GOOGLE_HOST)
                and request.method == "POST"
                and request.url.path
                == f"/v1beta/models/{self._service_model}:generateContent"
                and not request.url.query
            )
            if not generation:
                validate_google_files_request(request, profile=self._profile)
                return await self._transport.handle_async_request(request)

        raw = await request.aread()
        if self._profile and len(raw) > self._profile.max_wire_bytes:
            raise RequestRejected("Request body exceeds the verified wire size")
        try:
            payload = json.loads(raw)
        except (ValueError, UnicodeError):
            raise RequestRejected(
                "Generation request does not contain valid JSON"
            ) from None
        if not isinstance(payload, dict):
            raise RequestRejected("Generation request must have an object body")
        output_limit = _output_limit(self._model, payload)
        if self._profile is not None:
            scope = _check_scope(self._profile)
            _validate_wire_input(self._model, payload, scope)
            audio_limit, text_limit = _input_bounds(
                scope.media_duration_seconds, len(scope.prompt_bytes)
            )
        else:
            audio_limit, text_limit = INPUT_LIMIT[self._model], 0
        rates = _gemini_rates(self._model) if self._model != OPENAI else None
        reservation = _reservation(
            self._model, output_limit, audio_limit, text_limit, rates=rates
        )
        call_id = self._ledger.reserve(self._model, reservation)
        start = monotonic()
        usage = None
        http_status = None
        bound_exceeded = False
        try:
            response = await self._transport.handle_async_request(request)
            http_status = response.status_code
            content = await response.aread()
            try:
                payload = _object(json.loads(content))
            except (ValueError, UnicodeError):
                payload = {}
            if 200 <= http_status < 300:
                if self._model == OPENAI and payload.get("service_tier") not in (
                    None,
                    "default",
                ):
                    bound_exceeded = True
                    raise BudgetStop("OpenAI returned an unexpected price tier")
                if self._model in THIRD_GEMINI_MODELS and any(
                    tier not in _STANDARD_GEMINI_TIERS
                    for tier in (
                        payload.get("serviceTier"),
                        _object(payload.get("usageMetadata")).get("serviceTier"),
                    )
                ):
                    bound_exceeded = True
                    raise BudgetStop(
                        "Optional Gemini model returned an unexpected price tier"
                    )
                expected = self._service_model
                served_model = payload.get(
                    "model" if self._model == OPENAI else "modelVersion"
                )
                if not _serves_requested_model(
                    served_model, expected, optional=self._model in THIRD_GEMINI_MODELS
                ):
                    bound_exceeded = True
                    raise BudgetStop(
                        "Provider returned a model outside the verified pricing family"
                    )
                usage = (
                    _openai_usage(payload)
                    if self._model == OPENAI
                    else _gemini_usage(payload, rates)
                )
                if usage is None:
                    raise BudgetStop(
                        "Provider response omitted usable billable token counts"
                    )
                usage = _sanitize_usage(usage, request)
                if (
                    self._profile is not None
                    and self._model == OPENAI
                    and usage.input_audio_tokens is None
                ):
                    # The previous conservative all-audio price can exceed a sized
                    # reservation even on an ordinary response. Without the split,
                    # keep the hold and stop before further dispatch.
                    usage = None
                    raise BudgetStop(
                        "OpenAI response omitted audio billing detail for the sized reservation"
                    )
                bound_exceeded = (
                    usage.input_tokens > audio_limit + text_limit
                    or usage.output_tokens > output_limit
                    or bool(usage.output_audio_tokens)
                )
                if self._profile is not None and usage.input_audio_tokens is not None:
                    bound_exceeded |= (
                        usage.input_audio_tokens > audio_limit
                        or usage.input_tokens - usage.input_audio_tokens > text_limit
                    )
            elif (
                self._model in _GEMINI_RATES
                and http_status in (400, 500)
                and _object(payload.get("error")).get("code") == http_status
            ):
                # The Gemini billing FAQ specifically excludes 400 and 500 errors.
                usage = Usage(
                    0,
                    "documented_no_charge",
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                )
            if self._model in THIRD_GEMINI_MODELS and _optional_model_unavailable(
                self._model, http_status, _object(payload.get("error"))
            ):
                raise OptionalModelUnavailable(self._model, http_status)
            if not 200 <= http_status < 300:
                raise ProviderRequestError(self._model, http_status)
            return response
        except httpx.RequestError:
            raise ProviderTransportError(self._model, http_status) from None
        finally:
            self._ledger.finish(
                call_id,
                usage,
                round(1000 * (monotonic() - start)),
                http_status,
                bound_exceeded=bound_exceeded,
            )

    async def aclose(self):
        await self._transport.aclose()
