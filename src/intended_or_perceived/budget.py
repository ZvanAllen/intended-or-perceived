"""Reserve model spend before each HTTP generation and persist billable usage."""

import json
import re
import sqlite3
from contextlib import closing, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic

import httpx

OPENAI = "openai/gpt-audio-1.5"
GEMINI = "google/gemini-3.5-flash-lite"
PROJECT_CAP_NANODOLLARS = 25_000_000_000
MAX_OUTPUT_TOKENS = 256
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
INPUT_LIMIT = {OPENAI: 128_000, GEMINI: 1_048_576}

_SCOPE = ContextVar("budget_scope", default=None)
_IDENTIFIER = re.compile(r"[A-Za-z0-9_.:-]{1,120}")
_GOOGLE_FILE = re.compile(r"/v1beta/files/[A-Za-z0-9._-]+")
_GEMINI_PATH = "/v1beta/models/gemini-3.5-flash-lite:generateContent"


class BudgetStop(RuntimeError):
    """The spend cap or a pricing assumption prevents further model requests."""


class RequestRejected(RuntimeError):
    """A request was rejected before dispatch by the provider allowlist."""


class ProviderRequestError(RuntimeError):
    """A provider rejected billing, authentication or another request prerequisite."""

    def __init__(self, model: str, http_status: int):
        self.http_status = http_status
        super().__init__(f"{model} rejected the request (HTTP {http_status})")


@contextmanager
def budget_scope(condition: str, sample_id: str):
    """Attach only opaque experiment identifiers to the request ledger."""
    if not _IDENTIFIER.fullmatch(condition) or not _IDENTIFIER.fullmatch(sample_id):
        raise RequestRejected("Invalid experiment request identifiers")
    token = _SCOPE.set((condition, sample_id))
    try:
        yield
    finally:
        _SCOPE.reset(token)


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
    def _committed(connection) -> int:
        return connection.execute(
            "SELECT COALESCE(SUM(COALESCE(charged_nanodollars, reserved_nanodollars)), 0)"
            " FROM calls"
        ).fetchone()[0]

    def committed_nanodollars(self) -> int:
        with closing(self._connect()) as connection:
            return self._committed(connection)

    def records(self) -> list[dict]:
        with closing(self._connect()) as connection:
            connection.row_factory = sqlite3.Row
            return [
                dict(row)
                for row in connection.execute("SELECT * FROM calls ORDER BY id")
            ]

    def reserve(self, model: str, amount: int) -> int:
        scope = _SCOPE.get()
        if scope is None:
            raise RequestRejected("Request is outside an active experiment sample")
        if model not in INPUT_LIMIT or amount <= 0:
            raise RequestRejected("Invalid model budget reservation")
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
            row = connection.execute(
                "INSERT INTO calls (model, condition, sample_id, requested_at, status, "
                "reserved_nanodollars) VALUES (?, ?, ?, ?, 'reserved', ?)",
                (model, *scope, datetime.now(UTC).isoformat(), amount),
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


def validate_google_files_request(request) -> None:
    """Allow only the free first-party Files API upload, poll and deletion paths."""
    if _first_party(request, GOOGLE_HOST):
        path = request.url.path
        if request.method == "POST" and path == "/upload/v1beta/files":
            return
        if request.method in ("GET", "DELETE") and _GOOGLE_FILE.fullmatch(path):
            return
    raise RequestRejected(
        "Request does not match an allowed Google Files API operation"
    )


def _token_count(value) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _object(value) -> dict:
    return value if isinstance(value, dict) else {}


def _identifier(value) -> str | None:
    return value if isinstance(value, str) and _IDENTIFIER.fullmatch(value) else None


def _sanitize_usage(usage: Usage, request) -> Usage:
    authorization = request.headers.get("authorization", "")
    secrets = (authorization.removeprefix("Bearer "), request.headers.get("x-goog-api-key", ""))
    values = {
        field: None
        for field in ("served_model", "response_id")
        if (value := getattr(usage, field)) and any(secret and secret in value for secret in secrets)
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


def _gemini_usage(payload: dict) -> Usage | None:
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
    charge = (input_tokens - cached) * GEMINI_INPUT + cached * GEMINI_CACHED_INPUT
    charge += output_tokens * GEMINI_OUTPUT
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
            or payload.get("serviceTier") not in (None, "STANDARD")
            or generation.get("thinkingConfig") not in (None, {"includeThoughts": True})
        ):
            raise RequestRejected(
                "Gemini generation must use standard, single text output"
            )
    if type(output) is not int or not 0 < output <= MAX_OUTPUT_TOKENS:
        raise RequestRejected("Generation request lacks a bounded output token limit")
    return output


def _reservation(model: str, output: int) -> int:
    # Full provider input limit at the highest applicable rate. Release unused spend
    # only after receiving billable usage, including output/thinking tokens.
    if model == OPENAI:
        return INPUT_LIMIT[model] * OPENAI_AUDIO_INPUT + output * OPENAI_TEXT_OUTPUT
    input_rate, output_rate = GEMINI_INPUT, GEMINI_OUTPUT
    return INPUT_LIMIT[model] * input_rate + output * output_rate


class BudgetTransport(httpx.AsyncBaseTransport):
    """Meter physical HTTP dispatch so SDK retries and continuations also reserve spend."""

    def __init__(self, ledger: BudgetLedger, model: str, *, transport=None):
        if model not in INPUT_LIMIT:
            raise ValueError("Model does not have verified pricing")
        self._ledger = ledger
        self._model = model
        self._transport = (
            transport if transport is not None else httpx.AsyncHTTPTransport(retries=0)
        )

    async def handle_async_request(self, request):
        if _SCOPE.get() is None:
            raise RequestRejected("Request is outside an active experiment sample")
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
                and request.url.path == _GEMINI_PATH
                and not request.url.query
            )
            if not generation:
                validate_google_files_request(request)
                return await self._transport.handle_async_request(request)

        try:
            payload = json.loads(await request.aread())
        except (ValueError, UnicodeError):
            raise RequestRejected(
                "Generation request does not contain valid JSON"
            ) from None
        if not isinstance(payload, dict):
            raise RequestRejected("Generation request must have an object body")
        output_limit = _output_limit(self._model, payload)
        reservation = _reservation(self._model, output_limit)
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
                expected = self._model.split("/", 1)[1]
                served_model = payload.get("model" if self._model == OPENAI else "modelVersion")
                if served_model is not None and not (
                    isinstance(served_model, str)
                    and (served_model == expected or served_model.startswith(expected + "-"))
                ):
                    bound_exceeded = True
                    raise BudgetStop("Provider returned a model outside the verified pricing family")
                usage = (
                    _openai_usage(payload)
                    if self._model == OPENAI
                    else _gemini_usage(payload)
                )
                if usage is None:
                    raise BudgetStop(
                        "Provider response omitted usable billable token counts"
                    )
                usage = _sanitize_usage(usage, request)
                bound_exceeded = (
                    usage.input_tokens > INPUT_LIMIT[self._model]
                    or usage.output_tokens > output_limit
                    or bool(usage.output_audio_tokens)
                )
            elif (
                self._model == GEMINI
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
            if http_status in (400, 401, 402, 403, 404, 422):
                raise ProviderRequestError(self._model, http_status)
            return response
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
