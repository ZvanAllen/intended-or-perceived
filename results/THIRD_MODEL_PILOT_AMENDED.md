# Higher-tier Gemini pilot

Requested model `google/gemini-4-carbon`. Combined output cap 1024 tokens. Sampling and thinking use provider defaults.
Served model IDs `gemini-4-carbon`.

| Condition | Strict valid | Amended valid | Strict unknown types | Amended unknown types | Mean metered cost per recorded cell | Mean thinking tokens | Max thinking tokens |
| --- | ---: | ---: | --- | --- | ---: | ---: | ---: |
| P1-R1 | 18/24 | 24/24 | parse_error 6 | None | US$0.0008 | 21.4 | 144 |
| P1-R2 | 19/24 | 24/24 | parse_error 5 | None | US$0.0009 | 36.3 | 207 |
| P1-R3 | 19/24 | 24/24 | parse_error 5 | None | US$0.0007 | 16.2 | 74 |
| P2 | 20/24 | 24/24 | parse_error 4 | None | US$0.0013 | 63.8 | 597 |
| P3 | 24/24 | 24/24 | None | None | US$0.0021 | 111.5 | 339 |

Predicted labels below use the amended parser. The stored completions were re-scored offline.

| Condition | Predicted label counts (P3 uses tied largest shares) |
| --- | --- |
| P1-R1 | Anger 1, Disgust 2, Fear 1, Happy 5, Neutral 12, Sad 3 |
| P1-R2 | Anger 2, Disgust 2, Fear 1, Happy 4, Neutral 11, Sad 4 |
| P1-R3 | Anger 3, Disgust 1, Happy 5, Neutral 12, Sad 3 |
| P2 | Anger 4, Disgust 1, Fear 1, Happy 3, Neutral 11, Sad 4 |
| P3 | Anger 4, Disgust 1, Fear 1, Happy 3, Neutral 11, Neutral:Sad 2, Sad 2 |

Pilot metered US$0.1387. Outstanding pilot reservations US$0.0000.
Projected fresh 1,500-call cost US$1.7336. This scales exposure, including unresolved attempts, within each condition.
Projected project exposure US$8.2381. Projected third-arm exposure including pilot calls US$1.8723.
