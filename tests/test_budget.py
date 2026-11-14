import asyncio
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from intended_or_perceived.budget import (
    GEMINI,
    OPENAI,
    PROJECT_CAP_NANODOLLARS,
    BudgetLedger,
    BudgetStop,
    BudgetTransport,
    ProviderRequestError,
    RequestRejected,
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


def client_for(ledger, provider, handler):
    transport = BudgetTransport(
        ledger, provider, transport=httpx.MockTransport(handler)
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
            with pytest.raises(httpx.ReadTimeout):
                await client.post(OPENAI_URL, json=OPENAI_REQUEST)
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
    async with client_for(ledger, OPENAI, lambda _: httpx.Response(200, json=response)) as client:
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
    async with client_for(ledger, OPENAI, lambda _: httpx.Response(200, json=response)) as client:
        with budget_scope("p1-1", "clip-001"):
            await client.post(
                OPENAI_URL, json=OPENAI_REQUEST, headers={"Authorization": "Bearer sk-test-secret"}
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
            if http_status == 500:
                assert (
                    await client.post(GEMINI_URL, json=GEMINI_REQUEST)
                ).status_code == 500
            else:
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
