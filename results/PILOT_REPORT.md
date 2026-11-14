# Gate 1 pilot report

The planned pilot has 24 clips and five conditions per model. Coverage
uses all planned calls as the denominator. Unknown outputs include schema
failures, out-of-set labels, refusals, incomplete output and request errors.

| Model | Condition | Valid / planned | Parse errors | Other unknown | Missing |
| --- | --- | ---: | ---: | ---: | ---: |
| `openai/gpt-audio-1.5` | P1-R1 | 23/24 | 0 | 1 | 0 |
| `openai/gpt-audio-1.5` | P1-R2 | 24/24 | 0 | 0 | 0 |
| `openai/gpt-audio-1.5` | P1-R3 | 23/24 | 0 | 1 | 0 |
| `openai/gpt-audio-1.5` | P2 | 24/24 | 0 | 0 | 0 |
| `openai/gpt-audio-1.5` | P3 | 24/24 | 0 | 0 | 0 |
| `google/gemini-3.5-flash-lite` | P1-R1 | 24/24 | 0 | 0 | 0 |
| `google/gemini-3.5-flash-lite` | P1-R2 | 24/24 | 0 | 0 | 0 |
| `google/gemini-3.5-flash-lite` | P1-R3 | 24/24 | 0 | 0 | 0 |
| `google/gemini-3.5-flash-lite` | P2 | 23/24 | 0 | 1 | 0 |
| `google/gemini-3.5-flash-lite` | P3 | 2/24 | 22 | 0 | 0 |

| Model | Coverage | Parse-failure rate |
| --- | ---: | ---: |
| `openai/gpt-audio-1.5` | 118/120 (98.3%) | 0.0% |
| `google/gemini-3.5-flash-lite` | 97/120 (80.8%) | 18.3% |

Parse-failure rates use received responses as the denominator.

Pilot outcomes recorded for 240/240 cells.

## Distribution prompt diagnosis

Gemini produced 22 P3 parse errors. 22 of those completions used Markdown fences. 20 would meet the schema after unwrapping.
The original strict scoring stands. The main-run prompt `P3-v2.txt` clarifies raw JSON formatting and asks for an explicit sum check. Live validation of the revision is pending.

## API cost in USD

| Model | HTTP generation attempts | Metered cost | Unresolved holds | Mean per received response |
| --- | ---: | ---: | ---: | ---: |
| `openai/gpt-audio-1.5` | 120 | $0.1478 | $4.0986 | $0.001242 |
| `google/gemini-3.5-flash-lite` | 120 | $0.0124 | $0.0000 | $0.000103 |

Metered so far **$0.1602**. Unresolved holds **$4.0986**.
Projected fresh main run **$2.02**.
Projected project total with pilot **$2.18** against the US$25 cap.
The projection applies each provider’s metered mean per received response to 1,500 fresh calls.
Budget planning total with existing unresolved holds **$6.28**.
The ledger retains those holds for cap enforcement. Future connection failures or retries can add cost.

## Stimuli

The manifest marks 24 pilot MP3s, with durations ranging from 1.88 to 3.87 seconds.
The four upstream-flagged defective MP3s were outside the eligible pool.
One additional silent recording was replaced before freeze, outside the pilot subset.
Request errors recorded in transcripts: 1.
See the model and condition table for received output status.
Manifest SHA-256 `0742e730a95a51cefc97b942358a078e5712cb2415a406e7bf733e6ffe5d741e`.

Recorded unknowns

- Out Of Set — 2
- Parse Error — 22
- Request Error — 1

UTC run date(s) 2026-11-14.

Served model IDs `gemini-3.5-flash-lite`, `gpt-audio-1.5`.

Main-run dispatch requires a separate approval.
