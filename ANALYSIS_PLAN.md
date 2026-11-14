# Analysis plan

The 24-clip pilot is for engineering and cost checks. The main study estimates how scores depend on the reference, how scores relate to listener agreement, and how stable model responses are across repeats and prompt wording. Main-run execution requires Zack’s approval of the pilot report.

## Inputs and coverage

- Use the frozen, seeded 300-clip CREMA-D manifest with 50 per intended emotion and approximately equal voice-agreement strata within each emotion. Report counts by stratum, actor and sentence. This mixture defines the study sample.
- Compare OpenAI `gpt-audio-1.5` and Gemini `gemini-3.5-flash-lite`. Use three independent P1 generations per clip, one P2 and one P3. Run the full set fresh following pilot review. Record the model identifier returned by the API where available, run dates, request settings and input hashes. Keep response caching off. Record and explain deviations before analysis.
- Keep `prompts/P1.txt` and `prompts/P2.txt` from the pilot. Use `prompts/P3-v2.txt` for the main-run distribution condition on both models. The revision clarifies raw JSON output and asks the model to verify the sum, following the pilot’s Markdown fences and arithmetic errors. The 24-clip run used the original `prompts/P3.txt`.
- The intended reference comes from the CREMA-D stimulus filename. The perceived voice reference is the set of labels tied for the largest count among retained voice votes. Voice agreement is the largest vote count divided by the number of retained voice votes. The high stratum is ≥0.80, middle is ≥0.50 and <0.80, and low is <0.50.
- Validate one JSON object using the condition’s schema. Treat invalid JSON, schema errors, out-of-set labels, refusals, unfinished responses and unavailable requests as unknown. Report coverage by model and prompt using all requested clips as the denominator and valid-only denominators for metrics. Preserve an outcome row for each planned cell and describe missing cases.

## RQ1. Scores by reference

- P1-R1 is the prespecified primary forced-choice result for each model. Report the other forced-choice runs individually. For each run, use paired valid predictions for intended and perceived accuracy. A prediction matching any tied label earns a match. Repeat both accuracies on the same untied subset. Report conventional macro-F1 with all six labels, multiclass MCC and counts in the confusion matrix for the intended reference and for both references on the common untied subset. Mark metrics undefined when their denominator is zero.
- For the primary comparison, report `perceived accuracy − intended accuracy` as a percentage-point difference. Use 2,000 percentile bootstrap replicates with actors as the resampling units (seed `20261112`, interval equal to the 2.5th and 97.5th percentiles). In each replicate draw the original number of distinct eligible actors with replacement and carry across all their valid clips and both paired correctness indicators together. Use the same draws to estimate accuracy intervals for each reference. Report the number of contributing clips and actors.
- Human baseline uses the retained voice responses and the same sampled clips. Within a clip, score each rater’s response against the intended label and against the largest remaining vote count after removing that rater’s response(s). Score against any label tied for the largest remaining count. If a rater has multiple retained responses on one clip, average the individual scores within that rater and clip. Average across raters within each clip, then give clips equal weight. For the primary figure, show each baseline on the same valid clip subset as the corresponding model and compute actor-clustered intervals. Label the baseline as individual listener agreement with the intended label or other listeners.

## RQ2. Listener agreement and distributions

- For each model, report P1-R1 intended and perceived accuracy and coverage within each agreement stratum. Use Spearman rank correlation for P1-R1 stated confidence versus voice agreement on valid clips. Include sample sizes and report undefined correlations when either series is constant.
- For valid P3 forecasts, divide the reported percentages by 100 and construct the reference distribution by dividing each retained vote count by the clip total. Report the mean base-2 Jensen–Shannon divergence and the mean sum of squared differences over the six emotion probabilities (multiclass Brier distance to the empirical vote distribution). Treat zero terms in the divergence as zero. These metrics compare forecasts with observed vote shares.

## RQ3. Repeat and prompt stability

- Among clips with three valid P1 labels, report the fraction with at least one changed label, Fleiss’ kappa across the three repeats and each repeat’s accuracy against both references. Report the range of those three accuracies in percentage points and the complete-repeat coverage. Report individual run accuracy and coverage as a secondary view.
- Compare P1-R1 and P2 on clips with two valid labels. Report label change rate and the paired change in accuracy (P2 minus P1-R1) against both references.

## Tables, figures and interpretation

- Report descriptive counts, coverage and accuracy by intended emotion and intensity. Use the study’s six emotion categories. The core analysis omits demographic comparisons. Optional modality work requires its own frozen subset and modality-matched human references.
- Figure 1 shows primary accuracy by reference and model with actor-clustered intervals and the human baseline. Figure 2 shows P1-R1 accuracy by voice-agreement stratum. Figure 3 compares per-clip flip rate with the range of repeat accuracy. Report valid denominators alongside the plots or in their associated tables.
- Interpret the analysis as exploratory and limited to acted English speech and published CREMA-D crowd ratings, the selected sample, prompts and model versions. Reference agreement describes matching labels under these conditions. Report null and mixed results and any operational limits.
