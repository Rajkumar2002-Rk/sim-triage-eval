# sim-triage-eval

I built an issue triage workflow on [Sim](https://github.com/simstudioai/sim), deployed it as an API on a self-hosted install, and then built the eval loop around it that I'd want if a customer were putting this into production. That means deterministic checks that don't call a model, mutation testing to see what those checks actually catch, a side-by-side comparison with Sim's own Evaluator block, and one round of prompt improvement driven by the errors.

## The short version

- **Sim's Evaluator catches what my cheap checks can't.** My deterministic checks catch 100% of invented numbers and broken structure, but 0% of summaries whose meaning was flipped and at most 17% of wrong-but-plausible categories. The Evaluator caught 91 to 100% of those. Used together, they catch 88 to 100% of every kind of injected mistake on Sim; on Kubernetes, everything except priority (41%) and needs_human (56%).
- **Real mistakes are much harder than injected ones.** The Evaluator caught 88 to 100% of most injected mistakes, but only 54% of the model's real mistakes on Sim issues and 41% on Kubernetes.
- **The Evaluator's flags on good outputs were mostly false alarms.** At the default cutoff it flagged about a third of outputs that had passed my checks and matched the answer key. When I reviewed a blind sample by hand, 0 of 8 flagged summaries and 2 of 15 flagged triage calls were actually wrong.
- **The model rates Kubernetes issues far more urgent than the maintainers do.** On priority it scored 24%, where always answering "important-longterm" would score 44%. A calibrated v2 prompt raised it to 33%, and within-one-level to 87%, but it's still below that baseline.

## What I built

Two "customers", one eval system:

- **Sim's own issue queue.** 307 real issues from simstudioai/sim. The answer key is the reporter's own choice of the "Bug report" or "Feature request" template (232 issues). The other 75 have no label at all, and the workflow triages them the way it would in production.
- **Kubernetes.** 229 issues from kubernetes/kubernetes where the priority was set by a triager, not by the person who filed it. I checked every one against the `/priority` comment that set the label. The rubric is Kubernetes' own published triage guide.

For each customer there's a workflow built in the Sim canvas (Claude Haiku 4.5, structured output, temperature 0), deployed and called only through Sim's API, 3 runs per issue. A third workflow wraps Sim's Evaluator block. The exported definitions are in [sim_workflows/](sim_workflows/).

## Triage accuracy

Every number comes with a baseline: what you'd score by always giving the most common answer from the dev split.

| | dev | test | always guessing (test) |
|---|---|---|---|
| Sim, bug vs feature (reporter's choice) | 89% | 90% | 69% |
| Kubernetes kind | 90% | 89% | 65% |
| Kubernetes priority, v1 | 22% | 24% | 44% |
| Kubernetes priority, v2 | 26% | 33% (95% CI 24 to 43) | 44% |
| Kubernetes owning SIG | 81% | 79% | 82% |

On Kubernetes priority, v1 rated 106 of 138 dev issues more urgent than the triagers did, and rated only 2 less urgent. It treated failing tests as critical-urgent (the Kubernetes guide lists "tests" as an example of critical-urgent, and the model took that literally), and it answered "backlog" once in 138 issues. For v2 I kept the rubric as it was and added calibration from dev only: how often each level is used, that a failing test alone isn't critical-urgent, and to pick the lower level when unsure. Within-one-level accuracy on test went from 70% to 87%, and exact accuracy from 24% to 33%. I stopped there. The remaining gap looks like information that isn't in the issue text, such as what the SIG is working on this release, and tuning further would mean fitting to the test set.

The model is very stable: it gives the same answer on 97 to 100% of repeated runs.

## What each checker catches

I took outputs that were correct (they passed every check and matched every field that has an answer key) and broke them in 12 specific ways, then asked each checker to find the problem. The Sim Evaluator column is a single run per input, flagged if any metric scored 3 or lower out of 5.

| Kind of mistake | My checks, Sim | Evaluator, Sim | My checks, K8s | Evaluator, K8s |
|---|---|---|---|---|
| Invented version or number in the summary | 100% | 100% | 100% | 100% |
| Missing field | 100% | 100% | 100% | 100% |
| Extra field | 100% | 86% | 100% | 85% |
| Badly formatted value | 100% | 99% | 100% | 100% |
| Summary copied from another issue | 58% | 100% | 65% | 100% |
| Invented tool or service name | 40% | 99% | 48% | 100% |
| Random wrong category | 41% | 99% | 9% | 94% |
| Wrong category that sounds plausible | 17% | 97% | 0% | 91% |
| Wrong owning area | 2% | 93% | 0% | 94% |
| Summary with its meaning flipped | 0% | 100% | 0% | 91% |
| needs_human flipped | 9% | 100% | 26% | 56% |
| Priority off by one level | 0% | 88% | 12% | 41% |

Sample sizes: 187 to 202 per row for Sim (79 for flipped meaning) and 33 to 34 per row for Kubernetes (11 for flipped meaning).

Before running it, I guessed the Evaluator would miss invented details in summaries. That guess was wrong: it caught 99 to 100% of them. Where it struggled was Kubernetes priority (41%) and needs_human (56%), which are the same judgments the triage model gets wrong.

## Real mistakes versus injected ones

Injected mistakes are easy to spot. On the model's actual errors (outputs that disagree with the answer key), the Evaluator caught 54% on Sim (13 of 24) and 41% on Kubernetes (79 of 195). For Kubernetes issues where priority was the only thing wrong, it caught 44 of 134. The judge seems to share the triage model's sense of what is urgent, so a model checking a model doesn't correct that; only the maintainers' answers show it. My deterministic checks caught almost none of the real errors, which is expected, since those were judgment calls and not formatting problems.

## False alarms, checked by hand

The Evaluator flagged 37% of clean Sim outputs and 29% of clean Kubernetes outputs. Many of those flags were on fields that have no answer key, so I reviewed a sample blind, without seeing the scores or which items were flagged:

- summaries the Evaluator called unfaithful: 0 of 8 were actually wrong
- triage calls it flagged: 2 of 15 were clearly wrong
- triage calls it didn't flag (for comparison): 1 of 15 were clearly wrong

Using a cutoff of 2 instead of 3 cuts false flags on clean outputs to 17% (Sim) and 9% (Kubernetes), but detection of injected mistakes drops to 75% and 71%. The full sweep is in the report.

## What I learned about Sim's issue queue

- Sim's `bug` and `feature` labels are applied by the issue templates. Only 1 of 311 issues had a label added by anyone other than the reporter, so the queue is effectively untriaged by humans.
- In the 24 cases where the model and the reporter disagreed, I reviewed each issue blind. The reporter's template choice was wrong in 14, and 12 of the 24 were really questions filed through the bug form. Scored against that reviewed key, bug-vs-feature accuracy is 95% on both dev and test.
- The templates also give the answer away. Headings like "Describe the bug" tell a model which template was used, so I strip everything a template inserts automatically and keep everything a person typed.

## Using Sim as a customer

I kept a dated list of everything confusing or surprising: [FRICTION.md](FRICTION.md). The main ones:

- On a self-hosted install, every logged run cost includes a fixed $0.005 base charge even though billing is off. For a Haiku triage run, that's about 3.4x the real model cost ($0.0070 logged vs $0.0020 billed).
- The logs API can report `completed` before the log is final: once without an end time, and once, in 24% of runs, without the cost breakdown, which is written about 17ms later.
- The Evaluator block's docs describe a different default model and settings than the code. Temperature and the system prompt are hidden and fixed. Its prompt asks for "only scores", yet it averaged 683 output tokens, so each check cost about $0.012, 2.5x what a single test call suggested.
- The Agent block's temperature slider sits under "Show additional fields" and defaults to 0.3.
- Batch calls at modest concurrency got `429 RATE_LIMITED` responses (156 of 1,077 calls in the first batch), even though Sim's self-hosting docs say installs with billing disabled run with no rate limits. Sim's server logs showed the cause: a fixed pre-auth limit on the v2 API of 600 requests, then 300 per minute, per client IP (`v2:preauth:ip:172.19.0.1`). It ignores the billing setting and has no config variable, and on Docker every request from the host shares the gateway IP. I reproduced it with 800 requests: the first 600 got 401 (fake key) and the rest got 429.
- Sim's structured output enforces the allowed values but not string length. One summary came back at 166 characters against a 160 limit, and my schema check caught it.

## What broke in my own checker

My check for invented names flagged 11 real summaries, and only 2 were real problems. Six were formatting (`Stripe-only`, `Manager's`, `Next.js` versus "nextjs", an error code with a colon dropped), which I fixed with a test pinned to each real case. The fix didn't change how many injected invented names it catches. The other three need meaning, not string matching ("Windows" versus "Win11", "SSL" versus "local issuer certificate"), and I've left them as a known limit. Every bug I found in my own code is in [BUGS_FOUND.md](BUGS_FOUND.md), including a template-stripping pass that missed variants and a crash on real Sim logs. Every design decision, and every change made after results came in, is in [PROTOCOL.md](PROTOCOL.md).

## Cost

About $44 in model spend for everything: roughly $6 for about 2,300 triage runs across v1 and v2, and $38.69 for 3,121 Evaluator checks. Median triage latency was 1.6 to 1.7 seconds per issue. I had planned 3 Evaluator runs per input and cancelled runs 2 and 3 once the real cost per check came in 2.5x over my estimate, so the Evaluator numbers are single runs.

## What this doesn't show

One workflow design, two issue sets, a self-hosted install rather than Sim Cloud, and one triage model. The Sim answer key is the reporter's own choice, not an expert's. The Kubernetes kind and SIG labels are mostly reporter-set; only priority comes from triagers, and they may have seen discussion the model never saw. The human reviews were done by one person (me). The Evaluator results are single runs, so I can't say how often it would change its mind on a second try.

## Running it

```bash
uv sync
uv run pytest                                          # includes a test pinned to each real failure found
uv run simtriage report --dataset k8s --version v2 --split test
```

Every number in the report is rebuilt offline from committed files, with no API keys. `simtriage report` exits 0 on pass, 1 below `--fail-under`, 2 on bad usage, and 3 when there's no data, so it can gate CI. [docs/BUILD_WORKFLOWS.md](docs/BUILD_WORKFLOWS.md) covers building the Sim workflows and running everything live.

## Next

- Deploy the Sim workflow on a GitHub webhook, so new issues get triaged as they're opened.
- Give the triage model some project context (open milestones, recent similar issues) and see whether that closes the priority gap that prompting alone didn't.

Data sources and licenses: [data/ATTRIBUTION.md](data/ATTRIBUTION.md).
