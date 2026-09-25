# sim-triage-eval

I built an issue triage workflow on [Sim](https://github.com/simstudioai/sim), deployed it as an API on a self-hosted install, and then built the eval loop around it that I'd want if a customer were putting this into production. That means deterministic checks that don't call a model, mutation testing to see what those checks actually catch, and a side-by-side comparison with Sim's own Evaluator block.

This is still in progress. The first round of results is below, and the Evaluator comparison is running now.

## What's here

Two "customers", one eval system:

- **Sim's own issue queue.** 307 real issues from simstudioai/sim. The answer key is the reporter's own choice of the "Bug report" or "Feature request" template. 75 issues have no label at all and form an untriaged queue that the workflow handles as it would in production.
- **Kubernetes.** 229 issues from kubernetes/kubernetes where the priority label was set by a triager, not by the person who filed the issue. I checked each one against the `/priority` comment that set it. The rubric is Kubernetes' own published triage guide.

For each customer there's a workflow built in the Sim canvas (Claude Haiku 4.5, structured output, temperature 0), deployed and called only through Sim's API. Every issue ran 3 times.

## Results so far (v1 prompt)

Every accuracy number comes with a baseline: what you'd score by always giving the most common answer.

| | dev | test | always guessing |
|---|---|---|---|
| Sim, bug vs feature (reporter's choice) | 89% | 90% | 68% |
| Kubernetes, kind | 90% | 89% | 62 to 65% |
| Kubernetes, priority (set by triagers) | 22% | 24% | 44% |
| Kubernetes, owning SIG | 81% | 79% | 82 to 91% |

The Kubernetes priority result is the interesting one. The model does worse than always answering "important-longterm", because it rates almost everything as more urgent than the maintainers did. Of 61 dev issues the triagers marked important-longterm, it called 56 "important-soon" or "critical-urgent". It answered "backlog" once in 138 issues. It isn't random, though: 65 to 70% of its answers are within one level, and it gives the same answer on 97 to 100% of repeated runs. So this looks like a calibration problem a prompt change should be able to fix, which is what v2 is for.

The owning-SIG number is below its baseline too, because 249 of the 325 raw Kubernetes issues belong to SIG Node. Without the baseline, 81% would look fine.

Latency is about 1.6 to 1.7 seconds per issue at the median, and the model cost is about $0.0021 to $0.0027 per issue.

## What my checks catch

The deterministic checks (schema, consistency rules, and summary checks for invented numbers, URLs, handles and names) never call a model. To see what they actually catch, I took outputs that were correct and broke them on purpose in 12 different ways, then ran the checks without an answer key:

| Kind of mistake | Sim | Kubernetes |
|---|---|---|
| Invented version or number in the summary | 100% | 100% |
| Missing field, extra field, badly formatted value | 100% | 100% |
| Summary copied from a different issue | 58% | 65% |
| Invented tool or service name in the summary | 40% | 48% |
| Wrong category that sounds plausible | 17% | 0% |
| Summary with its meaning flipped ("fails" becomes "works") | 0% | 0% |

So the cheap checks are very good at invented specifics and structure, and blind to anything that needs judgment. The open question is whether Sim's Evaluator covers those blind spots. That run is going now, over about 3,100 inputs with 3 runs each.

## Things that surprised me

- Sim's `bug` and `feature` labels are applied by the issue templates. Only 1 of 311 issues had a label added by anyone other than the reporter, so there's no maintainer answer key to measure against, and the queue is effectively untriaged by humans.
- The templates give away the answer. Headings like "Describe the bug" or "What would you like to be added?" tell a model which template was used, so I strip everything a template inserts automatically and keep everything a person typed.
- Sim's structured output enforces the allowed values but not string length. One Kubernetes summary came back at 166 characters against a 160 limit, and the schema gate caught it.

## Using Sim as a customer

I kept a dated list of everything that was confusing or surprising while doing this: [FRICTION.md](FRICTION.md). A few examples:

- On a self-hosted install, every logged run cost includes a fixed $0.005 base charge, even though billing is off. For a short Haiku run, that's about 3.8x the real model cost.
- The logs API can say `completed` before the log is final. Once it's missing the end time, and once it's missing the cost breakdown, about 20ms later.
- The Evaluator block's docs describe a different default model and settings than the code actually has.
- A batch of API calls at modest concurrency ran into a rate limit that isn't documented for self-hosted installs.

## Mistakes in my own tooling

[BUGS_FOUND.md](BUGS_FOUND.md) lists every bug I found in my own code, with dates, including ones that would have quietly skewed the results (a template-stripping pass that missed variants, a coarse-vs-fine category mix-up, a crash on real Sim logs). The design decisions and anything changed after results came in are in [PROTOCOL.md](PROTOCOL.md).

## Still to do

- Finish the Evaluator comparison and put it next to the table above.
- Review by hand every flagged summary, and every Sim issue where the model and the reporter disagree. That review is blind to what either side said.
- v2 prompt: fix the priority calibration using dev errors only, then rerun dev and test once.
- Deploy the workflow on a GitHub webhook so new issues get triaged as they're opened.

## Running it

```bash
uv sync
uv run pytest                                   # includes one test pinned to each real failure found
uv run simtriage report --dataset k8s --version v1 --split test
```

Everything in the report is rebuilt offline from committed files, with no API keys needed. `simtriage report` exits 0 on pass, 1 below `--fail-under`, 2 on bad usage, and 3 when there's no data, so it can gate CI. [docs/BUILD_WORKFLOWS.md](docs/BUILD_WORKFLOWS.md) covers building the Sim workflows and running everything live.

## What this doesn't show

One workflow design, two issue sets, a self-hosted install and not Sim Cloud, and one model. The Sim answer key is the reporter's own choice, not an expert's. The Kubernetes kind and SIG labels are mostly reporter-set too; only priority is set by triagers, and triagers may have seen discussion the model never saw.

Data sources and licenses: [data/ATTRIBUTION.md](data/ATTRIBUTION.md).
