import base64
import csv
import hashlib
import json
from pathlib import Path

import httpx
import pytest

from intended_or_perceived import evaluation
from intended_or_perceived.budget import GEMINI, GOOGLE_HOST, OPENAI, BudgetLedger
from intended_or_perceived.evaluation import (
    CONDITIONS,
    PilotStopped,
    make_model,
    run_pilot,
)
from intended_or_perceived.scoring import EMOTIONS

MEDIA = b"opaque mock audio data"
COMPLETION = '{"label":"Anger","confidence":90}'
DISTRIBUTION = json.dumps({label: 100 if label == "Anger" else 0 for label in EMOTIONS})
OPENAI_KEY = "sample-openai-secret"
GOOGLE_KEY = "sample-google-secret"


@pytest.fixture
def pilot_inputs(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", OPENAI_KEY)
    monkeypatch.setenv("GOOGLE_API_KEY", GOOGLE_KEY)
    monkeypatch.delenv("GOOGLE_GENAI_USE_VERTEXAI", raising=False)
    stimuli = tmp_path / "stimuli"
    stimuli.mkdir()
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    for name in ("P1", "P2", "P3"):
        (prompts / f"{name}.txt").write_text(name, encoding="utf-8")
    manifest = tmp_path / "manifest.csv"
    with manifest.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=[
                "sample_id",
                "filename",
                "intended_emotion",
                "voice_majority",
                "pilot",
                "media_sha256",
            ],
        )
        writer.writeheader()
        for i in range(24):
            opaque_id = f"clip{i + 1:03}"
            (stimuli / f"{opaque_id}.mp3").write_bytes(MEDIA)
            writer.writerow(
                {
                    "sample_id": opaque_id,
                    "filename": "1076_MTI_NEU_XX",
                    "intended_emotion": EMOTIONS[i // 4],
                    "voice_majority": "Anger:Sad",
                    "pilot": "1",
                    "media_sha256": hashlib.sha256(MEDIA).hexdigest(),
                }
            )
    return {
        "manifest_path": manifest,
        "stimuli_dir": stimuli,
        "prompts_dir": prompts,
        "run_dir": tmp_path / "pilot",
        "ledger": BudgetLedger(tmp_path / "budget.sqlite3"),
    }


def _openai_payload(text):
    return {
        "id": "chatcmpl-mock",
        "object": "chat.completion",
        "model": "gpt-audio-1.5",
        "created": 1780000000,
        "service_tier": "default",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
            "prompt_tokens_details": {"audio_tokens": 5},
        },
    }


def _gemini_payload(text):
    return {
        "modelVersion": "gemini-3.5-flash-lite",
        "responseId": "gemini-mock",
        "candidates": [
            {
                "content": {"role": "model", "parts": [{"text": text}]},
                "finishReason": "STOP",
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 10,
            "candidatesTokenCount": 5,
            "totalTokenCount": 15,
            "promptTokensDetails": [{"modality": "AUDIO", "tokenCount": 5}],
        },
    }


def test_real_adapters_remain_metered_opaque_and_resumable(pilot_inputs, monkeypatch):
    requests = []
    files = []
    failures = []
    original_error_code = evaluation._error_code

    def record_error(error):
        failures.append(error)
        return original_error_code(error)

    monkeypatch.setattr(evaluation, "_error_code", record_error)

    async def generation(request):
        payload = json.loads(await request.aread())
        raw = json.dumps(payload)
        for forbidden in (
            "1076_MTI_NEU_XX",
            "clip001",
            "Anger:Sad",
            OPENAI_KEY,
            GOOGLE_KEY,
        ):
            assert forbidden not in raw
        requests.append(str(request.url))
        if request.url.host != GOOGLE_HOST:
            assert payload["service_tier"] == "default"
            assert payload["max_tokens"] == 256
            assert payload["messages"][0]["content"][0]["input_audio"] == {
                "format": "mp3",
                "data": base64.b64encode(MEDIA).decode(),
            }
            assert all(key not in payload for key in ("temperature", "seed", "top_p"))
            text = payload["messages"][0]["content"][1]["text"]
            return httpx.Response(
                200, json=_openai_payload(DISTRIBUTION if text == "P3" else COMPLETION)
            )

        assert not payload.get("safetySettings")
        settings = payload["generationConfig"]
        assert settings["maxOutputTokens"] == 256
        assert all(
            key not in settings
            for key in ("temperature", "seed", "topP", "topK", "thinkingConfig")
        )
        parts = payload["contents"][0]["parts"]
        file_data = parts[0]["fileData"]
        assert file_data.get("mimeType", file_data.get("mime_type")) == "audio/mpeg", (
            file_data
        )
        assert file_data.get("fileUri", file_data.get("file_uri")) == (
            f"https://{GOOGLE_HOST}/v1beta/files/mock-opaque"
        )
        return httpx.Response(
            200,
            json=_gemini_payload(
                DISTRIBUTION if parts[1]["text"] == "P3" else COMPLETION
            ),
        )

    def upload(request):
        files.append(request.url.path)
        info = {
            "name": "files/mock-opaque",
            "state": "ACTIVE",
            "mimeType": "audio/mpeg",
            "uri": f"https://{GOOGLE_HOST}/v1beta/files/mock-opaque",
        }
        if request.method == "GET":
            assert request.url.path == "/v1beta/files/mock-opaque"
            return httpx.Response(200, json=info)
        assert request.url.path == "/upload/v1beta/files"
        if not request.url.query:
            metadata = json.loads(request.content)
            assert "displayName" not in metadata.get("file", {})
            assert "1076_MTI_NEU_XX" not in request.content.decode()
            return httpx.Response(
                200,
                headers={
                    "x-goog-upload-url": f"https://{GOOGLE_HOST}/upload/v1beta/files?upload_id=mock-opaque"
                },
            )
        assert request.content == MEDIA
        return httpx.Response(
            200, headers={"x-goog-upload-status": "final"}, json={"file": info}
        )

    def model_factory(model_id):
        return make_model(
            model_id,
            pilot_inputs["ledger"],
            transport=httpx.MockTransport(generation),
            files_transport=httpx.MockTransport(upload),
        )

    try:
        first = run_pilot(**pilot_inputs, model_factory=model_factory)
    except PilotStopped:
        if failures:
            raise failures[0]
        raise
    assert len(first) == len(requests) == len(pilot_inputs["ledger"].records()) == 240
    assert files
    assert {row["status"] for row in first} == {"valid"}
    assert {row["condition"] for row in first} == set(CONDITIONS)
    assert {row["model"] for row in first} == {OPENAI, GEMINI}
    assert run_pilot(**pilot_inputs, model_factory=model_factory) == first
    assert len(requests) == 240
    for path in pilot_inputs["run_dir"].rglob("*.json*"):
        recorded = path.read_text(encoding="utf-8")
        assert OPENAI_KEY not in recorded and GOOGLE_KEY not in recorded, path
        assert (
            MEDIA.decode() not in recorded
            and base64.b64encode(MEDIA).decode() not in recorded
        ), path


def test_systemic_provider_error_stops_before_second_dispatch(pilot_inputs):
    captures = []

    async def failure(request):
        captures.append(request.url)
        return httpx.Response(401, json={"error": {"message": OPENAI_KEY}})

    def model_factory(model_id):
        assert model_id == OPENAI
        return make_model(
            model_id, pilot_inputs["ledger"], transport=httpx.MockTransport(failure)
        )

    with pytest.raises(PilotStopped, match=r"stopped \(401\)"):
        run_pilot(**pilot_inputs, model_factory=model_factory)
    assert len(captures) == 1
    payload = (pilot_inputs["run_dir"] / "transcripts.jsonl").read_text(
        encoding="utf-8"
    )
    assert OPENAI_KEY not in payload
    row = json.loads(payload)
    assert row["status"] == "request_error"
    assert row["error"] == 401


def test_media_hash_mismatch_precedes_model_construction(pilot_inputs):
    changed: Path = pilot_inputs["stimuli_dir"] / "clip001.mp3"
    changed.write_bytes(b"changed")
    with pytest.raises(ValueError, match="Media hash mismatch"):
        run_pilot(
            **pilot_inputs, model_factory=lambda _: pytest.fail("Model constructed")
        )
