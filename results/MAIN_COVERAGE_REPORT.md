# Strict and amended operational coverage

Strict requires a raw JSON object. Amended coverage allows a single enclosing Markdown fence and retains the same schema checks. Counts use all planned clips as the denominator.
Unknown columns show strict/amended counts. Both classifications use saved responses.

| Phase | Model | Condition | Strict valid | Amended valid | JSON/schema error | Out of set | Refusal | Incomplete | Request error | Missing | Retried | Failed twice |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| main | `openai/gpt-audio-1.5` | P1-R1 | 300/300 | 300/300 | 0/0 | 0/0 | 0/0 | 0/0 | 0/0 | 0 | 0 | 0 |
| main | `openai/gpt-audio-1.5` | P1-R2 | 300/300 | 300/300 | 0/0 | 0/0 | 0/0 | 0/0 | 0/0 | 0 | 0 | 0 |
| main | `openai/gpt-audio-1.5` | P1-R3 | 300/300 | 300/300 | 0/0 | 0/0 | 0/0 | 0/0 | 0/0 | 0 | 0 | 0 |
| main | `openai/gpt-audio-1.5` | P2 | 300/300 | 300/300 | 0/0 | 0/0 | 0/0 | 0/0 | 0/0 | 0 | 0 | 0 |
| main | `openai/gpt-audio-1.5` | P3 | 292/300 | 292/300 | 8/8 | 0/0 | 0/0 | 0/0 | 0/0 | 0 | 0 | 0 |
| main | `google/gemini-3.5-flash-lite` | P1-R1 | 300/300 | 300/300 | 0/0 | 0/0 | 0/0 | 0/0 | 0/0 | 0 | 0 | 0 |
| main | `google/gemini-3.5-flash-lite` | P1-R2 | 299/300 | 299/300 | 0/0 | 1/1 | 0/0 | 0/0 | 0/0 | 0 | 0 | 0 |
| main | `google/gemini-3.5-flash-lite` | P1-R3 | 299/300 | 299/300 | 0/0 | 1/1 | 0/0 | 0/0 | 0/0 | 0 | 0 | 0 |
| main | `google/gemini-3.5-flash-lite` | P2 | 298/300 | 298/300 | 1/1 | 1/1 | 0/0 | 0/0 | 0/0 | 0 | 0 | 0 |
| main | `google/gemini-3.5-flash-lite` | P3 | 300/300 | 300/300 | 0/0 | 0/0 | 0/0 | 0/0 | 0/0 | 0 | 0 | 0 |
| pilot | `google/gemini-4-carbon` | P1-R1 | 18/24 | 24/24 | 6/0 | 0/0 | 0/0 | 0/0 | 0/0 | 0 | 0 | 0 |
| pilot | `google/gemini-4-carbon` | P1-R2 | 19/24 | 24/24 | 5/0 | 0/0 | 0/0 | 0/0 | 0/0 | 0 | 0 | 0 |
| pilot | `google/gemini-4-carbon` | P1-R3 | 19/24 | 24/24 | 5/0 | 0/0 | 0/0 | 0/0 | 0/0 | 0 | 0 | 0 |
| pilot | `google/gemini-4-carbon` | P2 | 20/24 | 24/24 | 4/0 | 0/0 | 0/0 | 0/0 | 0/0 | 0 | 0 | 0 |
| pilot | `google/gemini-4-carbon` | P3 | 24/24 | 24/24 | 0/0 | 0/0 | 0/0 | 0/0 | 0/0 | 0 | 0 | 0 |
| main | `google/gemini-4-carbon` | P1-R1 | 227/300 | 300/300 | 73/0 | 0/0 | 0/0 | 0/0 | 0/0 | 0 | 0 | 0 |
| main | `google/gemini-4-carbon` | P1-R2 | 219/300 | 300/300 | 81/0 | 0/0 | 0/0 | 0/0 | 0/0 | 0 | 0 | 0 |
| main | `google/gemini-4-carbon` | P1-R3 | 218/300 | 300/300 | 82/0 | 0/0 | 0/0 | 0/0 | 0/0 | 0 | 0 | 0 |
| main | `google/gemini-4-carbon` | P2 | 259/300 | 300/300 | 41/0 | 0/0 | 0/0 | 0/0 | 0/0 | 0 | 0 | 0 |
| main | `google/gemini-4-carbon` | P3 | 300/300 | 300/300 | 0/0 | 0/0 | 0/0 | 0/0 | 0/0 | 0 | 0 | 0 |

| Phase | Model | Served model IDs | UTC dates | Generation attempts | Metered | Holds |
| --- | --- | --- | --- | ---: | ---: | ---: |
| main | `openai/gpt-audio-1.5` | `gpt-audio-1.5` | 2026-11-14 | 1500 | US$1.8553 | US$0.0000 |
| main | `google/gemini-3.5-flash-lite` | `gemini-3.5-flash-lite` | 2026-11-14 | 1500 | US$0.1482 | US$0.0000 |
| pilot | `google/gemini-4-carbon` | `gemini-4-carbon` | 2026-11-14 | 120 | US$0.1387 | US$0.0000 |
| main | `google/gemini-4-carbon` | `gemini-4-carbon` | 2026-11-14 | 1500 | US$1.6526 | US$0.0000 |

Project metered US$4.0484 with US$4.1087 held. Remaining headroom is US$16.8429 under the US$25.0000 cap.
