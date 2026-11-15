# Main-study results

All three models evaluated the same 300 original-level CREMA-D MP3s across five conditions on November 14, 2026. Every scheduled call returned a response. Primary results use the amended single-fence parser. Strict results use the raw completions and their own valid subsets. See [coverage by condition and unknown type](../MAIN_COVERAGE_REPORT.md).

## RQ1. Accuracy depends on the reference

Primary P1-R1 accuracy and actor-clustered 95% percentile intervals. The paired gap is perceived minus intended in percentage points. Accurate matches to any tied voice plurality count. The constant-label baselines use the same valid clips as the corresponding model.

| Parser | Model | Valid clips / actors | Intended, % [95% CI] | Perceived, % [95% CI] | Paired gap, pp [95% CI] | Always Neutral, intended / perceived | Majority class, intended / perceived |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| Amended | GPT-Audio-1.5 | 300 / 91 | 22.7 [18.1, 27.2] | 63.7 [58.3, 69.0] | +41.0 [35.3, 46.4] | 16.7% / 58.0% | Anger 16.7% / Neutral 58.0% |
| Amended | Gemini 3.5 Flash-Lite | 300 / 91 | 27.0 [22.4, 31.9] | 67.3 [61.7, 72.6] | +40.3 [34.1, 46.0] | 16.7% / 58.0% | Anger 16.7% / Neutral 58.0% |
| Amended | Gemini 4 Carbon | 300 / 91 | 39.0 [33.5, 44.6] | 65.7 [60.9, 70.3] | +26.7 [20.1, 33.0] | 16.7% / 58.0% | Anger 16.7% / Neutral 58.0% |
| Strict | GPT-Audio-1.5 | 300 / 91 | 22.7 [18.1, 27.2] | 63.7 [58.3, 69.0] | +41.0 [35.3, 46.4] | 16.7% / 58.0% | Anger 16.7% / Neutral 58.0% |
| Strict | Gemini 3.5 Flash-Lite | 300 / 91 | 27.0 [22.4, 31.9] | 67.3 [61.7, 72.6] | +40.3 [34.1, 46.0] | 16.7% / 58.0% | Anger 16.7% / Neutral 58.0% |
| Strict | Gemini 4 Carbon | 227 / 90 | 38.3 [31.7, 44.9] | 66.5 [60.4, 72.3] | +28.2 [20.3, 35.4] | 16.7% / 59.0% | Happy 17.2% / Neutral 59.0% |

On the full primary subset, the equal-clip individual-listener baseline was 38.5% [34.8, 42.1] against the intended emotion and 58.7% [56.7, 60.7] against the plurality of other listeners. On Carbon’s strict subset, the corresponding estimates were 37.1% [33.1, 41.1] and 57.8% [55.1, 60.3]. The perceived model score uses the full listener panel as its reference, whereas the human comparison leaves the evaluated listener out.

Thirty-six clips had tied voice pluralities. The reference gap was positive for all models on the untied subset as well. Conventional macro-F1 and MCC use single-valued references, so the perceived scores and corresponding intended comparison use the untied subset. The [all-condition accuracy and baseline table](accuracies.csv), [macro-F1 and MCC](classification.csv), and [confusion matrices](confusion_matrices.csv) retain both parser versions and valid counts.

Neutral was predicted on 261, 262, and 170 of 300 amended P1-R1 responses by GPT-Audio-1.5, Flash-Lite, and Carbon, respectively. On these clips, always choosing Neutral reached 58.0% agreement with the voice plurality. This baseline qualifies the size and interpretation of the perceived accuracy scores. [Predicted-label counts](predicted_labels.csv)

## RQ2. Human agreement and distribution forecasts

Perceived accuracy was highest in the high-agreement stratum for each model. Intended accuracy was highest in that stratum for GPT-Audio-1.5 and Flash-Lite. Carbon’s intended accuracy ranged from 38% to 40% across the three strata. The primary stratum comparisons each used 100 clips. The exact same-subset baseline and strict-parser estimates are in the [accuracy table](accuracies.csv).

| Model | Confidence vs. agreement Spearman ρ, amended / strict | P3 valid, amended / strict | Mean JS divergence, amended / strict | Mean Brier distance, amended / strict |
| --- | ---: | ---: | ---: | ---: |
| GPT-Audio-1.5 | 0.081 / 0.081 | 292 / 292 | 0.287 / 0.287 | 0.294 / 0.294 |
| Gemini 3.5 Flash-Lite | 0.137 / 0.137 | 300 / 300 | 0.344 / 0.344 | 0.426 / 0.426 |
| Gemini 4 Carbon | 0.089 / 0.067 | 300 / 300 | 0.243 / 0.243 | 0.287 / 0.287 |

Confidence correlations used 300 of 300 clips except for strict Carbon, which used 227. Lower P3 distances mean the forecast was closer to the empirical vote shares on the evaluated subset. The [P3 table](distribution_forecasts.csv) gives per-category mean forecast shares. The [label table](predicted_labels.csv) gives the largest-share label counts with ties retained.

## RQ3. Stability across repeated calls and prompt wording

Across three P1 repeats, a clip flipped if at least one of its labels differed. Accuracy ranges use exactly the same clips as the flip and κ calculations. Values for the two references are intended / perceived. The [full repeat table](repeat_stability.csv) gives each repeat’s accuracy and both constant-label baselines.

| Model | Parser | Complete P1 clips | Flipped | Fleiss’ κ | Aggregate accuracy range, pp | Paired P1-R1 / P2 clips | Prompt label change | P2 minus P1-R1, pp |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| GPT-Audio-1.5 | Amended and strict | 300 | 9.0% | 0.760 | 1.0 / 1.0 | 300 | 10.3% | +1.7 / +2.7 |
| Gemini 3.5 Flash-Lite | Amended and strict | 298 | 7.0% | 0.776 | 2.7 / 2.7 | 298 | 13.4% | +3.0 / +0.3 |
| Gemini 4 Carbon | Amended | 300 | 30.7% | 0.655 | 0.7 / 1.7 | 300 | 24.7% | +2.0 / +2.0 |
| Gemini 4 Carbon | Strict | 133 | 30.1% | 0.648 | 2.3 / 2.3 | 199 | 26.6% | +4.0 / +1.5 |

The denominator for both stability subsets is 300 scheduled clips per model. The [prompt comparison table](prompt_stability.csv) includes paired accuracies and their baselines. Repeatability and changes in aggregate accuracy refer to these three runs and prompt wordings.

## Figures and derived data

The figures contain information from CREMA-D by Cao et al. (2014). The frozen manifest and the CREMA-D–derived CSV tables in this directory are available under the Open Database License 1.0. The Database Contents License 1.0 applies to the original CREMA-D contents. [Pinned CREMA-D dataset](https://github.com/CheyneyComputerScience/CREMA-D/tree/1658cd342dff90010aa843eaeebd53610a08b1dc) · [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/) · [DbCL 1.0](https://opendatacommons.org/licenses/dbcl/1-0/) · [Data provenance and license](../../data/README.md)

1. [Reference accuracy](../figures/figure1_reference_accuracy.png) shows amended P1-R1 accuracy and the same-subset listener baselines with actor-clustered intervals. Constant-label baselines use the same valid clips. [PDF](../figures/figure1_reference_accuracy.pdf)
2. [Accuracy by listener agreement](../figures/figure2_agreement_accuracy.png) shows both references in the three strata. Baseline markers are horizontally offset within each stratum for legibility. [PDF](../figures/figure2_agreement_accuracy.pdf)
3. [Repeat stability](../figures/figure3_repeat_stability.png) compares clip-level flips and aggregate accuracy range by reference on complete P1 triples. [PDF](../figures/figure3_repeat_stability.pdf)

[Sample counts](sample_counts.csv) cover intended emotion, intensity, agreement, actor and sentence. The [accuracy tables](accuracies.csv) also include breakdowns by emotion and intensity. The three derived clip-level files contain [predictions and scores](per_clip_predictions.csv), [listener baseline aggregates](per_clip_listeners.csv), and [repeat and prompt label changes](per_clip_stability.csv). Join them on `sample_id` to the [frozen manifest](../../data/manifest.csv). Blank cells mark undefined or inapplicable values.

The exploratory P1-R1 table reports accuracy and baselines on clips whose voice plurality excludes Neutral, under both parser rules. [Non-Neutral voice plurality subset](exploratory_non_neutral_plurality.csv)

The [exploratory format checks](FORMAT_CHECKS.md) give Carbon’s fenced and unfenced counts and two verbatim examples from the eight GPT-Audio-1.5 P3 prose responses. The [deviation log](../../docs/DEVIATIONS.md) records those additions. Main-run transcript and prompt hashes are in [analysis provenance](provenance.json).

## Verification

Pytest reported `105 passed in 34.31s`. Ruff reported `All checks passed!` for `ruff check src tests`. Hand-computed fixtures cover tied accuracy and baselines, six-class confusion and classification metrics, paired actor resampling with unequal cluster sizes, tied ranks, probability distances, repeat and prompt stability, and leave-one-rater-out scoring. Independent calculations also matched the exported confusion matrices, macro-F1, MCC, Spearman correlations and P3 distance summaries. [Metric fixtures](../../tests/test_metrics.py) · [Listener fixtures](../../tests/test_human_baseline.py)
