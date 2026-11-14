# Source lock

Public-source checks and ratings audit completed November 11, 2026. Zack confirmed the local repository name `intended-or-perceived` and the US$25 project-wide API cap, and authorized the 24-clip pilot on November 14. Both required credentials are present in the ignored project environment file. Verify account access through the authorized pilot.

## CREMA-D

Use revision `1658cd342dff90010aa843eaeebd53610a08b1dc`. CREMA-D contains 7,442 acted English clips from 91 actors across 12 sentences and six emotion categories. The crowd study reported 2,443 raters and separate voice-only, face-only and audiovisual conditions. Cite the crowd ratings as reported by Cao et al. (2014), the paper’s publication year. [Pinned upstream dataset](https://github.com/CheyneyComputerScience/CREMA-D/tree/1658cd342dff90010aa843eaeebd53610a08b1dc) · [Cao et al., *IEEE Transactions on Affective Computing*, 5(4), 377–390](https://doi.org/10.1109/TAFFC.2014.2336244) · [Author manuscript](https://pmc.ncbi.nlm.nih.gov/articles/PMC4313618/)

The upstream license applies ODbL 1.0 to the database and DbCL 1.0 to its contents. Keep the source attribution and license notice with the manifest and derived rating tables. Use MIT for project code and keep stimulus media outside version control. [Pinned license](https://github.com/CheyneyComputerScience/CREMA-D/blob/1658cd342dff90010aa843eaeebd53610a08b1dc/LICENSE.txt)

### Ratings and modality encoding

- `SentenceFilenames.csv` maps `Stimulus_Number` to `Filename`. The filename codes for Anger, Disgust, Fear, Happy, Neutral and Sad are `ANG`, `DIS`, `FEA`, `HAP`, `NEU` and `SAD`. The corresponding vote codes are `A`, `D`, `F`, `H`, `N` and `S`. `LO`, `MD`, `HI` and `XX` encode the intended intensity. [Pinned filename conventions](https://github.com/CheyneyComputerScience/CREMA-D/tree/1658cd342dff90010aa843eaeebd53610a08b1dc#filename-labeling-conventions)
- `finishedResponses.csv` supplies final individual choices in `respEmo`. For the published tables, the authors exclude final rows with a matching initial response in `finishedEmoResponses.csv` whose `ttr` exceeds 10,000 ms. Match on `sessionNums`, `queryType` and `questNum`. Use this same retained set for vote reconstruction and the leave-one-out baseline. [Pinned response processing code](https://github.com/CheyneyComputerScience/CREMA-D/blob/1658cd342dff90010aa843eaeebd53610a08b1dc/processFinishedResponses.R#L26-L54)
- `processedResults/tabulatedVotes.csv` stores counts by clip and modality. Its first, unnamed column is `100000 * queryType + clipNum`. Query types `1`, `2` and `3` are voice-only, face-only and audiovisual. The six count columns are `A,D,F,H,N,S`. Agreement is the largest vote count divided by `numResponses`. `emoVote` and the summary fields `VoiceVote`, `FaceVote` and `MultiModalVote` preserve tied plurality labels with a colon separator. The filename column is `fileName` in `tabulatedVotes.csv` and `FileName` in `summaryTable.csv`. Define the perceived reference as the set of labels with the most votes. The paper also describes a separate binomial significance procedure. [Pinned tabulation code](https://github.com/CheyneyComputerScience/CREMA-D/blob/1658cd342dff90010aa843eaeebd53610a08b1dc/tabulateVotesV2.r) · [Pinned processed tables](https://github.com/CheyneyComputerScience/CREMA-D/tree/1658cd342dff90010aa843eaeebd53610a08b1dc/processedResults) · [Author manuscript, §§3.1 and 3.2](https://pmc.ncbi.nlm.nih.gov/articles/PMC4313618/)

### Metadata audit

Rebuilding the six-way counts from the pinned CSVs removed 7,688 of 219,688 final responses and retained 212,000. The paper reports one fewer raw response and one fewer exclusion. All 22,326 clip-modality rows matched on filename, counts, totals, plurality label set and agreement (absolute tolerance `1e-8`). The three plurality fields matched across all 7,442 summary rows. The retained export has one duplicated `(localid, clipNum, queryType)` key in the face-only condition. The published counts include both responses. The voice leave-one-out baseline has no duplicated keys.

| Pinned file | Data rows | SHA-256 |
| --- | ---: | --- |
| `SentenceFilenames.csv` | 7,442 | `d88cb50e84bbc30b2e159cdfc25e1cf87777ad97c7c41d6ab8f75d3383b8f740` |
| `finishedResponses.csv` | 219,688 | `5eab9668f6adc2666b0179ae80553a50a5172dbc9812e582cd0ffa7bc0dd237e` |
| `finishedEmoResponses.csv` | 258,932 | `e6d44cbbf1dca05746c789f87ecdbf975e01cb142bba88266f23189a47bb4667` |
| `processedResults/tabulatedVotes.csv` | 22,326 | `774d9d759cb5caf2542758a39eca8c0f1d2777f9987ff5d5adf8066d192f377b` |
| `processedResults/summaryTable.csv` | 7,442 | `fb0e382700d32c0d9adc0c6815292215a36bcf912f2657048862c91e3bd2b317` |

The pool contains 7,427 clips with at least six retained voice ratings after the four documented MP3 exclusions. Of these, 642 have tied voice pluralities. Each intended emotion has enough clips in each stratum for a 16–17 clip quota, based on ratings and known exclusions. Sample feasibility after media validation remains to be checked.

| Intended emotion | Low (<0.50) | Middle (0.50 to <0.80) | High (≥0.80) |
| --- | ---: | ---: | ---: |
| Anger | 240 | 675 | 355 |
| Disgust | 399 | 755 | 112 |
| Fear | 286 | 749 | 233 |
| Happy | 289 | 731 | 250 |
| Neutral | 62 | 464 | 560 |
| Sad | 266 | 770 | 231 |

### Stimuli

Use `AudioMP3` for the primary study because it contains the files the authors used for voice-only ratings. Exclude `1076_MTI_NEU_XX`, `1076_MTI_SAD_XX`, `1064_TIE_SAD_XX` and `1064_IEO_DIS_MD` before sampling. `AudioWAV` contains processed audio. `VideoFlash` contains FLV media and includes 28 files with audio restored in 2020. Record the provenance of any restored files used in the optional modality comparison. [Pinned media notes](https://github.com/CheyneyComputerScience/CREMA-D/tree/1658cd342dff90010aa843eaeebd53610a08b1dc#video-files)

Skip LFS smudging during checkout and fetch only the selected MP3 objects from the pinned revision. Verify LFS pointer hashes and inspect decoding, duration and embedded metadata before freezing the manifest. Use opaque sample IDs and keep references and label-bearing paths out of provider requests. If metadata needs stripping, preserve the source file and hash the exact stimulus sent as well. [Pinned LFS attributes](https://github.com/CheyneyComputerScience/CREMA-D/blob/1658cd342dff90010aa843eaeebd53610a08b1dc/.gitattributes)

## Inspect and model configuration

Pin `inspect-ai==0.3.289` (released November 10, 2026, Python ≥3.11, source revision `ad7dc3c94145438b352ca8c1c19b63adf85b56c6`). Inspect supports `ContentAudio` for WAV and MP3 with both providers. It supports `ContentVideo` for MP4, MPEG and MOV with Gemini. The pilot environment uses Python 3.11.7 and the bundled executable from `imageio-ffmpeg==0.6.0`. [PyPI release](https://pypi.org/project/inspect-ai/0.3.289/) · [Inspect release](https://github.com/UKGovernmentBEIS/inspect_ai/releases/tag/0.3.289) · [Multimodal guide](https://inspect.aisi.org.uk/multimodal.html)

| Inspect ID | API and output | Standard text input | Standard audio input | Standard text output |
| --- | --- | ---: | ---: | ---: |
| `openai/gpt-audio-1.5` | OpenAI Chat Completions, text response | US$2.50 | US$32.00 | US$10.00 |
| `google/gemini-3.5-flash-lite` | Gemini Developer API, text response | US$0.30 | US$0.30 | US$2.50 |

Rates are per million tokens in USD. OpenAI also lists US$64 per million audio output tokens. Use text output. Gemini’s text output rate includes thinking tokens. I selected Gemini 3.5 Flash-Lite as the low-cost stable Google candidate with audio and video input. The model documents `minimal` as the default thinking level. Omit temperature, `top_p` and `top_k` because Google deprecates and ignores these settings for this model. Use prompt-directed JSON and the same local schema checks across providers. GPT-Audio-1.5 lacks API-enforced Structured Outputs. Verify actual served model IDs and settings where exposed in pilot responses. [OpenAI model and pricing](https://developers.openai.com/api/docs/models/gpt-audio-1.5) · [Gemini model](https://aistudio.google.com/docs/models/gemini-3.5-flash-lite) · [Gemini pricing](https://aistudio.google.com/docs/pricing#gemini-3.5-flash-lite) · [Gemini API changes](https://aistudio.google.com/docs/whats-new-gemini-3.6)

Use an actively billed Gemini project for the proposed pilot. Google’s Paid Services terms specify that prompts, files and responses are excluded from product improvement. The pinned Inspect adapter sends audio through Gemini’s Files API, which automatically deletes uploads after 48 hours and supports earlier deletion. The pinned adapters send an audio byte stream or file URI with format or MIME type. Check the outbound payload locally for filename or metadata leakage before live calls. [Google data-use terms](https://aistudio.google.com/docs/terms#data-use-paid) · [Google Files API](https://aistudio.google.com/docs/files#delete-uploaded) · [Inspect Gemini adapter](https://github.com/UKGovernmentBEIS/inspect_ai/blob/ad7dc3c94145438b352ca8c1c19b63adf85b56c6/src/inspect_ai/model/_providers/google.py#L2934-L3002) · [Inspect OpenAI adapter](https://github.com/UKGovernmentBEIS/inspect_ai/blob/ad7dc3c94145438b352ca8c1c19b63adf85b56c6/src/inspect_ai/model/_openai.py#L460-L470)

## Pilot requirements

- **Spending.** The pilot is 240 nominal generations (24 clips × five passes × two models). Budget for 3,240 nominal generations if the 3,000 main-run generations are fresh, plus any billable retries and continuations. The observed per-call cost and account eligibility are pending. Use a durable project-wide ledger with a conservative reservation before each billable generation request, including SDK retries and adapter continuations. Reconcile with provider usage, retain reservations for ambiguous outcomes, and stop dispatch if the next reservation would exceed the cap. Inspect’s cost limit applies per sample. [Inspect evaluation options](https://inspect.aisi.org.uk/reference/inspect_eval.html)
- **Logs and reproducibility.** Use `log_images=False` (`--no-log-images`) to omit media from completed Inspect logs and verify with a local mock before sending audio. Check error paths and export only allowlisted transcript and usage fields. Record each request’s input/output token counts by billing modality when available, including Gemini thinking tokens. Inspect’s normalized usage can omit the needed input split, so capture the relevant provider counters without copying raw payloads into the release. Disable response caching for repeat runs. [Inspect media logging](https://inspect.aisi.org.uk/multimodal.html#logging) · [Inspect model API logging](https://inspect.aisi.org.uk/eval-logs.html#model-api-logging)
- **Analysis decisions to freeze before the main run.** Use any tied plurality label for accuracy and use an untied subset for conventional perceived-reference macro-F1, MCC and confusion matrices. Compare reference accuracy on the same valid predictions and predefine the denominator for the listener baseline. Use paired valid outputs for prompt comparisons and report the complete-repeat denominator for flip rates and Fleiss’ kappa. The stratified sample estimates performance on that mixture of intended emotions and agreement strata. Capture the final choices in `ANALYSIS_PLAN.md` at Gate 1.

The source-verification audit used the upstream metadata CSVs. Operational pilot results are recorded in `results/PILOT_REPORT.md` once available.

## Prespecified higher-tier Gemini addition

Checked November 14, 2026, using Google’s model and pricing documentation and the pinned Inspect adapter. Gemini 4 Carbon (`google/gemini-4-carbon`) is the first candidate under the analysis plan. Google describes Carbon as its most capable general reasoning model and documents stable Developer API support for audio input and text output. This selection uses documented capability and API availability, with cost tested in the fixed pilot. [Gemini 4 Carbon model](https://aistudio.google.com/docs/models/gemini-4-carbon) · [GenerateContent API](https://aistudio.google.com/api-reference/generate-content/generate-content) · [Pinned Inspect adapter](https://github.com/UKGovernmentBEIS/inspect_ai/blob/ad7dc3c94145438b352ca8c1c19b63adf85b56c6/src/inspect_ai/model/_providers/google.py)

| Developer API model ID | Paid Standard input, all supported input modalities | Cached input | Text output including thinking | Default thinking | Rate change |
| --- | ---: | ---: | ---: | --- | --- |
| `gemini-4-carbon` | US$2.00 | US$0.10 | US$10.00 | Medium | Doubles December 1, 2026 |
| `gemini-4-argon` | US$2.00 | US$0.10 | US$10.00 | Medium | Doubles December 1, 2026 |
| `gemini-4-hydrogen` | US$1.50 | US$0.075 | US$7.50 | High | No change listed |
| `gemini-3.8-flash` | US$0.75 | US$0.075 | US$3.75 | Medium | Doubles January 1, 2027 |

All rates are per million tokens in USD. The table uses publicly listed synchronous Standard rates and no optional tools. This study uses text output and short inputs. The Gemini 4 Developer API models use a unified input, thinking and output context of 1,048,576 tokens. Google lists a 1,048,576 input-token limit for Gemini 3.8 Flash. Long Decode and any separate tiers are outside the frozen request envelope. [Carbon pricing](https://aistudio.google.com/docs/pricing#gemini-4-carbon) · [Argon pricing](https://aistudio.google.com/docs/pricing#gemini-4-argon) · [Hydrogen pricing](https://aistudio.google.com/docs/pricing#gemini-4-hydrogen) · [3.8 Flash pricing](https://aistudio.google.com/docs/pricing#gemini-3.8-flash) · [3.8 Flash context limit](https://aistudio.google.com/docs/models/gemini-3.8-flash) · [Thinking defaults](https://aistudio.google.com/docs/thinking#thinking-levels)

Use a fixed 1,024 combined output-token cap for the higher-tier arm. Keep provider-default sampling and thinking. The cap gives short JSON answers room after thinking without assuming the provider will use the full allowance. Google’s broader migration guidance suggests a much larger cap for general applications. The pilot tests strict output coverage and measures actual spend. Carbon scenarios at 200 input tokens per call cost about US$4.44 at 256 billed output tokens per call or US$8.28 at 512 across 1,500 calls. These scenarios are planning estimates. The chosen model must meet the recorded pilot and project cost gates before its main run. [Carbon generation limits and migration guidance](https://aistudio.google.com/docs/whats-new-gemini-4-carbon#setting-output-token-limits)

If Carbon is unavailable on Zack’s account or its projected 1,500-call cost exceeds US$10, the documented next tier is Gemini 4 Argon. Its November rates match Carbon and Google reports lower token spend on complex tasks. Gemini 4 Hydrogen and Gemini 3.8 Flash are further candidates under the same availability and cost rule. This ordering follows the provider’s general capability positioning. The pilot’s emotion labels do not drive substitutions. A failure of strict coverage, frozen-input integrity or local verification stops the conditional arm. [Argon model](https://aistudio.google.com/docs/models/gemini-4-argon) · [Hydrogen model](https://aistudio.google.com/docs/models/gemini-4-hydrogen) · [3.8 Flash model](https://aistudio.google.com/docs/models/gemini-3.8-flash)
