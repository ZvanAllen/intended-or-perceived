"""Run frozen audio evaluation cells through Inspect and persist each outcome."""

import asyncio
import base64
import csv
import hashlib
import io
import json
import math
import os
import re
import sqlite3
from contextlib import asynccontextmanager, closing, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Literal

import httpx
from google.genai.types import HttpOptions, HttpRetryOptions
from inspect_ai import Task, eval_async
from inspect_ai._util.registry import RegistryInfo, registry_tag
from inspect_ai.dataset import Sample
from inspect_ai.model import (
    ChatMessageUser,
    ContentAudio,
    ContentText,
    GenerateConfig,
    Model,
    ModelOutput,
    ModelUsage,
)
from inspect_ai.model._providers.google import GoogleGenAIAPI
from inspect_ai.model._providers.mockllm import MockLLM
from inspect_ai.model._providers.openai import OpenAIAPI
from inspect_ai.scorer import CORRECT, INCORRECT, NOANSWER, Score, Target, scorer
from inspect_ai.solver import Generate, TaskState, solver
from inspect_ai.util._display import display_type, init_display_type

from intended_or_perceived.budget import (
    GEMINI,
    GOOGLE_HOST,
    MAX_OUTPUT_TOKENS,
    OPENAI,
    OPENAI_HOST,
    BudgetLedger,
    BudgetStop,
    BudgetTransport,
    ProviderTransportError,
    RequestRejected,
    ReservationProfile,
    budget_scope,
    validate_google_files_request,
)
from intended_or_perceived.scoring import (
    EMOTIONS,
    ParsedOutput,
    label_matches,
    parse_output,
)

CONDITIONS = ("P1-R1", "P1-R2", "P1-R3", "P2", "P3")
MODEL_IDS = (OPENAI, GEMINI)
KEY_NAMES = ("OPENAI_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY")
_OPAQUE_ID = re.compile(r"clip[0-9]{3}")
_SYSTEMIC_HTTP = {401, 402, 403, 404}
_RETRY_BACKOFF_SECONDS = 1
_RUN = ContextVar("pilot_run")


class PilotStopped(RuntimeError):
    """The run needs to stop before more requests are dispatched."""


@dataclass(frozen=True)
class Condition:
    name: str
    family: str
    prompt_file: str


STUDY_CONDITIONS = (
    Condition("P1-R1", "P1", "P1.txt"),
    Condition("P1-R2", "P1", "P1.txt"),
    Condition("P1-R3", "P1", "P1.txt"),
    Condition("P2", "P2", "P2.txt"),
    Condition("P3", "P3", "P3-v2.txt"),
)
LEGACY_CONDITIONS = (*STUDY_CONDITIONS[:-1], Condition("P3", "P3", "P3.txt"))


@dataclass(frozen=True)
class PreparedStimulus:
    path: Path
    sha256: str
    duration_seconds: float | None = None


@dataclass(frozen=True)
class Stimulus:
    sample_id: str
    path: Path
    sha256: str
    intended: str
    perceived: str
    duration_seconds: float
    size_bytes: int
    format: Literal["mp3", "wav"]


@dataclass(frozen=True)
class Prompt:
    family: str
    filename: str
    text: str
    sha256: str


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _load_inputs(manifest, stimuli_dir, prompts_dir, subset, conditions, stimuli):
    if subset not in {"main", "pilot"}:
        raise ValueError("Expected the main or pilot subset")
    raw_manifest = manifest.read_bytes()
    clips = {}
    stimuli_root = stimuli_dir.resolve()
    for row in csv.DictReader(io.StringIO(raw_manifest.decode("utf-8-sig"))):
        if subset == "pilot" and row["pilot"] != "1":
            continue
        sample_id = row["sample_id"]
        if not _OPAQUE_ID.fullmatch(sample_id) or sample_id in clips:
            raise ValueError("Manifest requires unique opaque sample IDs")
        intended, perceived = row["intended_emotion"], row["voice_majority"]
        if intended not in EMOTIONS or any(
            label not in EMOTIONS for label in perceived.split(":")
        ):
            raise ValueError(f"Invalid references for {sample_id}")
        original_duration = float(row["duration_seconds"])
        prepared = (
            stimuli[sample_id]
            if stimuli is not None
            else PreparedStimulus(
                stimuli_root / Path(row.get("media_path") or f"{sample_id}.mp3").name,
                row["media_sha256"],
            )
        )
        path = prepared.path.resolve(strict=True)
        if (
            path.stem != sample_id
            or path.suffix not in {".mp3", ".wav"}
            or (stimuli is None and path.parent != stimuli_root)
        ):
            raise ValueError(f"Media path is not opaque for {sample_id}")
        duration = (
            prepared.duration_seconds
            if prepared.duration_seconds is not None
            else original_duration
        )
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError(f"Invalid media duration for {sample_id}")
        audio_format = "wav" if path.suffix == ".wav" else "mp3"
        stimulus = Stimulus(
            sample_id,
            path,
            prepared.sha256,
            intended,
            perceived,
            duration,
            path.stat().st_size,
            audio_format,
        )
        _verify_media(stimulus)
        clips[sample_id] = stimulus
    per_emotion = 4 if subset == "pilot" else 50
    if len(clips) != len(EMOTIONS) * per_emotion or any(
        sum(clip.intended == label for clip in clips.values()) != per_emotion
        for label in EMOTIONS
    ):
        raise ValueError(f"{subset} requires {per_emotion} clips per intended emotion")
    if stimuli is not None and clips.keys() != stimuli.keys():
        raise ValueError("Prepared stimuli must match all selected clip IDs")

    prompts = {}
    prompts_root = prompts_dir.resolve()
    for condition in conditions:
        if (
            not re.fullmatch(r"[A-Za-z][A-Za-z0-9-]{0,30}", condition.name)
            or condition.name in prompts
            or condition.family not in {"P1", "P2", "P3", "D1"}
        ):
            raise ValueError("Invalid or duplicate evaluation condition")
        path = (prompts_root / condition.prompt_file).resolve(strict=True)
        if not path.is_relative_to(prompts_root):
            raise ValueError("Prompt must be under the prompt directory")
        content = path.read_bytes()
        if not content.strip():
            raise ValueError(f"Empty prompt {condition.name}")
        prompts[condition.name] = Prompt(
            condition.family,
            path.relative_to(prompts_root).as_posix(),
            content.decode("utf-8"),
            _sha256(content),
        )
    if not prompts:
        raise ValueError("Select at least one condition")
    return _sha256(raw_manifest), clips, prompts


def _reservation_profile(manifest: Path, stimuli_dir: Path, clips, prompts):
    max_duration = max(clip.duration_seconds for clip in clips.values())
    max_bytes = max(clip.size_bytes for clip in clips.values())
    with manifest.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            path = (
                stimuli_dir
                / Path(row.get("media_path") or f"{row['sample_id']}.mp3").name
            )
            max_duration = max(max_duration, float(row["duration_seconds"]))
            max_bytes = max(max_bytes, path.stat().st_size)
    return ReservationProfile(
        max_duration,
        max_bytes,
        max(len(prompt.text.encode("utf-8")) for prompt in prompts.values()),
    )


def _verify_media(clip: Stimulus) -> bytes:
    content = clip.path.read_bytes()
    if len(content) != clip.size_bytes or _sha256(content) != clip.sha256:
        raise ValueError(f"Media hash mismatch for {clip.sample_id}")
    return content


def _atomic_text(path: Path, text: str) -> None:
    pending = path.with_suffix(path.suffix + ".tmp")
    with pending.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())
    pending.replace(path)


@contextmanager
def _run_lock(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(directory / "execution.sqlite3", timeout=0)) as lock:
        try:
            lock.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError:
            raise PilotStopped(
                "An evaluation is already running in this directory"
            ) from None
        yield


class PilotRun:
    """Persist completed samples individually and rebuild the transcript on exit."""

    def __init__(
        self,
        run_dir,
        manifest_hash,
        clips,
        prompts,
        ledger,
        *,
        run_id,
        subset,
        authorization,
        legacy,
    ):
        self.directory = run_dir
        self.manifest_hash = manifest_hash
        self.clips = clips
        self.prompts = prompts
        self.ledger = ledger
        self.run_id = run_id
        self.conditions = tuple(prompts)
        self.halt_reason = None
        self.failed_cells = 0
        self.secrets = tuple(
            value for name in KEY_NAMES if (value := os.environ.get(name))
        )
        self.rows = {}
        self.rows_dir = run_dir / "samples"
        self.rows_dir.mkdir(parents=True, exist_ok=True)
        provenance = {
            "manifest_sha256": self.manifest_hash,
            "prompt_sha256": {
                prompt.family: prompt.sha256 for prompt in prompts.values()
            },
            "conditions": list(self.conditions),
            "models": list(MODEL_IDS),
            "max_output_tokens": MAX_OUTPUT_TOKENS,
        }
        if not legacy:
            provenance.update(
                run_id=run_id,
                subset=subset,
                authorization=authorization,
                prompts={
                    name: {
                        "family": prompt.family,
                        "file": prompt.filename,
                        "sha256": prompt.sha256,
                    }
                    for name, prompt in prompts.items()
                },
                stimuli={
                    name: {
                        "sha256": clip.sha256,
                        "format": clip.format,
                        "bytes": clip.size_bytes,
                        "duration_seconds": clip.duration_seconds,
                    }
                    for name, clip in clips.items()
                },
            )
        checkpoint_path = run_dir / "inputs.json"
        if checkpoint_path.exists():
            if json.loads(checkpoint_path.read_text(encoding="utf-8")) != provenance:
                raise ValueError(
                    "Evaluation inputs differ from the previous invocation"
                )
        else:
            _atomic_text(checkpoint_path, json.dumps(provenance, indent=2) + "\n")
        for path in self.rows_dir.glob("*.json"):
            row = json.loads(path.read_text(encoding="utf-8"))
            model, condition, sample_id = self.key(row)
            if (
                model not in MODEL_IDS
                or condition not in self.conditions
                or sample_id not in clips
                or path != self.row_path(model, condition, sample_id)
                or row["manifest_sha256"] != self.manifest_hash
                or row["prompt_sha256"] != prompts[condition].sha256
                or row["media_sha256"] != clips[sample_id].sha256
                or row.get("run_id", "pilot") != run_id
            ):
                raise ValueError("Evaluation checkpoint differs from the frozen inputs")
            self.rows[self.key(row)] = row

    @staticmethod
    def key(row):
        return row["model"], row["condition"], row["sample_id"]

    def row_path(self, model, condition, sample_id):
        provider = model.split("/", 1)[0]
        return self.rows_dir / f"{provider}_{condition}_{sample_id}.json"

    def redact(self, value):
        if isinstance(value, str):
            for secret in self.secrets:
                value = value.replace(secret, "[redacted]")
        return value

    def commit(self, row):
        key = self.key(row)
        if key in self.rows:
            raise RuntimeError("Evaluation attempted to overwrite a completed sample")
        _atomic_text(self.row_path(*key), json.dumps(row, ensure_ascii=False) + "\n")
        self.rows[key] = row

    def export(self):
        rows = sorted(self.rows.values(), key=self.key)
        _atomic_text(
            self.directory / "transcripts.jsonl",
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        )
        return rows

    def row(self, model, condition, sample_id, started_at, latency_seconds, attempts):
        prompt = self.prompts[condition]
        return {
            "run_id": self.run_id,
            "model": model,
            "served_model": None,
            "condition": condition,
            "prompt": prompt.family,
            "prompt_file": prompt.filename,
            "sample_id": sample_id,
            "manifest_sha256": self.manifest_hash,
            "prompt_sha256": prompt.sha256,
            "media_sha256": self.clips[sample_id].sha256,
            "completion": None,
            "stop_reason": None,
            "response_id": None,
            "started_at": started_at,
            "finished_at": datetime.now(UTC).isoformat(),
            "latency_seconds": latency_seconds,
            "attempts": attempts,
            "retried": attempts > 1,
            "usage": None,
        }

    def recover_interrupted_calls(self):
        if self.ledger is None:
            return
        attempts_by_cell = {}
        for attempt in self.ledger.records(run_id=self.run_id):
            attempts_by_cell.setdefault(self.key(attempt), []).append(attempt)
        for (model, condition, sample_id), attempts in attempts_by_cell.items():
            if (
                (model, condition, sample_id) in self.rows
                or model not in MODEL_IDS
                or condition not in self.conditions
                or sample_id not in self.clips
            ):
                continue
            attempt = attempts[-1]
            latencies = [
                entry["latency_ms"]
                for entry in attempts
                if entry["latency_ms"] is not None
            ]
            row = self.row(
                model,
                condition,
                sample_id,
                attempts[0]["requested_at"],
                sum(latencies) / 1000 if latencies else None,
                len(attempts),
            )
            row.update(
                ParsedOutput("request_error").as_dict(),
                served_model=self.redact(attempt["served_model"]),
                response_id=self.redact(attempt["response_id"]),
                error="A previously reserved request has no recoverable completion",
            )
            self.commit(row)

    def failed(self, model, condition, sample_id, code):
        self.failed_cells += 1
        if code in _SYSTEMIC_HTTP or code in {"BudgetStop", "RequestRejected"}:
            self.halt_reason = f"{model} {condition} {sample_id} stopped ({code})"
        elif self.failed_cells == 3:
            self.halt_reason = (
                f"{model} {condition} {sample_id} stopped after three failed cells"
            )


def _error_code(error: BaseException):
    seen = set()
    while error is not None and id(error) not in seen:
        if isinstance(error, (BudgetStop, RequestRejected)):
            return type(error).__name__
        if isinstance(error, httpx.HTTPStatusError):
            return error.response.status_code
        if isinstance(error, ProviderTransportError):
            return error.http_status if error.http_status is not None else "no_response"
        for attr in ("http_status", "status_code", "code"):
            code = getattr(error, attr, None)
            if type(code) is int and 400 <= code <= 599:
                return code
        if isinstance(error, (httpx.TransportError, TimeoutError)):
            return "no_response"
        seen.add(id(error))
        error = error.__cause__ or error.__context__
    return None


def _retryable(code):
    return (
        code == "no_response" or code == 429 or (isinstance(code, int) and code >= 500)
    )


def _parse_completion(completion, family, stop_reason):
    if family != "D1":
        return parse_output(completion, family, stop_reason=stop_reason)
    if stop_reason in {"content_filter", "safety", "model_refusal", "refusal"}:
        return ParsedOutput("refusal")
    if stop_reason in {"length", "max_tokens", "model_length"}:
        return ParsedOutput("incomplete")
    return ParsedOutput("valid" if completion.strip() else "parse_error")


@solver
def pilot_generation(model_id: str, condition: str):
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        run = _RUN.get()
        if run.halt_reason:
            return state
        sample_id = str(state.sample_id)
        clip = run.clips[sample_id]
        prompt = run.prompts[condition]
        audio = state.messages[0].content[0]
        media_bytes = base64.b64decode(audio.audio.split(",", 1)[1], validate=True)
        started_at = datetime.now(UTC).isoformat()
        started = monotonic()
        for attempt in (1, 2):
            try:
                with budget_scope(
                    condition,
                    sample_id,
                    run_id=run.run_id,
                    media_duration_seconds=clip.duration_seconds,
                    media_bytes=media_bytes,
                    prompt_bytes=prompt.text.encode("utf-8"),
                ):
                    await generate(state, tool_calls="none", cache=False)
                break
            except Exception as error:  # noqa: BLE001 - provider errors can contain payloads
                code = _error_code(error)
                physical_attempts = (
                    [
                        record
                        for record in run.ledger.records(run_id=run.run_id)
                        if run.key(record) == (model_id, condition, sample_id)
                    ]
                    if run.ledger is not None
                    else []
                )
                if code is None and len(physical_attempts) == attempt:
                    latest = physical_attempts[-1]
                    if (
                        latest["http_status"] is None
                        and latest["status"] == "ambiguous"
                    ):
                        code = "no_response"
                if attempt == 1 and _retryable(code):
                    await asyncio.sleep(_RETRY_BACKOFF_SECONDS)
                    continue
                run.failed(model_id, condition, sample_id, code)
                dispatched = bool(physical_attempts) or code not in (
                    "BudgetStop",
                    "RequestRejected",
                )
                if dispatched:
                    row = run.row(
                        model_id,
                        condition,
                        sample_id,
                        started_at,
                        monotonic() - started,
                        attempt,
                    )
                    row.update(ParsedOutput("request_error").as_dict(), error=code)
                    run.commit(row)
                return state

        run.failed_cells = 0
        output: ModelOutput = state.output
        stop_reason = output.stop_reason if not output.empty else None
        row = run.row(
            model_id, condition, sample_id, started_at, monotonic() - started, attempt
        )
        row.update(
            served_model=run.redact(output.model),
            completion=run.redact(output.completion),
            stop_reason=stop_reason,
            response_id=run.redact(output.response_id),
            usage=output.usage.model_dump(mode="json")
            if output.usage is not None
            else None,
        )
        row.update(
            _parse_completion(row["completion"], row["prompt"], stop_reason).as_dict()
        )
        run.commit(row)
        return state

    return solve


@scorer(metrics=[])
def pilot_scoring(model_id: str, condition: str):
    async def score(state: TaskState, target: Target) -> Score:
        run = _RUN.get()
        row = run.rows.get((model_id, condition, str(state.sample_id)))
        if row is None:
            return Score(value=NOANSWER, metadata={"status": "not_dispatched"})
        if row["status"] != "valid":
            return Score(value=NOANSWER, reason=row["status"])
        if run.run_id.startswith("diagnostic-"):
            return Score(value="valid")
        if row["label"] is None:
            return Score(value=row["distribution"])
        perceived = run.clips[row["sample_id"]].perceived
        return Score(
            value=CORRECT if label_matches(row["label"], target.text) else INCORRECT,
            answer=row["label"],
            metadata={"perceived_match": label_matches(row["label"], perceived)},
        )

    return score


def _make_task(
    run: PilotRun, model_id: str, condition: str, pending: list[Stimulus]
) -> Task:
    prompt = run.prompts[condition]
    dataset = []
    for clip in pending:
        media = base64.b64encode(_verify_media(clip)).decode("ascii")
        mime = "audio/wav" if clip.format == "wav" else "audio/mpeg"
        dataset.append(
            Sample(
                id=clip.sample_id,
                input=[
                    ChatMessageUser(
                        content=[
                            ContentAudio(
                                audio=f"data:{mime};base64,{media}", format=clip.format
                            ),
                            ContentText(text=prompt.text),
                        ]
                    )
                ],
                target=clip.intended,
            )
        )
    return Task(
        name=condition,
        dataset=dataset,
        config=GenerateConfig(
            max_tokens=MAX_OUTPUT_TOKENS,
            max_retries=0,
            timeout=120,
            max_connections=1,
            cache=False,
        ),
        solver=pilot_generation(model_id, condition),
        scorer=pilot_scoring(model_id, condition),
    )


class _MeteredGemini(GoogleGenAIAPI):
    def __init__(self, api_key, client, async_client):
        super().__init__(
            model_name=GEMINI.split("/", 1)[1],
            base_url=f"https://{GOOGLE_HOST}",
            api_key=api_key,
            api_version="v1beta",
            streaming=False,
            use_adc=False,
        )
        if self.is_vertex():
            raise PilotStopped("Pilot requires the Gemini Developer API")
        self.safety_settings = []
        self._pilot_sync = client
        self._pilot_async = async_client

    def _http_options(self, config=None) -> HttpOptions:
        options = super()._http_options(config)
        options.httpx_client = self._pilot_sync
        options.httpx_async_client = self._pilot_async
        options.retry_options = HttpRetryOptions(attempts=1)
        return options

    def chat_thinking_config(self, config: GenerateConfig) -> None:
        return None

    async def _generate_with_continuations(self, client, contents, parameters, chain):
        # The pinned SDK's public generate_content and the Inspect adapter can
        # both follow continuation tokens. Each cell attempt must make one request.
        response = await client.aio.models._generate_content(
            model=self.service_model_name(),
            contents=contents,
            config=parameters,
        )
        chain.add(response)
        return [response]


@asynccontextmanager
async def make_model(
    model_id: str,
    ledger: BudgetLedger,
    *,
    profile=None,
    transport=None,
    files_transport=None,
):
    guarded = BudgetTransport(ledger, model_id, transport=transport, profile=profile)
    async with httpx.AsyncClient(
        transport=guarded, trust_env=False, timeout=120
    ) as client:
        if model_id == OPENAI:
            api = OpenAIAPI(
                model_id.split("/", 1)[1],
                base_url=f"https://{OPENAI_HOST}/v1",
                api_key=os.environ["OPENAI_API_KEY"],
                responses_api=False,
                streaming=False,
                service_tier="default",
                http_client=client,
                max_retries=0,
            )
            registry_tag(
                lambda: None, api, RegistryInfo(type="modelapi", name="openai")
            )
            model = Model(api, GenerateConfig())
            api.qualified_model_name = model_id
            async with model:
                yield model
        elif model_id == GEMINI:
            key = os.environ.get("GOOGLE_API_KEY") or os.environ["GEMINI_API_KEY"]
            with httpx.Client(
                transport=files_transport,
                trust_env=False,
                timeout=45,
                event_hooks={
                    "request": [
                        lambda request: validate_google_files_request(
                            request, profile=profile
                        )
                    ]
                },
            ) as files:
                api = _MeteredGemini(key, files, client)
                registry_tag(
                    lambda: None,
                    api,
                    RegistryInfo(type="modelapi", name="google"),
                )
                model = Model(api, GenerateConfig())
                api.qualified_model_name = model_id
                async with model:
                    yield model
        else:
            raise ValueError("Unsupported pilot model")


@asynccontextmanager
async def mock_model_factory(model_id: str):
    def complete(*_args):
        run = _RUN.get()
        family = run.prompts[_ACTIVE_CONDITION.get()].family
        result = {
            "D1": "Example mock transcription",
            "P3": json.dumps(
                {label: 100 if label == "Neutral" else 0 for label in EMOTIONS}
            ),
        }.get(family, '{"label":"Neutral","confidence":50}')
        output = ModelOutput.from_content("mockllm", result)
        output.usage = ModelUsage(input_tokens=1, output_tokens=1, total_tokens=2)
        return output

    api = MockLLM(model_id.split("/", 1)[0], custom_outputs=complete)
    registry_tag(lambda: None, api, RegistryInfo(type="modelapi", name="mockllm"))
    async with Model(api, GenerateConfig()) as model:
        yield model


_ACTIVE_CONDITION = ContextVar("active_condition")


async def _run_conditions(run, model_factory):
    logs_dir = (run.directory / "inspect").as_posix()
    for model_id in MODEL_IDS:
        if all((model_id, c, s) in run.rows for c in run.conditions for s in run.clips):
            continue
        async with model_factory(model_id) as model:
            for condition in run.conditions:
                pending = [
                    clip
                    for sid, clip in run.clips.items()
                    if (model_id, condition, sid) not in run.rows
                ]
                if not pending:
                    continue
                task = _make_task(run, model_id, condition, pending)
                active_condition = _ACTIVE_CONDITION.set(condition)
                try:
                    logs = await eval_async(
                        task,
                        model=model,
                            score=run.subset != "main",
                        log_dir=logs_dir,
                        log_format="json",
                        log_images=False,
                        log_model_api=False,
                        log_realtime=False,
                        log_samples=False,
                        checkpoint=False,
                        max_samples=1,
                        retry_on_error=0,
                        log_level="error",
                        log_level_transcript="error",
                    )
                finally:
                    _ACTIVE_CONDITION.reset(active_condition)
                run.export()
                if run.halt_reason:
                    raise PilotStopped(run.halt_reason)
                if (
                    len(logs) != 1
                    or logs[0].status != "success"
                    or any(
                        (model_id, condition, clip.sample_id) not in run.rows
                        for clip in pending
                    )
                ):
                    raise PilotStopped(
                        f"Inspect did not complete {model_id} {condition}"
                    )
                print(
                    f"Completed {model_id} {condition} ({len(pending)} clips)",
                    flush=True,
                )


def run_pilot(
    *,
    manifest_path: Path,
    stimuli_dir: Path,
    prompts_dir: Path,
    run_dir: Path,
    ledger: BudgetLedger | None = None,
    model_factory=None,
) -> list[dict]:
    """Resume the original Gate 1 pilot, including its original P3 prompt."""
    return run_evaluation(
        manifest_path=manifest_path,
        stimuli_dir=stimuli_dir,
        prompts_dir=prompts_dir,
        run_dir=run_dir,
        run_id="pilot",
        subset="pilot",
        conditions=LEGACY_CONDITIONS,
        ledger=ledger,
        model_factory=model_factory,
        authorization="Original Gate 1 pilot",
    )


def run_evaluation(
    *,
    manifest_path: Path,
    stimuli_dir: Path,
    prompts_dir: Path,
    run_dir: Path,
    run_id: str,
    subset: Literal["pilot", "main"],
    authorization: str,
    conditions: tuple[Condition, ...] = STUDY_CONDITIONS,
    ledger: BudgetLedger | None = None,
    model_factory=None,
    stimuli: dict[str, PreparedStimulus] | None = None,
    reservation_profile: ReservationProfile | None = None,
    main_approved: bool = False,
) -> list[dict]:
    """Run a frozen subset and condition set, or resume it from private checkpoints."""
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,39}", run_id) or not authorization.strip():
        raise ValueError("A run ID and authorization provenance are required")
    if run_id == "pilot" and (
        subset != "pilot" or conditions != LEGACY_CONDITIONS or stimuli
    ):
        raise ValueError("The pilot run ID is reserved for the original Gate 1 inputs")
    if subset == "main" and ledger is not None and not main_approved:
        raise PilotStopped("The main study requires explicit dispatch approval")
    manifest_hash, clips, prompts = _load_inputs(
        manifest_path,
        stimuli_dir,
        prompts_dir,
        subset,
        conditions,
        stimuli,
    )
    if reservation_profile is None and model_factory is None:
        reservation_profile = _reservation_profile(
            manifest_path, stimuli_dir, clips, prompts
        )
    if model_factory is None:
        if ledger is None:
            raise ValueError("A durable budget ledger is required for live evaluation")

        def model_factory(model_id):
            return make_model(model_id, ledger, profile=reservation_profile)

    with _run_lock(run_dir.resolve()):
        run = PilotRun(
            run_dir.resolve(),
            manifest_hash,
            clips,
            prompts,
            ledger,
            run_id=run_id,
            subset=subset,
            authorization=authorization,
            legacy=run_id == "pilot",
        )
        run.recover_interrupted_calls()
        token = _RUN.set(run)
        previous_display = display_type()
        init_display_type("none")
        try:
            asyncio.run(_run_conditions(run, model_factory))
        finally:
            init_display_type(previous_display)
            _RUN.reset(token)
            rows = run.export()
    return rows
