# Pre-main evaluation checks

## P3-v2 validation

| Model | Strict valid | Fenced failures that pass after unwrapping |
| --- | ---: | ---: |
| `openai/gpt-audio-1.5` | 23/24 | 0 |
| `google/gemini-3.5-flash-lite` | 24/24 | 0 |

The strict parser was applied to both models. The unwrapping column is an offline check of failed responses.
Request errors before a completion: 1.

## Metering and projection

Additional diagnostics and prompt validation metered **US$0.0933**, with **US$0.0101** in unresolved diagnostic reservations, against their shared US$0.50 ceiling.
Cumulative project spend is **US$0.2536** with **US$4.1087** held. Current uncommitted headroom is **US$20.64**.
The projected fresh 3,000-call audio run is **US$2.02**, leaving **US$18.62** after current charges and holds.
This estimate uses observed mean HTTP 200 costs from the original-level forced-choice pilot and the P3-v2 rerun. Retries and gain-adjusted stimulus costs can change the estimate.
