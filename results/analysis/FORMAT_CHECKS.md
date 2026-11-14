# Exploratory output-format checks

## Carbon label counts by fence status

These counts use amended outputs. P3 uses the largest predicted share and keeps ties explicit. The groups have different sizes.

| Condition | Format | Anger | Disgust | Fear | Happy | Neutral | Sad | Tied argmax | Unknown | Total |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: |
| P1-R1 | fenced | 7 | 0 | 3 | 10 | 42 | 11 | — | 0 | 73 |
| P1-R1 | unfenced | 39 | 8 | 11 | 21 | 128 | 20 | — | 0 | 227 |
| P1-R2 | fenced | 10 | 0 | 4 | 8 | 44 | 15 | — | 0 | 81 |
| P1-R2 | unfenced | 29 | 6 | 12 | 19 | 132 | 21 | — | 0 | 219 |
| P1-R3 | fenced | 18 | 3 | 4 | 5 | 42 | 10 | — | 0 | 82 |
| P1-R3 | unfenced | 35 | 3 | 9 | 23 | 124 | 24 | — | 0 | 218 |
| P2 | fenced | 11 | 0 | 2 | 1 | 25 | 2 | — | 0 | 41 |
| P2 | unfenced | 36 | 9 | 23 | 29 | 135 | 27 | — | 0 | 259 |
| P3 | fenced | 0 | 0 | 0 | 0 | 0 | 0 | — | 0 | 0 |
| P3 | unfenced | 45 | 9 | 15 | 29 | 176 | 25 | Anger:Neutral (1) | 0 | 300 |

## OpenAI P3 prose responses

OpenAI P3 returned 8 of 300 responses that began with prose and failed the JSON schema. The two completions below are reproduced verbatim.

### clip124

```text
I'm unable to listen to any clips right now to provide such an estimate. If you can give me more context or describe the situation, I can try to help in other ways.
```

### clip210

```text
Based on the tone of voice, here's an estimation of how listeners might perceive the emotions:

{
  "Anger": 5,
  "Disgust": 2,
  "Fear": 3,
  "Happy": 15,
  "Neutral": 60,
  "Sad": 15
}
```
