# Protocol (pre-registered)

This version replaces the single-dataset, hand-labeled design from the first
commits (see "History" at the bottom). It was committed before any triage
output existed for either dataset. Anything changed after this point goes in
"Deviations" with the date and reason, and the report shows both versions of
any affected number.

## 1. Two customers, one eval system

The same triage workflow design, gates, mutation engine and report are run for
two "customers", each with its own taxonomy (`src/simtriage/schema.py`) and
rubric (`prompts/<ds>/rubric.md`):

| | Sim (`sim`) | Kubernetes (`k8s`) |
|---|---|---|
| Source | simstudioai/sim issues, snapshot 2026-09-25 | kubernetes/kubernetes issues with a priority label, created on or after 2025-08-01, snapshot 2026-09-25 |
| Issues | 307 (232 with a key, 75 untriaged queue) | 229 |
| Split | dev 139 / test 93, stratified by key | dev 138 / test 91, stratified by priority |
| Answer key | `category_coarse` (bug or feature): the reporter's template choice | `priority`: set by a triager; `category` (kind) and `product_area` (sig): mostly reporter-set |

**Provenance was checked, not assumed.**
- In Sim's snapshot, only 1 of 311 candidate issues had a label applied by
  anyone other than the reporter. Sim's `bug` and `feature` labels come from
  the issue templates. The label-event history is committed.
- For Kubernetes, an issue is included only if the `/priority` command that
  set its label came from someone other than the reporter. 72 reporter-set and
  18 untraceable issues were excluded. The setter for each issue is in
  `data/k8s/priority_provenance.jsonl`.

**Leak removal.** Text that a template inserts automatically (Sim's `[BUG]` and
`[REQUEST]` prefixes and template headings; Kubernetes' form headings and
placeholders) and prow commands (`/kind`, `/sig`, ...) are stripped, because
they give away the answer. Anything a person typed is kept. The build scripts
list the exact strings.

## 2. The workflow under test

- Built in the Sim canvas on a self-hosted install (image digests in
  SIM_VERSION.txt), one triage workflow per customer, deployed as an API, and
  called only through that API.
- Model `claude-haiku-4-5` with native structured output, and temperature set
  explicitly to 0 (Sim's default when the field is empty is 0.7).
- Every issue runs 3 times per prompt version. Run-to-run disagreement is
  reported as stability.

## 3. Deterministic gates (no model calls)

Label-free: `schema`, `consistency` (the customer's rules), `summary_length`,
`summary_numbers`, `summary_urls`, `summary_handles`, `summary_entities`.
Label-dependent: one `<field>_match` gate per field that has a key. A key may
list several acceptable values, and any of them counts as a match. Sim's
coarse key compares the model's category through a fixed map (bug, security →
bug; feature_request, integration_request → feature; anything else → other).

## 4. Metrics

- For each field with a key: accuracy with a 95% Wilson interval, next to a
  **majority baseline** (always answer the most common dev-split value,
  scored on the reported split). For priority: within-one-level accuracy and a
  confusion table.
- Gate failure rates on real outputs, including Sim's untriaged queue.
- Telemetry from Sim's logs API: p50 and p95 latency end to end and per
  block, execution failure rate, cost per 100 runs.
- Sim only: accuracy for issues filed before and after 2025-08-01, as a check
  for training-data contamination.

## 5. Mutation testing

Seeds are v1 outputs (repeat 0) that pass every label-free gate and agree with
every keyed field. Fields without a key are unverified in a seed, and the
report says which fields had a key. There are 12 operators
(`src/simtriage/mutations.py`) with seed 11. Confusable categories, neighboring
areas and the invented-entity pools are defined per customer, so the injected
defects are plausible for that domain.

## 6. Sim Evaluator comparison

- One Evaluator workflow. The customer's rubric is included in the content it
  scores, so the judge has the same rules as the triage agent.
- Metrics `classification`, `faithfulness` and `consistency`, each on a 1 to 5
  scale (`prompts/evaluator_metrics.json`).
- The model is the block's default, recorded as the logs report it,
  temperature 0, 3 repeats.
- **Primary flag rule:** flagged if any metric scores 3 or lower in at least
  2 of 3 repeats. A sweep over cutoffs 1 to 4 is also reported, with every
  cutoff shown.
- Inputs: clean seeds (false-flag rate), mutants (recall by operator), and
  real outputs that disagree with the key (natural errors).

## 7. Adjudication (human, after outputs)

- Sim: every disagreement between the model and the reporter's bug/feature
  choice is settled by the author (model right, reporter right, or neither),
  alone and with no AI review, in `data/sim/adjudications.jsonl`. The report
  gives Sim metrics under the `original` key (primary) and the `adjudicated`
  key, and reports how often the reporter's template choice was wrong.
- Both datasets: every label-free gate failure on a real output and every
  Evaluator flag on a clean seed is marked `true_defect` or `false_alarm`.
  False-alarm rates come only from adjudicated records.

## 8. Improvement loop

v1, then dev run and error analysis on dev only, then v2, then dev and test.
Test is reported for v1 and v2. At most two iterations. Each real failure found
becomes a pinned pytest case.

## 9. Reproducibility

Raw snapshots, build scripts, prompts, all outputs and the Evaluator scores are
committed. `simtriage report` rebuilds every number offline with no secrets,
and CI runs it.

## History

- 2026-09-25 (commits 71b73e6..c7122a0): the first design had the author hand-
  label 100 Sim issues. It was abandoned after 2 labels. Labeling technical
  issues from scratch was slow for one person. AI review of the labels was
  rejected because Claude is also the model under test. That made the case for
  existing human answer keys, which led to checking label provenance and
  finding that Sim's labels are reporter-set.

## Deviations

- 2026-09-25, before any Evaluator run: section 6 says temperature 0. Sim's
  Evaluator block hides temperature and fixes it at 0.1
  (`EVALUATOR.DEFAULT_TEMPERATURE`), and it generates its own system prompt
  from the metrics ("... only scores"). The Evaluator runs as Sim ships it:
  default model (`claude-sonnet-5` in this image, recorded from the logs),
  temperature 0.1. The 3 repeats already capture its run-to-run variation.
- 2026-09-25, before any Evaluator run: the Evaluator runs as pre-registered
  (every input, 3 runs, flagged if 2 of 3 runs flag). Two additions: (1) runs
  are ordered repeat-major (every input's first run before any second run),
  so a run cut short by API credits still covers every input once; (2) a
  single-run verdict (repeat 0 only) is reported as a secondary column, to
  show what a customer running the Evaluator once per output would see.
- 2026-09-25, after the first Evaluator pass and before any recall or
  false-flag number was computed: the Evaluator's real cost was $0.012 per
  check (2,509 Sim checks cost $30.43). The single test call suggested about
  $0.0047; the judge's answers average 683 output tokens, not about 25. Runs 2
  and 3 would have cost about $76 more and were cancelled for budget. The
  **primary** Evaluator verdict is therefore the single run (flagged if any
  metric is 3 or lower in repeat 0), which is also how a customer running the
  Evaluator once per output would use it. The 2-of-3 majority rule stays in
  the code and is reported only where 3 runs exist. Judge consistency may be
  measured later on a small subset, if budget allows.

