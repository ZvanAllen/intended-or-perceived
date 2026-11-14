import asyncio
import base64
import io
import sqlite3
import wave
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from intended_or_perceived.budget import (
    DIAGNOSTIC_CAP_NANODOLLARS,
    GEMINI,
    OPENAI,
    PROJECT_CAP_NANODOLLARS,
    BudgetLedger,
    BudgetStop,
    BudgetTransport,
    ProviderRequestError,
    ProviderTransportError,
    RequestRejected,
    ReservationProfile,
    Usage,
    budget_scope,
    validate_google_files_request,
)

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent"
OPENAI_REQUEST = {
    "model": "gpt-audio-1.5",
    "max_tokens": 256,
    "service_tier": "default",
}
GEMINI_REQUEST = {"generationConfig": {"maxOutputTokens": 256}}
OPENAI_RESPONSE = {
    "id": "chatcmpl-offline",
    "model": "gpt-audio-1.5",
    "service_tier": "default",
    "usage": {
        "prompt_tokens": 50,
        "completion_tokens": 25,
        "prompt_tokens_details": {"audio_tokens": 30, "cached_tokens": 0},
        "completion_tokens_details": {"audio_tokens": 0, "reasoning_tokens": 0},
    },
}
GEMINI_RESPONSE = {
    "modelVersion": "gemini-3.5-flash-lite",
    "responseId": "gemini-offline",
    "usageMetadata": {
        "promptTokenCount": 100,
        "candidatesTokenCount": 30,
        "thoughtsTokenCount": 10,
        "cachedContentTokenCount": 5,
        "promptTokensDetails": [{"modality": "AUDIO", "tokenCount": 72}],
        "totalTokenCount": 140,
    },
}


def client_for(ledger, provider, handler, profile=None):
    transport = BudgetTransport(
        ledger, provider, transport=httpx.MockTransport(handler), profile=profile
    )
    return httpx.AsyncClient(transport=transport, trust_env=False)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "model,url,request_data,response_data,expected",
    [
        (OPENAI, OPENAI_URL, OPENAI_REQUEST, OPENAI_RESPONSE, 1_260_000),
        (GEMINI, GEMINI_URL, GEMINI_REQUEST, GEMINI_RESPONSE, 128_650),
    ],
)
async def test_reservation_precedes_send_and_settles_exact_usage(
    tmp_path, model, url, request_data, response_data, expected
):
    path = tmp_path / "api-budget.db"
    ledger = BudgetLedger(path)

    def handler(request):
        during_send = ledger.records()[0]
        assert during_send["status"] == "reserved"
        assert during_send["reserved_nanodollars"] > expected
        return httpx.Response(200, json=response_data)

    async with client_for(ledger, model, handler) as client:
        with budget_scope("p1-1", "clip-001"):
            response = await client.post(url, json=request_data)
    assert response.json() == response_data
    reopened = BudgetLedger(path)
    row = reopened.records()[0]
    assert row["model"] == model
    assert row["sample_id"] == "clip-001"
    assert row["condition"] == "p1-1"
    assert row["status"] == "settled"
    assert row["charged_nanodollars"] == expected == reopened.committed_nanodollars()
    assert row["served_model"] == model.split("/", 1)[1]
    assert row["input_audio_tokens"] == {OPENAI: 30, GEMINI: 72}[model]
    assert row["thinking_tokens"] == {OPENAI: 0, GEMINI: 10}[model]
    assert row["http_status"] == 200
    assert row["latency_ms"] >= 0


def test_open_reservations_survive_restart_and_share_cap_across_models(tmp_path):
    path = tmp_path / "api-budget.db"
    ledger = BudgetLedger(path, cap_nanodollars=100)
    with budget_scope("p1-1", "clip-001"):
        ledger.reserve(OPENAI, 61)
    reopened = BudgetLedger(path, cap_nanodollars=100)
    assert reopened.committed_nanodollars() == 61
    with budget_scope("p1-1", "clip-002"), pytest.raises(BudgetStop):
        reopened.reserve(GEMINI, 40)
    with pytest.raises(BudgetStop, match="durable project cap"):
        BudgetLedger(path, cap_nanodollars=101)
    with pytest.raises(ValueError):
        BudgetLedger(
            tmp_path / "invalid.db", cap_nanodollars=PROJECT_CAP_NANODOLLARS + 1
        )


def test_parallel_process_style_reservations_are_atomic(tmp_path):
    path = tmp_path / "api-budget.db"
    BudgetLedger(path, cap_nanodollars=120)

    def reserve(index):
        ledger = BudgetLedger(path, cap_nanodollars=120)
        with budget_scope("p1-1", f"clip-{index}"):
            try:
                return ledger.reserve(OPENAI, 60)
            except BudgetStop:
                return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(reserve, range(8)))
    assert sum(outcome is not None for outcome in outcomes) == 2
    assert BudgetLedger(path, cap_nanodollars=120).committed_nanodollars() == 120


@pytest.mark.asyncio
async def test_missing_usage_stops_and_preserves_full_hold(tmp_path):
    ledger = BudgetLedger(tmp_path / "api-budget.db")
    async with client_for(
        ledger, OPENAI, lambda _: httpx.Response(200, json={})
    ) as client:
        with (
            budget_scope("p1-1", "clip-001"),
            pytest.raises(BudgetStop, match="token counts"),
        ):
            await client.post(OPENAI_URL, json=OPENAI_REQUEST)
    row = ledger.records()[0]
    assert row["status"] == "ambiguous"
    assert row["charged_nanodollars"] is None
    assert ledger.committed_nanodollars() == row["reserved_nanodollars"]


@pytest.mark.asyncio
async def test_each_retry_dispatch_requires_reservation_and_timeout_holds_it(tmp_path):
    ledger = BudgetLedger(tmp_path / "api-budget.db", cap_nanodollars=5_000_000_000)
    sent = 0

    def handler(request):
        nonlocal sent
        sent += 1
        raise httpx.ReadTimeout("mock timeout", request=request)

    async with client_for(ledger, OPENAI, handler) as client:
        with budget_scope("p1-1", "clip-001"):
            with pytest.raises(ProviderTransportError) as error:
                await client.post(OPENAI_URL, json=OPENAI_REQUEST)
            assert error.value.http_status is None
            with pytest.raises(BudgetStop, match="next request reservation"):
                await client.post(OPENAI_URL, json=OPENAI_REQUEST)
    assert sent == 1
    assert [row["status"] for row in ledger.records()] == ["ambiguous"]


@pytest.mark.asyncio
async def test_output_limit_breach_durably_blocks_further_calls(tmp_path):
    ledger = BudgetLedger(tmp_path / "api-budget.db")
    response = {
        **OPENAI_RESPONSE,
        "usage": {"prompt_tokens": 50, "completion_tokens": 257},
    }
    async with client_for(
        ledger, OPENAI, lambda _: httpx.Response(200, json=response)
    ) as client:
        with budget_scope("p1-1", "clip-001"):
            with pytest.raises(BudgetStop, match="exceeded the request reservation"):
                await client.post(OPENAI_URL, json=OPENAI_REQUEST)
            with pytest.raises(BudgetStop, match="prior response"):
                await client.post(OPENAI_URL, json=OPENAI_REQUEST)
    assert [row["status"] for row in ledger.records()] == ["limit_exceeded"]


@pytest.mark.asyncio
async def test_unverified_serving_tier_locks_ledger_and_preserves_hold(tmp_path):
    ledger = BudgetLedger(tmp_path / "api-budget.db")
    response = {**OPENAI_RESPONSE, "service_tier": "priority"}
    async with client_for(
        ledger, OPENAI, lambda _: httpx.Response(200, json=response)
    ) as client:
        with budget_scope("p1-1", "clip-001"):
            with pytest.raises(BudgetStop, match="unexpected price tier"):
                await client.post(OPENAI_URL, json=OPENAI_REQUEST)
            with pytest.raises(BudgetStop, match="prior response"):
                await client.post(OPENAI_URL, json=OPENAI_REQUEST)
    row = ledger.records()[0]
    assert row["status"] == "limit_exceeded"
    assert row["charged_nanodollars"] is None


@pytest.mark.asyncio
async def test_response_metadata_cannot_write_an_echoed_api_key(tmp_path):
    ledger = BudgetLedger(tmp_path / "api-budget.db")
    response = {**OPENAI_RESPONSE, "id": "chatcmpl-sk-test-secret"}
    async with client_for(
        ledger, OPENAI, lambda _: httpx.Response(200, json=response)
    ) as client:
        with budget_scope("p1-1", "clip-001"):
            await client.post(
                OPENAI_URL,
                json=OPENAI_REQUEST,
                headers={"Authorization": "Bearer sk-test-secret"},
            )
    assert ledger.records()[0]["response_id"] is None
    assert b"sk-test-secret" not in ledger.path.read_bytes()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "http_status,billable", [(400, False), (500, False), (402, True)]
)
async def test_documented_gemini_no_charge_and_sanitized_account_error(
    tmp_path, http_status, billable
):
    ledger = BudgetLedger(tmp_path / "api-budget.db")

    def handler(_):
        return httpx.Response(
            http_status, json={"error": {"code": http_status, "message": "secret"}}
        )

    async with client_for(ledger, GEMINI, handler) as client:
        with budget_scope("p1-1", "clip-001"):
            with pytest.raises(
                ProviderRequestError, match=f"HTTP {http_status}"
            ) as error:
                await client.post(GEMINI_URL, json=GEMINI_REQUEST)
            assert "secret" not in str(error.value)
    row = ledger.records()[0]
    assert row["charged_nanodollars"] == (None if billable else 0)
    assert row["status"] == ("ambiguous" if billable else "settled")
    assert "secret" not in str(row)


@pytest.mark.asyncio
async def test_nonstandard_unbounded_or_unscoped_generation_fails_before_send(tmp_path):
    ledger = BudgetLedger(tmp_path / "api-budget.db")

    def handler(_):
        pytest.fail("unexpected dispatch")

    async with client_for(ledger, OPENAI, handler) as client:
        with pytest.raises(RequestRejected, match="active experiment sample"):
            await client.post(OPENAI_URL, json=OPENAI_REQUEST)
        with budget_scope("p1-1", "clip-001"):
            for patch in (
                {"service_tier": "auto"},
                {"max_tokens": 257},
                {"stream": True},
            ):
                with pytest.raises(RequestRejected):
                    await client.post(OPENAI_URL, json={**OPENAI_REQUEST, **patch})
            with pytest.raises(RequestRejected):
                await client.post(
                    OPENAI_URL.replace("api.openai.com", "localhost"),
                    json=OPENAI_REQUEST,
                )
    assert ledger.records() == []


def test_google_files_allowlist_accepts_only_first_party_paths():
    base = "https://generativelanguage.googleapis.com"
    validate_google_files_request(
        httpx.Request("POST", f"{base}/upload/v1beta/files?upload_id=mock")
    )
    validate_google_files_request(httpx.Request("GET", f"{base}/v1beta/files/sample"))
    for url in (
        f"{base}/v1beta/files",
        f"{base}/v1beta/files/sample:download",
        GEMINI_URL,
    ):
        with pytest.raises(RequestRejected):
            validate_google_files_request(httpx.Request("GET", url))


def test_diagnostic_cap_survives_restarts_and_excludes_legacy_hold(tmp_path):
    path = tmp_path / "api-budget.db"
    ledger = BudgetLedger(path)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO calls (id, model, condition, sample_id, requested_at, status, "
            "reserved_nanodollars) VALUES (69, ?, 'P1-R3', 'clip259', 'legacy', 'ambiguous', ?)",
            (OPENAI, 4_098_560_000),
        )
    original = ledger.records()[0]
    with budget_scope("D1", "clip001", run_id="diagnostic-d1"):
        call1 = ledger.reserve(OPENAI, 300_000_000)
        ledger.finish(call1, None, 16, None)
    with budget_scope("P1", "clip001", run_id="diagnostic-gain"):
        call2 = ledger.reserve(GEMINI, 200_000_000)
        ledger.finish(
            call2,
            Usage(100_000_000, "provider_usage", None, None, 1, 0, 0, 0, 0, 0),
            5,
            200,
        )
    reopened = BudgetLedger(path)
    with budget_scope("P3", "clip001", run_id="diagnostic-p3-v2"):
        with pytest.raises(BudgetStop, match=r"US\$0.50 diagnostic"):
            reopened.reserve(OPENAI, 100_000_001)
        reopened.reserve(OPENAI, 100_000_000)
    assert reopened.committed_nanodollars(diagnostic=True) == DIAGNOSTIC_CAP_NANODOLLARS
    assert reopened.committed_nanodollars() == 4_598_560_000
    assert reopened.records(run_id="pilot") == [original]


def _wav(sample_count=8_000):
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setparams((1, 2, 8_000, sample_count, "NONE", "not compressed"))
        audio.writeframes(b"\x00\x00" * sample_count)
    return output.getvalue()


def _openai_audio_payload(media, prompt="A clip", media_format="wav"):
    return {
        **OPENAI_REQUEST,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_audio",
                        "input_audio": {
                            "format": media_format,
                            "data": base64.b64encode(media).decode(),
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    }


@pytest.mark.asyncio
async def test_sized_reservation_rejects_oversize_or_changed_body(tmp_path):
    ledger = BudgetLedger(tmp_path / "api-budget.db")
    media = _wav()
    profile = ReservationProfile(5, len(media), 694)
    mock = lambda _: httpx.Response(200, json=OPENAI_RESPONSE)
    async with client_for(ledger, OPENAI, mock, profile) as client:
        with budget_scope(
            "P1",
            "clip001",
            run_id="diagnostic-gain",
            media_duration_seconds=1,
            media_bytes=media,
            prompt_bytes=b"A clip",
        ):
            payload = _openai_audio_payload(media)
            response = await client.post(OPENAI_URL, json=payload)
            assert response.status_code == 200
            with pytest.raises(RequestRejected, match="wire size"):
                await client.post(
                    OPENAI_URL, json={**payload, "unused": "x" * profile.max_wire_bytes}
                )
            with pytest.raises(RequestRejected, match="verified prompt"):
                await client.post(
                    OPENAI_URL, json=_openai_audio_payload(media, prompt="Changed")
                )
            with pytest.raises(RequestRejected, match="verified stimulus"):
                await client.post(OPENAI_URL, json=_openai_audio_payload(media + b"x"))
    (row,) = ledger.records()
    # ceil((1 + .1) * 64) + 16 = 87 audio tokens, 6 + 128 text tokens.
    assert row["reserved_nanodollars"] == 87 * 32_000 + 134 * 2_500 + 256 * 10_000
    assert row["reserved_nanodollars"] < profile.max_reservation_nanodollars(OPENAI)


@pytest.mark.asyncio
async def test_diagnostic_requires_profile_and_reports_usage_envelope_breach(tmp_path):
    ledger = BudgetLedger(tmp_path / "api-budget.db")
    media = _wav()
    response = {
        **OPENAI_RESPONSE,
        "usage": {
            "prompt_tokens": 90,
            "completion_tokens": 25,
            "prompt_tokens_details": {"audio_tokens": 90},
        },
    }
    with budget_scope(
        "P1",
        "clip001",
        run_id="diagnostic-gain",
        media_duration_seconds=1,
        media_bytes=media,
        prompt_bytes=b"A clip",
    ):
        async with client_for(
            ledger, OPENAI, lambda _: pytest.fail("unexpected dispatch")
        ) as client:
            with pytest.raises(
                RequestRejected, match="requires a verified request envelope"
            ):
                await client.post(OPENAI_URL, json=_openai_audio_payload(media))
        async with client_for(
            ledger,
            OPENAI,
            lambda _: httpx.Response(200, json=response),
            ReservationProfile(1, len(media), len(b"A clip")),
        ) as client:
            with pytest.raises(BudgetStop, match="exceeded the request reservation"):
                await client.post(OPENAI_URL, json=_openai_audio_payload(media))
    assert ledger.records()[0]["status"] == "limit_exceeded"


def test_google_files_upload_is_bound_to_exact_scoped_media():
    url = "https://generativelanguage.googleapis.com/upload/v1beta/files"
    media = _wav()
    profile = ReservationProfile(1, len(media), len(b"P1"))
    with budget_scope(
        "P1",
        "clip001",
        run_id="diagnostic-gain",
        media_duration_seconds=1,
        media_bytes=media,
        prompt_bytes=b"P1",
    ):
        initiate = httpx.Request(
            "POST",
            url,
            headers={
                "X-Goog-Upload-Command": "start",
                "X-Goog-Upload-Header-Content-Length": str(len(media)),
            },
            json={},
        )
        validate_google_files_request(initiate, profile=profile)
        finalize = httpx.Request(
            "POST",
            url + "?upload_id=mock",
            headers={
                "X-Goog-Upload-Command": "upload, finalize",
                "X-Goog-Upload-Offset": "0",
            },
            content=media,
        )
        validate_google_files_request(finalize, profile=profile)
        bad = httpx.Request(
            "POST",
            url + "?upload_id=mock",
            headers=finalize.headers,
            content=media + b"x",
        )
        with pytest.raises(RequestRejected, match="verified stimulus"):
            validate_google_files_request(bad, profile=profile)


@pytest.mark.asyncio
async def test_budget_scope_isolated_between_async_samples(tmp_path):
    ledger = BudgetLedger(tmp_path / "api-budget.db")

    async def handler(_):
        await asyncio.sleep(0)
        return httpx.Response(200, json=GEMINI_RESPONSE)

    async with client_for(ledger, GEMINI, handler) as client:

        async def run(condition, sample_id):
            with budget_scope(condition, sample_id):
                await client.post(GEMINI_URL, json=GEMINI_REQUEST)

        await asyncio.gather(run("p1-1", "clip-001"), run("p1-2", "clip-002"))
    assert [(row["condition"], row["sample_id"]) for row in ledger.records()] == [
        ("p1-1", "clip-001"),
        ("p1-2", "clip-002"),
    ]
