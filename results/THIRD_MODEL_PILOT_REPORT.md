# Higher-tier Gemini pilot

Requested model `google/gemini-4-carbon`. Combined output cap 1024 tokens. Sampling and thinking use provider defaults.
Served model IDs `gemini-4-carbon`.

| Condition | Valid / planned | Unknown types | Mean metered cost per recorded cell | Mean thinking tokens | Max thinking tokens |
| --- | ---: | --- | ---: | ---: | ---: |
| P1-R1 | 18/24 | parse_error 6 | US$0.0008 | 21.4 | 144 |
| P1-R2 | 19/24 | parse_error 5 | US$0.0009 | 36.3 | 207 |
| P1-R3 | 19/24 | parse_error 5 | US$0.0007 | 16.2 | 74 |
| P2 | 20/24 | parse_error 4 | US$0.0013 | 63.8 | 597 |
| P3 | 24/24 | None | US$0.0021 | 111.5 | 339 |

| Condition | Predicted label counts (P3 uses tied largest shares) |
| --- | --- |
| P1-R1 | Anger 1, Disgust 1, Happy 4, Neutral 10, Sad 2, Unknown 6 |
| P1-R2 | Anger 1, Disgust 2, Fear 1, Happy 3, Neutral 8, Sad 4, Unknown 5 |
| P1-R3 | Anger 2, Happy 4, Neutral 10, Sad 3, Unknown 5 |
| P2 | Anger 2, Fear 1, Happy 2, Neutral 11, Sad 4, Unknown 4 |
| P3 | Anger 4, Disgust 1, Fear 1, Happy 3, Neutral 11, Neutral:Sad 2, Sad 2 |

Pilot metered US$0.1387. Outstanding pilot reservations US$0.0000.
Projected fresh 1,500-call cost US$1.7336. This scales exposure, including unresolved attempts, within each condition.
Projected project exposure US$8.2381. Projected third-arm exposure including pilot calls US$1.8723.

Unmet operational gates: strict coverage.
