# Protocol (pre-registered)

Committed before any triage output exists. If something changes later, it goes
in "Deviations" at the bottom with the date and reason, and the report shows
both versions of any affected number.

## 1. Data

- Source: GitHub issues in `simstudioai/sim`, fetched 2026-09-25. Selection is
  in `scripts/sample_issues.py`: filed on or after 2025-08-01, not by a bot or
  core team member (50 or more commits), body of at least 150 characters, 100
  issues stratified by maintainer label (bug 53, feature 22, unlabeled 25),
  seed 20260925.
- Split: 60 dev and 40 held-out test (`data/split.json`), stratified the same
  way. Prompt iteration only ever looks at dev outputs. Test is run once per
  frozen prompt version.
- Ground truth: my labels (`data/labels.jsonl`) under LABELING_GUIDE.md.
  Reliability: blind relabel of 20 issues at least 24h later, reported as
  percent agreement and Cohen's kappa per field.
- Secondary reference: Sim maintainers' own `bug` and `feature` labels, compared
  with my category labels after labeling is complete.

## 2. The workflow under test

- Built in the Sim canvas on a self-hosted install (image digests in
  SIM_VERSION.txt), deployed as an API, and called only through that API.
- Input: `title`, `body`. Output: the `Triage` schema in `src/simtriage/schema.py`.
- Model: `claude-haiku-4-5` at temperature 0 if the block exposes it. Structured
  output is used if Sim's Agent block supports a response schema, because a
  customer would use it. Whether Sim actually enforces it is itself measured by
  the schema gate.
- Every issue runs 3 times per prompt version. Run-to-run disagreement is
  reported as a stability metric.

## 3. Deterministic gates (no model calls)

Label-free gates, which work in production where there are no labels:

| gate | fails when |
|---|---|
| `schema` | invalid JSON, a missing or extra field, a value outside the allowed set, a wrong type |
| `consistency` | any of R1 to R7 is violated |
| `summary_length` | the summary is empty, multi-line, or over 160 characters |
| `summary_numbers` | a number or version token in the summary doesn't appear in the issue title or body |
| `summary_urls` | a URL or domain in the summary doesn't appear in the issue |
| `summary_handles` | an email, `@handle` or `#123` reference in the summary doesn't appear in the issue |
| `summary_entities` | a capitalized word that isn't sentence-initial and isn't on a fixed stoplist doesn't appear in the issue (case-insensitive) |

Label-dependent gates (these need ground truth, so they're regression-suite only):
`category_match`, `priority_match`, `product_area_match`, `needs_human_match`.

Results for the two families are always reported separately.

## 4. Metrics

- Per field: accuracy, with macro-F1 for category and product_area. For
  priority, also within-one-level accuracy. For needs_human, precision and
  recall on `true`.
- Gate failure rate for each gate on real outputs.
- Telemetry from Sim's logs API: p50 and p95 end-to-end and per-block latency,
  execution failure rate, tokens, and cost per 100 issues.
- Every proportion gets a 95% Wilson interval. With n=40 on test, differences
  inside the intervals are reported as "no measurable difference".

## 5. Mutation testing

Seeds are v1 outputs (run 1 of 3) that pass every label-free gate and match my
labels on all four fields. Every applicable operator is applied once per seed
with a seeded RNG (seed 11), so the mutant set is deterministic and committed.

| operator | what it does |
|---|---|
| `category_random` | category set to a uniformly random other category |
| `category_plausible` | category swapped to its declared confusable: bug↔question, bug↔security, feature_request↔integration_request, docs↔question, invalid→question |
| `product_area_plausible` | swapped to its declared neighbor: self_hosting↔dev_setup, execution_engine↔workflow_editor, integrations↔api_deployment, agents_models↔integrations, copilot↔agents_models, mcp↔integrations, auth_accounts↔self_hosting, logs_observability↔execution_engine |
| `priority_off_by_one` | one level up or down (seeded), staying within range |
| `needs_human_flip` | needs_human negated |
| `summary_invented_number` | a version or number that isn't in the issue inserted into the summary |
| `summary_invented_entity` | a named tool or service in the summary replaced with one not in the issue |
| `summary_swapped` | the summary replaced with the summary of a different issue from the same category |
| `summary_negated` | the summary's main verb negated (for example "fails" becomes "works") |
| `field_missing` | one field removed (seeded) |
| `field_extra` | a `confidence` field added |
| `enum_case` | category with its first letter capitalized, such as `Bug` |

Each mutant is designed to be wrong. If an operator produces a mutant that is
still correct (say a flipped needs_human that is defensible for that issue),
it's counted and reported, not silently dropped.

## 6. Sim Evaluator comparison

- A second Sim workflow: Start (`issue`, `triage_output`) → Evaluator block,
  deployed as an API. It is the same rubric the labeler had:
  LABELING_GUIDE.md's definitions go into the Evaluator's system prompt,
  because a customer would give their judge the rubric.
- Metrics, each on a 1 to 5 scale:
  - `classification`: are category, priority, product_area and needs_human
    correct for this issue under the rubric?
  - `faithfulness`: does the summary state only what the issue says, with no
    invented numbers, versions, names or claims?
  - `consistency`: are the fields consistent with each other and the rubric's
    rules?
- Model: the block default (`claude-sonnet-4-6`), recorded exactly as the logs
  report it. Temperature 0 if exposed. 3 repeats per input.
- **Primary flag rule:** an input is flagged if any metric scores 3 or lower
  in at least 2 of the 3 repeats.
- Secondary: a full sweep over cutoffs 1 to 4, reporting detection rate and
  false-flag rate at each. All cutoffs are shown, none selected after the fact.
- Inputs: every clean seed (for the false-flag rate), every mutant (for recall
  by operator), and every real v1 output that disagrees with my labels
  (natural errors).
- It is compared side by side with label-free gates, label-dependent gates, and
  their union.

## 7. Improvement loop

v1 prompt, then a dev run. From dev failures only, write the v2 prompt, then run
dev and test. Test is reported for v1 and v2. Each real failure found becomes a
pinned pytest regression case. Maximum 2 iterations (v2, v3) to limit
overfitting to dev.

## 8. Label corrections

If a model output reveals that my label was wrong, the correction goes in
`data/label_corrections.jsonl` with a reason. The report gives metrics under
both the original and the corrected labels. Labels are never edited in place.

## 9. Reproducibility

All model and workflow outputs are recorded in `runs/`. `simtriage report`
rebuilds every number from committed files, with no network access and no
secrets. CI runs the report and the test suite offline.

## Deviations

(none)
