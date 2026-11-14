# Pilot methods

This exploratory study compares model judgments of acted vocal emotion with two references from CREMA-D. The intended label is the emotion the actor was asked to portray. The perceived voice label is the plurality of retained voice-only listener choices, with ties preserved. Data provenance, the published rating filter, model rates and source revisions are recorded in [SOURCE_LOCK.md](../SOURCE_LOCK.md).

## Sample and conditions

The frozen sample has 300 MP3 stimuli, 50 per intended emotion. Candidate clips have at least six retained voice ratings. The selection balances high, middle and low listener agreement, favors underrepresented actors and sentences, and uses seed `20261111`. The four defective MP3s identified by CREMA-D were excluded before sampling. Local decoding found digital silence in `1046_TIE_HAP_XX.mp3`, which was replaced with `1046_WSI_HAP_XX.mp3` from the same stratum before freeze. The pilot selects 24 clips from those 300, four per intended emotion and eight per agreement stratum. The manifest records the exact source and stimulus hashes and the pilot flag.

Each model receives the same stimuli and prompts. P1 is a forced choice with confidence, repeated three times. P2 adds category definitions for one forced-choice run. P3 asks for the predicted distribution of listener choices. The prompts tell models to use vocal tone and ignore the words. The three P1 repeats use identical prompt bytes. The model-facing messages include audio and prompt text. The runner keeps actor, sentence, source filename and both reference labels outside those messages. The pilot uses `P3.txt`. The analysis plan freezes the format-only revision `P3-v2.txt` for the main run.

## Local reproduction

Install from the pinned `uv.lock` with Python 3.11. Run the commands from the project root. The download script fetches only the pinned metadata and 300 sampled audio files. The second command checks the ratings and media hashes, decodes the MP3s, strips container metadata and prepares the manifest deterministically.

```powershell
uv sync --locked
$env:PYTHONPATH = 'src'
.venv/Scripts/python.exe -m intended_or_perceived.dataset --download
.venv/Scripts/python.exe -m intended_or_perceived.dataset
.venv/Scripts/python.exe -m pytest
.venv/Scripts/ruff.exe check src tests
```

The live pilot entry point is `python -m intended_or_perceived.pilot --live` from the locked environment. Supply `OPENAI_API_KEY` and either `GOOGLE_API_KEY` or `GEMINI_API_KEY` in the environment or in the ignored project `.env`. The runner records spend and unresolved reservations in `results/private/project_budget.sqlite3` and keeps transcripts and Inspect logs in `results/private/pilot/`. Keep those local paths intact to resume the pilot using the same ledger and checkpoints. Regenerate the coverage and cost report from those saved files with `python -m intended_or_perceived.pilot --report-only`.

## Measurement

Scoring validates the JSON output and records unscorable responses as unknown. The pilot report gives valid coverage, parse failures among received responses, request errors, metered cost and unresolved reservations. A complete pilot supports a projection using the observed mean by model, 1,500 fresh main-run calls per model and the cost of the pilot. The main-run analysis follows [ANALYSIS_PLAN.md](../ANALYSIS_PLAN.md).

AI coding agents assisted implementation under Zack’s direction.
