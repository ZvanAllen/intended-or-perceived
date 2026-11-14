# Audio diagnostic

## Original-level transcription

Exact match lowercases and strips punctuation and collapses consecutive whitespace. Each denominator is the 24 scheduled clips.
The reference is the scripted CREMA-D sentence. A difference can reflect the actor’s wording or a transcription error. Exact matches show that the words were recoverable in this condition.

| Model | Exact match |
| --- | ---: |
| `openai/gpt-audio-1.5` | 19/24 (79.2%) |
| `google/gemini-3.5-flash-lite` | 20/24 (83.3%) |

### Mismatches

| Model | Clip | Expected | Returned |
| --- | --- | --- | --- |
| `openai/gpt-audio-1.5` | clip005 | I wonder what this is about. | Sorry, I can't do that. |
| `openai/gpt-audio-1.5` | clip082 | I'm on my way to the meeting. | {"text": "I am on my way to the meeting."} |
| `openai/gpt-audio-1.5` | clip183 | That is exactly what happened. | {"text": "That is exactly what happened."} |
| `openai/gpt-audio-1.5` | clip216 | I think I have a doctor's appointment. | {"transcription": "I think I have a doctor's appointment."} |
| `openai/gpt-audio-1.5` | clip257 | That is exactly what happened. | {"transcription": "That is exactly what happened."} |
| `google/gemini-3.5-flash-lite` | clip005 | I wonder what this is about. | What what is this about? |
| `google/gemini-3.5-flash-lite` | clip082 | I'm on my way to the meeting. | I am on my way to the meeting. |
| `google/gemini-3.5-flash-lite` | clip101 | It's eleven o'clock. | It's 11:00. |
| `google/gemini-3.5-flash-lite` | clip139 | It's eleven o'clock. | It's 11:00. |

## Original-level predicted labels (pilot P1-R1)

| Model | Anger | Disgust | Fear | Happy | Neutral | Sad | Unknown |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `openai/gpt-audio-1.5` | 1 | 0 | 1 | 0 | 21 | 0 | 1 |
| `google/gemini-3.5-flash-lite` | 0 | 0 | 0 | 1 | 23 | 0 | 0 |

## Peak-adjusted predicted labels (diagnostic P1)

| Model | Anger | Disgust | Fear | Happy | Neutral | Sad | Unknown |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `openai/gpt-audio-1.5` | 0 | 0 | 1 | 0 | 23 | 0 | 0 |
| `google/gemini-3.5-flash-lite` | 0 | 0 | 0 | 2 | 22 | 0 | 0 |

## Audio levels

The diagnostic used one linear gain per clip to target −1 dBFS peak, followed by conversion to 16-bit mono WAV at the native sample rate. Per-clip gain removes the between-clip loudness differences present during the listener task. The loudest clip in the 300 is already near full scale, leaving essentially no room for a single positive gain across the set before clipping.
The adjusted clips were sent as WAV, and the original-level runs used MP3. This comparison changes level and input format and uses one generation per clip and model at each level.

Original-level full-set measurements are in the table below.

| Metric | Value |
| --- | ---: |
| clips | 300 |
| pilot clips | 24 |
| source rms min dbfs | -52.86027962922109 |
| source rms median dbfs | -38.84024462839109 |
| source rms max dbfs | -17.011695365768116 |
| source peak max | 0.9999504089355469 |
| source peak max dbfs | -0.00043075319371699077 |
| target peak dbfs | -1.0 |

| Clip | Original RMS dBFS | Original peak dBFS | Gain dB | OpenAI original | OpenAI adjusted | Gemini original | Gemini adjusted |
| --- | ---: | ---: | ---: | --- | --- | --- | --- |
| clip005 | -39.85 | -21.70 | 20.70 | Unknown | Neutral | Neutral | Neutral |
| clip006 | -38.29 | -19.28 | 18.28 | Neutral | Neutral | Neutral | Neutral |
| clip011 | -31.27 | -12.63 | 11.63 | Neutral | Neutral | Neutral | Neutral |
| clip019 | -39.22 | -18.23 | 17.23 | Neutral | Neutral | Neutral | Neutral |
| clip060 | -33.79 | -13.06 | 12.06 | Neutral | Neutral | Neutral | Happy |
| clip072 | -29.96 | -10.40 | 9.40 | Neutral | Neutral | Neutral | Neutral |
| clip082 | -29.35 | -10.69 | 9.69 | Neutral | Neutral | Neutral | Neutral |
| clip093 | -33.89 | -17.09 | 16.09 | Neutral | Fear | Neutral | Happy |
| clip101 | -47.99 | -35.43 | 34.43 | Neutral | Neutral | Neutral | Neutral |
| clip135 | -34.21 | -14.62 | 13.62 | Fear | Neutral | Neutral | Neutral |
| clip139 | -38.86 | -19.09 | 18.09 | Neutral | Neutral | Neutral | Neutral |
| clip142 | -46.88 | -23.14 | 22.14 | Neutral | Neutral | Neutral | Neutral |
| clip152 | -48.11 | -32.13 | 31.13 | Neutral | Neutral | Neutral | Neutral |
| clip160 | -38.98 | -21.07 | 20.07 | Neutral | Neutral | Neutral | Neutral |
| clip174 | -44.30 | -28.00 | 27.00 | Neutral | Neutral | Neutral | Neutral |
| clip183 | -41.89 | -18.60 | 17.60 | Neutral | Neutral | Neutral | Neutral |
| clip192 | -30.98 | -6.82 | 5.82 | Neutral | Neutral | Happy | Neutral |
| clip216 | -43.71 | -26.47 | 25.47 | Neutral | Neutral | Neutral | Neutral |
| clip253 | -38.14 | -21.03 | 20.03 | Neutral | Neutral | Neutral | Neutral |
| clip257 | -49.29 | -28.90 | 27.90 | Neutral | Neutral | Neutral | Neutral |
| clip259 | -51.02 | -31.65 | 30.65 | Neutral | Neutral | Neutral | Neutral |
| clip276 | -34.59 | -16.26 | 15.26 | Neutral | Neutral | Neutral | Neutral |
| clip284 | -41.11 | -21.70 | 20.70 | Neutral | Neutral | Neutral | Neutral |
| clip289 | -22.62 | -4.32 | 3.32 | Anger | Neutral | Neutral | Neutral |
