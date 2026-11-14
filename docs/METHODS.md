# Methods

**Draft for Gate 3 review.** This exploratory study compares model judgments of acted vocal emotion with two references from CREMA-D. The intended label is the emotion the actor was asked to portray. The perceived voice reference is the plurality of retained voice-only listener choices, with ties preserved. CREMA-D was pinned to revision `1658cd342dff90010aa843eaeebd53610a08b1dc`. [CREMA-D and provider source lock](../SOURCE_LOCK.md) · [Frozen analysis plan](../ANALYSIS_PLAN.md)

## Sample and stimuli

The frozen manifest contains 300 original-level MP3 clips from 91 actors and all 12 scripted sentences. Within each of the six intended emotions we selected 50 clips stratified by voice agreement and favored underrepresented actors and sentences. Agreement is the maximum voice vote share. The strata are low (<0.50), middle (≥0.50 and <0.80), and high (≥0.80). The full sample includes 100 clips per stratum. The seed was `20261111`, and eligibility required six retained voice ratings. Four upstream-flagged MP3s were excluded. A fifth clip was replaced within its stratum after local decoding showed digital silence. The 24-clip pilot was drawn from the 300, four per intended emotion and eight per stratum. After stripping container metadata, the prepared MP3s decoded to identical samples as the source at the same playback level. Opaque sample IDs and source and stimulus SHA-256 hashes are in the manifest.

The manifest SHA-256 is `0742e730a95a51cefc97b942358a078e5712cb2415a406e7bf733e6ffe5d741e`. Gain-adjusted WAVs were used in the separate audio diagnostic. [Manifest](../data/manifest.csv) · [Sample counts](../results/analysis/sample_counts.csv) · [Audio diagnostic](../results/AUDIO_DIAGNOSTIC.md)

## Models and prompts

On November 14, 2026, we evaluated `gpt-audio-1.5` with OpenAI Chat Completions and `gemini-3.5-flash-lite` and `gemini-4-carbon` with the Gemini Developer API, using Inspect AI 0.3.289. All three returned the requested model ID. Requests contained the stimulus and prompt, with no actor, source filename, sentence code, or reference label. Each model completed 1,500 fresh calls. P1 used forced choice with confidence and was repeated three times with identical prompt bytes. P2 added emotion definitions. P3-v2 asked for predicted shares of the listener choices. Each prompt instructed the model to judge vocal tone and ignore the spoken words. The first pilot used the original P3 prompt. The main study used the locked P3-v2 prompt and the same six-label schemas across models.

All calls used provider-default sampling with response caching off. Carbon used provider-default `medium` thinking and a 1,024-token combined output cap. OpenAI and Flash-Lite used 256-token caps. Flash-Lite’s provider default is `minimal` thinking. The OpenAI audio calls did not set a reasoning or thinking parameter. Inspect transcripts and the usage ledger record served IDs, timestamps, hashes and request attempts. [Main-run dates, coverage and budgets](../results/MAIN_COVERAGE_REPORT.md) · [Prompt hashes and transcript provenance](../results/analysis/provenance.json)

## Parsing, coverage and reference scoring

The strict parser expects a JSON object in the original response. The amended parser removes one surrounding Markdown code fence when the whole response is a single fenced block, then applies the same schema. Zack approved the amendment after the Carbon pilot and before any main-run outcome was opened. The primary analysis uses amended parsing for every model and condition. Strict parsing is reported alongside it on its own valid subset. Invalid JSON or schema, out-of-set labels, incomplete responses, refusals and unavailable requests remain unknown. Coverage uses the number of scheduled clips. Performance metrics use eligible valid clips. The analysis preserves raw stored text and assigns no accuracy to unknown responses.

For RQ1 we compare the two references on paired predictions. A hit against a tied perceived reference may match any included label. The untied sensitivity comparison uses the same untied clips for both references. Multiclass confusion matrices, macro-F1 and MCC require one reference label per clip. Macro-F1 averages across all six labels and assigns zero to classes absent from both marginals when the subset is nonempty. MCC is undefined where its denominator is zero. The majority-class baseline uses the single label with most possible matches on the corresponding subset, using the fixed label order to break ties. Always-Neutral and majority-class accuracy use the same reference, clip subset and unit weighting as the model accuracy.

The primary P1-R1 accuracy intervals and paired perceived-minus-intended intervals use 2,000 percentile bootstrap draws of actors with replacement (seed `20261112`). Each draw samples the original number of distinct eligible actors and carries all valid clips from each sampled actor, using multiplicity when an actor appears more than once. The same draw carries both correctness indicators and listener-baseline values. Percentiles use linear interpolation.

## Listeners, agreement and stability

We joined `finishedResponses.csv` to the pinned initial-response records by session, modality and question, excluding responses with initial times above 10,000 ms per the published process. For voice-only ratings, we verified the six-count vote vector for every clip against both the published tabulation and the frozen manifest. Individual listeners were compared with the intended emotion and with the plurality of other retained listeners after holding out all of that listener’s votes for that clip. The human baseline first averages repeated responses within a rater, then raters within a clip, then clips with equal weight. Figure 1 evaluates the human baseline on the same clip subset as each model. The published export contributed 2,755 retained voice ratings across the 300 clips, with 6–11 per clip.

For RQ2, P1-R1 accuracy and coverage are tabulated by agreement stratum. Spearman correlation between stated confidence and agreement uses average ranks for ties. For P3-v2, we report base-2 Jensen–Shannon divergence and the sum of squared differences between the model percentages and empirical vote shares after converting both to fractions. For RQ3, the complete-repeat subset contains clips with all three P1 labels valid. On that subset we report the fraction with any label change, Fleiss’ κ, each repeat’s accuracy and the range of aggregate accuracies. The P1-R1 vs. P2 comparison uses clips with both labels valid. See [analysis tables and captions](../results/analysis/RESULTS.md).

## Limitations

The results describe 300 scripted, acted English recordings from one dataset with one sampling design and three model configurations. The ratings were reported in 2014. Listener agreement depends on the selected panels and reflects correspondence to their votes under these conditions. Real-world emotion recognition would require separate validation. The human leave-one-out comparison and the full-panel perceived reference have different constructions. The majority-class baselines reflect the sampled mix, and 276 clips have unspecified intended intensity. Carbon used default `medium` thinking and a 1,024-token cap while the two other models ran under 256-token caps and their own provider defaults. The study cannot isolate model strength from these settings. Strict format exclusions change the set of Carbon clips that contribute to the sensitivity analysis. The analysis is exploratory and has not been peer reviewed.

## Reproduce the analysis

The project uses Python 3.11 with pinned dependencies. Run from the checkout with the verified metadata in `data/local/metadata/`, the original two-model transcript and checkpoint header in `results/private/main/`, and their Carbon counterparts in `results/private/main/third-model/`. The [data preparation instructions](../data/README.md) show how to retrieve the public data. The analysis regenerates the CSV tables and the exploratory format examples from those inputs. The following commands make no model calls.

```powershell
uv sync --locked --group analysis
$env:PYTHONPATH = 'src'
.venv/Scripts/python.exe -m intended_or_perceived.analysis
.venv/Scripts/python.exe -m intended_or_perceived.figures --tables results/analysis --output results/figures
.venv/Scripts/python.exe -m pytest
.venv/Scripts/ruff.exe check src tests
```

The [derived data tables](../results/analysis/RESULTS.md#figures-and-derived-data) allow inspection of coverage, scores, votes and clip-level stability without the raw transcripts. See the [deviation log](DEVIATIONS.md) for exploratory format checks and operational choices.

AI coding agents assisted implementation under Zack van Allen’s direction. Zack set the design and analysis decisions. Gate 3 review of the findings and release wording is pending.
