# Source lock

The public-source checks and ratings audit were completed on November 11, 2026. The 24-clip pilot and the three-model main study ran on November 14, 2026, under a US$25 project-wide API cap. [Methods](docs/METHODS.md) · [Main-run coverage and costs](results/MAIN_COVERAGE_REPORT.md) · [Study results](results/analysis/RESULTS.md)

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

The pool contains 7,427 clips with at least six retained voice ratings after the four documented MP3 exclusions. Of these, 642 have tied voice pluralities. Each intended emotion had enough candidate clips for a 16–17 clip quota in each stratum. Media validation led to one replacement within its stratum before the 300-clip manifest was frozen. [Manifest](data/manifest.csv) · [Sampling and media checks](docs/METHODS.md#sample-and-stimuli)

| Intended emotion | Low (<0.50) | Middle (0.50 to <0.80) | High (≥0.80) |
| --- | ---: | ---: | ---: |
| Anger | 240 | 675 | 355 |
| Disgust | 399 | 755 | 112 |
| Fear | 286 | 749 | 233 |
| Happy | 289 | 731 | 250 |
| Neutral | 62 | 464 | 560 |
| Sad | 266 | 770 | 231 |

### Stimuli

The primary study used `AudioMP3`, the files the authors used for voice-only ratings. Four upstream-flagged clips were excluded before sampling (`1076_MTI_NEU_XX`, `1076_MTI_SAD_XX`, `1064_TIE_SAD_XX` and `1064_IEO_DIS_MD`). `AudioWAV` contains processed audio. `VideoFlash` contains FLV media and includes 28 files with audio restored in 2020. [Pinned media notes](https://github.com/CheyneyComputerScience/CREMA-D/tree/1658cd342dff90010aa843eaeebd53610a08b1dc#video-files)

The preparation script retrieves the selected MP3 objects from the pinned revision and verifies their Git LFS pointer hashes. Before freezing the manifest, local checks verified decoding, duration and embedded metadata. The manifest records hashes for the source and metadata-stripped stimulus files under opaque sample IDs. Provider requests omitted source filenames and reference labels. [Pinned LFS attributes](https://github.com/CheyneyComputerScience/CREMA-D/blob/1658cd342dff90010aa843eaeebd53610a08b1dc/.gitattributes) · [Data preparation](data/README.md)

## Inspect and model configuration

Pin `inspect-ai==0.3.289` (released November 10, 2026, Python ≥3.11, source revision `ad7dc3c94145438b352ca8c1c19b63adf85b56c6`). Inspect supports `ContentAudio` for WAV and MP3 with both providers. It supports `ContentVideo` for MP4, MPEG and MOV with Gemini. The pilot environment uses Python 3.11.7 and the bundled executable from `imageio-ffmpeg==0.6.0`. [PyPI release](https://pypi.org/project/inspect-ai/0.3.289/) · [Inspect release](https://github.com/UKGovernmentBEIS/inspect_ai/releases/tag/0.3.289) · [Multimodal guide](https://inspect.aisi.org.uk/multimodal.html)

| Inspect ID | API and output | Standard text input | Standard audio input | Standard text output |
| --- | --- | ---: | ---: | ---: |
| `openai/gpt-audio-1.5` | OpenAI Chat Completions, text response | US$2.50 | US$32.00 | US$10.00 |
| `google/gemini-3.5-flash-lite` | Gemini Developer API, text response | US$0.30 | US$0.30 | US$2.50 |

Rates are per million tokens in USD. OpenAI also lists US$64 per million audio output tokens. This study requested text output. Gemini’s text output rate includes thinking tokens. Gemini 3.5 Flash-Lite was selected as the low-cost stable Google candidate with audio and video input. Its documented default thinking level is `minimal`. Requests omitted temperature, `top_p` and `top_k`, which Google deprecates and ignores for this model. The study requested JSON through prompts and applied the same local schema checks to each provider’s responses. GPT-Audio-1.5 lacks API-enforced Structured Outputs. The coverage report records the model IDs returned by the providers. [OpenAI model and pricing](https://developers.openai.com/api/docs/models/gpt-audio-1.5) · [Gemini model](https://aistudio.google.com/docs/models/gemini-3.5-flash-lite) · [Gemini pricing](https://aistudio.google.com/docs/pricing#gemini-3.5-flash-lite) · [Gemini API changes](https://aistudio.google.com/docs/whats-new-gemini-3.6) · [Served model IDs](results/MAIN_COVERAGE_REPORT.md)

The study specified an actively billed Gemini project. Google’s Paid Services terms specify that prompts, files and responses are excluded from product improvement. The pinned Inspect adapter sends audio through Gemini’s Files API, which automatically deletes uploads after 48 hours and supports earlier deletion. The pinned adapters send an audio byte stream or file URI with format or MIME type. Local HTTP mocks checked outbound payloads for label-bearing filenames and reference labels before live calls. [Google data-use terms](https://aistudio.google.com/docs/terms#data-use-paid) · [Google Files API](https://aistudio.google.com/docs/files#delete-uploaded) · [Inspect Gemini adapter](https://github.com/UKGovernmentBEIS/inspect_ai/blob/ad7dc3c94145438b352ca8c1c19b63adf85b56c6/src/inspect_ai/model/_providers/google.py#L2934-L3002) · [Inspect OpenAI adapter](https://github.com/UKGovernmentBEIS/inspect_ai/blob/ad7dc3c94145438b352ca8c1c19b63adf85b56c6/src/inspect_ai/model/_openai.py#L460-L470)

## Original two-model pilot

- **Spending.** The pilot scheduled 240 generations (24 clips × five passes × two models). The original two-model main run scheduled 3,000 fresh generations. A durable project-wide ledger reserves spend before each billable generation request, reconciles reported usage, retains reservations for ambiguous outcomes, and stops dispatch if the next reservation would exceed the cap. Observed pilot costs and the final budget are reported separately. [Pilot report](results/PILOT_REPORT.md) · [Main-run coverage and costs](results/MAIN_COVERAGE_REPORT.md)
- **Logs and reproducibility.** The evaluation used `log_images=False` (`--no-log-images`) to omit media from Inspect logs and disabled response caching for repeat runs. The transcript and usage ledger record an allowlisted set of fields. Because Inspect’s normalized usage can omit the audio and text split, the ledger records billing counters directly when available, including Gemini thinking tokens. [Inspect media logging](https://inspect.aisi.org.uk/multimodal.html#logging) · [Inspect model API logging](https://inspect.aisi.org.uk/eval-logs.html#model-api-logging)
- **Analysis decisions.** The analysis plan specifies any-label matching for tied pluralities and an untied subset for conventional perceived-reference macro-F1, MCC and confusion matrices. It compares reference accuracy on the same valid predictions, defines the listener-baseline denominator, pairs valid outputs for prompt comparisons and uses complete repeat sets for flip rates and Fleiss’ kappa. The stratified sample represents the selected mixture of intended emotions and agreement strata. [Analysis plan](ANALYSIS_PLAN.md)

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

The prespecified fallback for account unavailability or a projected 1,500-call cost above US$10 was Gemini 4 Argon. Its November rates matched Carbon’s, and Google reported lower token spend on complex tasks. Gemini 4 Hydrogen and Gemini 3.8 Flash were the next candidates under the same availability and cost rule. This ordering followed the provider’s general capability positioning and did not use pilot emotion labels. Under the original rule, failure to meet strict coverage, frozen-input integrity or local verification requirements stopped the higher-tier arm. [Argon model](https://aistudio.google.com/docs/models/gemini-4-argon) · [Hydrogen model](https://aistudio.google.com/docs/models/gemini-4-hydrogen) · [3.8 Flash model](https://aistudio.google.com/docs/models/gemini-3.8-flash)

On November 14, 2026, the API served `gemini-4-carbon` for all 120 pilot calls. The projected cost of 1,500 fresh calls was US$1.7336. Four forced-choice conditions fell below 23 of 24 valid responses under strict parsing, which paused main-run dispatch for Carbon. An approved amendment allowed one enclosing Markdown fence before applying the same JSON schema. It was adopted before main-run outcomes were examined. Re-parsing the stored pilot responses gave 24 of 24 valid responses in every condition, and Carbon met the amended coverage and cost requirements. Carbon then completed all 1,500 main-run calls on November 14, using the same model, clips, prompts and output cap. The results retain strict coverage alongside amended coverage. [Original Carbon pilot](results/THIRD_MODEL_PILOT_REPORT.md) · [Parser amendment](docs/DEVIATIONS.md#parser-amendment-before-main-run-outcome-access) · [Amended Carbon pilot](results/THIRD_MODEL_PILOT_AMENDED.md) · [Main-run coverage and costs](results/MAIN_COVERAGE_REPORT.md)
