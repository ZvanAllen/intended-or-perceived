# Intended or Perceived?

This exploratory study evaluates three audio-capable models on 300 acted English clips from CREMA-D. In the first forced-choice run under the amended parser, always predicting Neutral matched **58.0%** of voice-only listener pluralities. GPT-Audio-1.5 matched **63.7%** of those pluralities and predicted Neutral on **87.0%** of clips. Gemini 3.5 Flash-Lite matched **67.3%** and predicted Neutral on **87.3%**. Gemini 4 Carbon matched **65.7%** and predicted Neutral on **56.7%**. The study uses crowd ratings reported by Cao et al. (2014) and model calls from November 14, 2026. It has not been peer reviewed. [Full results](results/analysis/RESULTS.md) · [Methods](docs/METHODS.md)

## Results

The primary analysis allows one surrounding Markdown fence. The table reports P1-R1 accuracy and multiclass Matthews correlation coefficient (MCC), with strict-parser scores for comparison. Amended accuracy uses 300 clips per model, and strict Carbon accuracy uses 227 valid clips from 90 actors. Tied listener pluralities count as a match if the prediction is any of the tied labels. Both reference columns for MCC use the same untied clips, 264 per model except strict Carbon, which uses 198.

| Served model ID | Amended accuracy, intended / perceived | Strict accuracy, intended / perceived | Untied MCC, intended / perceived (amended) | Untied MCC, intended / perceived (strict) | Amended paired gap [95% CI] | P1 clip-level flips, amended |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `gpt-audio-1.5` | 22.7% / 63.7% | 22.7% / 63.7% | 0.150 / 0.328 | 0.150 / 0.328 | +41.0 pp [35.3, 46.4] | 9.0% of 300 |
| `gemini-3.5-flash-lite` | 27.0% / 67.3% | 27.0% / 67.3% | 0.233 / 0.389 | 0.233 / 0.389 | +40.3 pp [34.1, 46.0] | 7.0% of 298 |
| `gemini-4-carbon` | 39.0% / 65.7% | 38.3% / 66.5% | 0.306 / 0.458 | 0.303 / 0.475 | +26.7 pp [20.1, 33.0] | 30.7% of 300 |

For the 300-clip subset, the always-Neutral baseline was 16.7% intended and 58.0% perceived. The majority-class baseline was also 16.7% and 58.0% (Anger and Neutral respectively, with the intended class tie broken in prespecified order). On Carbon’s strict subset the always-Neutral baseline was 16.7% / 59.0%, and the majority-class baseline was Happy 17.2% / Neutral 59.0%. [Baselines and per-reference intervals](results/analysis/primary_accuracy.csv)

Across the 300 clips, an individual listener matched the intended label **38.5%** of the time and the plurality of the other listeners **58.7%** of the time, with clips weighted equally. On Carbon’s strict-parser subset, these listener baselines were 37.1% and 57.8%. [Individual-listener estimates and intervals](results/analysis/primary_accuracy.csv)

The contrast between clip-level flips and the range of aggregate accuracy was largest for Carbon. Its label changed on **30.7%** of clips across three P1 runs, while its accuracy varied by **0.7 percentage points** against intended labels and **1.7 points** against listener pluralities. [Repeat stability](results/analysis/repeat_stability.csv)

Spearman correlations between amended P1-R1 confidence and listener agreement were **0.081** for GPT-Audio-1.5, **0.137** for Flash-Lite, and **0.089** for Carbon. [Confidence and agreement](results/analysis/confidence_agreement.csv)

![P1-R1 accuracy and actor-clustered intervals by reference, with same-subset human and constant-label baselines](results/figures/figure1_reference_accuracy.png)

![P1-R1 accuracy by listener agreement stratum and reference](results/figures/figure2_agreement_accuracy.png)

![Per-clip label flips and aggregate accuracy range across three repeats](results/figures/figure3_repeat_stability.png)

The [results index](results/analysis/RESULTS.md) includes confusion matrices, macro-F1, MCC, human agreement and confidence, forecast divergence, stability, and strict sensitivity tables. The [exploratory format checks](results/analysis/FORMAT_CHECKS.md) compare Carbon’s fenced and unfenced label counts and document the eight OpenAI P3 prose responses.

## Exploratory analysis of non-Neutral voice pluralities

This subset includes the 126 clips from 71 actors whose voice plurality excludes Neutral. A tie involving Neutral excludes the clip. Other ties retain the any-label match rule. The table shows P1-R1 accuracy with 95% actor-clustered bootstrap intervals on each parser’s valid subset.

| Model | Parser | Valid clips / actors | Intended, % [95% CI] | Perceived, % [95% CI] |
| --- | --- | ---: | ---: | ---: |
| GPT-Audio-1.5 | Amended and strict | 126 / 71 | 14.3 [9.2, 19.7] | 17.5 [10.8, 24.8] |
| Gemini 3.5 Flash-Lite | Amended and strict | 126 / 71 | 25.4 [18.6, 32.2] | 23.0 [16.4, 30.1] |
| Gemini 4 Carbon | Amended | 126 / 71 | 42.9 [35.5, 51.1] | 44.4 [36.2, 53.0] |
| Gemini 4 Carbon | Strict | 93 / 62 | 40.9 [31.8, 50.5] | 44.1 [33.7, 54.8] |

On the full subset, always predicting Neutral scored 1.6% intended and 0.0% perceived. Always predicting the majority class, Anger for both references, scored 29.4% and 34.1%. On Carbon’s strict subset the respective baselines were 1.1% / 0.0% and 28.0% / 33.3%. These estimates describe a subset selected using the listener reference. [Full exploratory table](results/analysis/exploratory_non_neutral_plurality.csv) · [Deviation log](docs/DEVIATIONS.md#gate-3-analysis-additions)

## Limitations

- The recordings are scripted, acted English speech from one dataset. Agreement with these listeners measures correspondence to their vote labels under the study conditions. The design cannot establish validity for real-world emotion recognition.
- The sample balances intended emotions and agreement strata, which sets the class proportions used in the baselines. Results should be interpreted for this mixture. Of the 300 clips, 276 have unspecified intended intensity. The other intensity groups are small.
- The perceived model reference uses the full panel, and the individual-listener baseline leaves out the evaluated listener. The exact-match estimates have different reference construction. The human comparison is descriptive.
- Carbon used provider-default `medium` thinking and a 1,024-token output cap that includes thinking. The other models used 256-token caps. Flash-Lite’s provider default is `minimal` thinking, and the OpenAI calls used the audio Chat Completions defaults. The comparison is between these model configurations. [Source lock](SOURCE_LOCK.md)
- Strict parsing excludes 277 Carbon main-run responses that the amended parser can score. Both coverage and metrics are reported under each rule and its valid subset. The strict sensitivity therefore combines formatting exclusion with a change in the clips evaluated.

## Reproduce the figures

From a fresh clone, use the included CSVs to regenerate all three figures and run the tests. Full analysis replay also requires the archived private transcripts and verified CREMA-D metadata. [Public checkout quickstart](docs/METHODS.md#verify-a-public-checkout) · [Archived analysis inputs](docs/METHODS.md#replay-the-archived-analysis)

Code is available under [MIT](LICENSE). The manifest and derived tables based on CREMA-D are attributed to CREMA-D and distributed under ODbL 1.0 with the source contents under DbCL 1.0. Cite Cao, Cooper, Keutmann, Gur, Nenkova, and Verma (2014), *IEEE Transactions on Affective Computing*, 5(4), 377–390. [Data provenance and license](data/README.md) · [Paper DOI](https://doi.org/10.1109/TAFFC.2014.2336244)

AI coding agents assisted implementation under Zack van Allen’s direction. Zack set the design and analysis decisions.
