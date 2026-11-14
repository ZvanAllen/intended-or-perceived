"""Build and run the five audio-only Inspect conditions on the frozen pilot."""

import asyncio
import base64
import csv
import hashlib
import io
import json
import os
import re
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic

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
)
from inspect_ai.model._providers.google import GoogleGenAIAPI
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
    RequestRejected,
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
_PILOT_SIZE = 24
_OPAQUE_ID = re.compile(r"clip[0-9]{3}")
_SYSTEMIC_HTTP = {400, 401, 402, 403, 404, 422, 429}
_RUN = ContextVar("pilot_run")


class PilotStopped(RuntimeError):
    """The pilot needs to stop before more requests are dispatched."""


@dataclass(frozen=True)
class Stimulus:
    sample_id: str
    path: Path
    sha256: str
    intended: str
    perceived: str


@dataclass(frozen=True)
class Prompt:
    name: str
    text: str
    sha256: str


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _load_inputs(manifest: Path, stimuli_dir: Path, prompts_dir: Path):
    raw_manifest = manifest.read_bytes()
    clips = {}
    for row in csv.DictReader(io.StringIO(raw_manifest.decode("utf-8-sig"))):
        if row["pilot"] != "1":
            continue
        sample_id = row["sample_id"]
        if not _OPAQUE_ID.fullmatch(sample_id) or sample_id in clips:
            raise ValueError("Pilot manifest requires unique opaque sample IDs")
        intended, perceived = row["intended_emotion"], row["voice_majority"]
        if intended not in EMOTIONS or any(
            label not in EMOTIONS for label in perceived.split(":")
        ):
            raise ValueError(f"Invalid references for {sample_id}")
        path = (stimuli_dir / f"{sample_id}.mp3").resolve(strict=True)
        if path.parent != stimuli_dir.resolve() or path.name != f"{sample_id}.mp3":
            raise ValueError(
                f"Media path escapes the opaque stimuli folder for {sample_id}"
            )
        stimulus = Stimulus(sample_id, path, row["media_sha256"], intended, perceived)
        _verify_media(stimulus)
        clips[sample_id] = stimulus
    if len(clips) != _PILOT_SIZE or any(
        sum(clip.intended == label for clip in clips.values()) != 4
        for label in EMOTIONS
    ):
        raise ValueError(
            "Pilot manifest must have 24 clips and four of each intended emotion"
        )

    prompts = {}
    for name in ("P1", "P2", "P3"):
        content = (prompts_dir / f"{name}.txt").read_bytes()
        if not content.strip():
            raise ValueError(f"Empty prompt {name}")
        prompts[name] = Prompt(name, content.decode("utf-8"), _sha256(content))
    return _sha256(raw_manifest), clips, prompts


def _verify_media(clip: Stimulus) -> bytes:
    content = clip.path.read_bytes()
    if _sha256(content) != clip.sha256:
        raise ValueError(f"Media hash mismatch for {clip.sample_id}")
    return content


def _atomic_text(path: Path, text: str) -> None:
    pending = path.with_suffix(path.suffix + ".tmp")
    with pending.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())
    pending.replace(path)


class PilotRun:
    """Persist completed samples individually and rebuild the transcript on exit."""

    def __init__(self, run_dir, manifest_hash, clips, prompts, ledger):
        self.directory = run_dir
        self.manifest_hash = manifest_hash
        self.clips = clips
        self.prompts = prompts
        self.ledger = ledger
        self.halt_reason = None
        self.secrets = tuple(
            value for name in KEY_NAMES if (value := os.environ.get(name))
        )
        self.rows = {}
        self.rows_dir = run_dir / "samples"
        self.rows_dir.mkdir(parents=True, exist_ok=True)
        provenance = {
            "manifest_sha256": self.manifest_hash,
            "prompt_sha256": {name: prompt.sha256 for name, prompt in prompts.items()},
            "conditions": list(CONDITIONS),
            "models": list(MODEL_IDS),
            "max_output_tokens": MAX_OUTPUT_TOKENS,
        }
        checkpoint_path = run_dir / "inputs.json"
        if checkpoint_path.exists():
            if json.loads(checkpoint_path.read_text(encoding="utf-8")) != provenance:
                raise ValueError("Pilot inputs differ from the previous invocation")
        else:
            _atomic_text(checkpoint_path, json.dumps(provenance, indent=2) + "\n")
        for path in self.rows_dir.glob("*.json"):
            row = json.loads(path.read_text(encoding="utf-8"))
            model, condition, sample_id = self.key(row)
            if (
                model not in MODEL_IDS
                or condition not in CONDITIONS
                or sample_id not in clips
                or path != self.row_path(model, condition, sample_id)
                or row["manifest_sha256"] != self.manifest_hash
                or row["prompt_sha256"] != prompts[condition.split("-", 1)[0]].sha256
                or row["media_sha256"] != clips[sample_id].sha256
            ):
                raise ValueError("Pilot checkpoint differs from the frozen inputs")
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
            raise RuntimeError("Pilot attempted to overwrite a completed sample")
        _atomic_text(self.row_path(*key), json.dumps(row, ensure_ascii=False) + "\n")
        self.rows[key] = row

    def export(self):
        rows = sorted(self.rows.values(), key=self.key)
        _atomic_text(
            self.directory / "transcripts.jsonl",
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        )
        return rows

    def row(self, model, condition, sample_id, started_at, latency_seconds):
        prompt = self.prompts[condition.split("-", 1)[0]]
        return {
            "model": model,
            "served_model": None,
            "condition": condition,
            "prompt": prompt.name,
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
            "usage": None,
        }

    def recover_interrupted_calls(self):
        if self.ledger is None:
            return
        for attempt in self.ledger.records():
            model, condition, sample_id = self.key(attempt)
            if (
                (model, condition, sample_id) in self.rows
                or model not in MODEL_IDS
                or condition not in CONDITIONS
                or sample_id not in self.clips
            ):
                continue
            latency = attempt["latency_ms"]
            row = self.row(
                model,
                condition,
                sample_id,
                attempt["requested_at"],
                latency / 1000 if latency is not None else None,
            )
            row.update(
                ParsedOutput("request_error").as_dict(),
                served_model=self.redact(attempt["served_model"]),
                response_id=self.redact(attempt["response_id"]),
                error="A previously reserved request has no recoverable completion",
            )
            self.commit(row)


def _error_code(error: BaseException):
    seen = set()
    while error is not None and id(error) not in seen:
        if isinstance(error, (BudgetStop, RequestRejected)):
            return type(error).__name__
        for attr in ("http_status", "status_code", "code"):
            code = getattr(error, attr, None)
            if type(code) is int and 400 <= code <= 599:
                return code
        seen.add(id(error))
        error = error.__cause__ or error.__context__
    return None


@solver
def pilot_generation(model_id: str, condition: str):
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        run = _RUN.get()
        if run.halt_reason:
            return state
        sample_id = str(state.sample_id)
        started_at = datetime.now(UTC).isoformat()
        started = monotonic()
        try:
            with budget_scope(condition, sample_id):
                await generate(state, tool_calls="none", cache=False)
        except Exception as error:  # noqa: BLE001 - provider exceptions may contain payloads
            code = _error_code(error)
            if code is None or code in _SYSTEMIC_HTTP or isinstance(code, str):
                run.halt_reason = f"{model_id} {condition} {sample_id} stopped ({code or 'transport or adapter error'})"
            dispatched = run.ledger is None or any(
                run.key(record) == (model_id, condition, sample_id)
                for record in run.ledger.records()
            )
            if dispatched:
                row = run.row(
                    model_id, condition, sample_id, started_at, monotonic() - started
                )
                row.update(ParsedOutput("request_error").as_dict(), error=code)
                run.commit(row)
            return state

        output: ModelOutput = state.output
        stop_reason = output.stop_reason if not output.empty else None
        row = run.row(model_id, condition, sample_id, started_at, monotonic() - started)
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
            parse_output(
                row["completion"], row["prompt"], stop_reason=stop_reason
            ).as_dict()
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
    prompt = run.prompts[condition.split("-", 1)[0]]
    dataset = []
    for clip in pending:
        media = base64.b64encode(_verify_media(clip)).decode("ascii")
        dataset.append(
            Sample(
                id=clip.sample_id,
                input=[
                    ChatMessageUser(
                        content=[
                            ContentAudio(
                                audio=f"data:audio/mpeg;base64,{media}", format="mp3"
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


@asynccontextmanager
async def make_model(
    model_id: str, ledger: BudgetLedger, *, transport=None, files_transport=None
):
    guarded = BudgetTransport(ledger, model_id, transport=transport)
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
                event_hooks={"request": [validate_google_files_request]},
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


async def _run_conditions(run, model_factory):
    logs_dir = (run.directory / "inspect").as_posix()
    for model_id in MODEL_IDS:
        if all((model_id, c, s) in run.rows for c in CONDITIONS for s in run.clips):
            continue
        async with model_factory(model_id) as model:
            for condition in CONDITIONS:
                pending = [
                    clip
                    for sid, clip in run.clips.items()
                    if (model_id, condition, sid) not in run.rows
                ]
                if not pending:
                    continue
                task = _make_task(run, model_id, condition, pending)
                logs = await eval_async(
                    task,
                    model=model,
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
    """Run each frozen pilot condition and export an allowlisted JSONL transcript."""
    if model_factory is None:
        if ledger is None:
            raise ValueError("A durable budget ledger is required for live evaluation")

        def model_factory(model_id):
            return make_model(model_id, ledger)

    manifest_hash, clips, prompts = _load_inputs(
        manifest_path, stimuli_dir, prompts_dir
    )
    run = PilotRun(run_dir.resolve(), manifest_hash, clips, prompts, ledger)
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
