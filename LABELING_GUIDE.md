# Labeling guide

The labels are the only independent ground truth in this project. This guide is
frozen by committing it before the first label and before any model output
exists. Changes after that point are listed at the bottom with a reason.

The allowed values below are enforced by `src/simtriage/schema.py`. The labeling
tool won't accept anything else.

## The task

You are the first responder on Sim's GitHub issue queue. For each issue, decide
what it is, how urgent it is, which part of Sim it touches, and whether a
maintainer must look at it now or whether automation can file it. Label what the
issue *says* at the time it was filed. Don't open the GitHub link to check
what happened later.

## category

| value | use when |
|---|---|
| `bug` | Sim behaves wrongly: an error, a crash, wrong output, a broken install or build |
| `feature_request` | A change to existing Sim behavior, UI, limits or config, including code refactors proposed by contributors |
| `integration_request` | A new third-party tool, block, trigger, LLM provider or service |
| `question` | Asks how something works or whether something is intended, without asserting a defect |
| `docs` | The documentation is wrong, missing or unclear, and that's the main complaint |
| `security` | A vulnerability, auth bypass, data exposure or DoS risk, or a follow-up on a security disclosure |
| `invalid` | Spam, empty, off-topic, a bot comment or a misfiled PR review; nothing to act on |

Tie-breakers, applied in this order:
1. Any credible security impact means `security`, even if it's also a bug.
2. "X doesn't work", even when phrased as a question, means `bug`. "Is X supposed to…" with no failure described means `question`.
3. A new external service means `integration_request`. New operations on an integration Sim already has (for example "add threads to the Slack tool") mean `feature_request`.
4. "Docs are missing env var X, so setup fails" means `bug` if setup is broken, or `docs` if setup works and only the docs are wrong.

## priority (ordered low < medium < high < urgent)

| value | use when |
|---|---|
| `urgent` | Security vulnerability, data loss or corruption, or a core path broken for most users (for example the latest image can't start at all) |
| `high` | A bug that blocks the reporter's main use of Sim with no workaround given; any install or self-hosting blocker |
| `medium` | A bug with a workaround or in a narrow feature; a well-argued feature or integration request |
| `low` | Cosmetic issues, speculative ideas, questions, docs nits, invalid |

## product_area

| value | covers |
|---|---|
| `self_hosting` | Docker, Compose, Kubernetes, Helm, env vars, migrations, running a deployed instance |
| `dev_setup` | Building or running from source, devcontainers, tests, contributor tooling |
| `workflow_editor` | The canvas and editor UI: block configuration UI, undo and redo, layout, import and export |
| `execution_engine` | Running workflows: block execution, variables, loops and parallel, function blocks, timeouts, streaming |
| `agents_models` | The Agent block and LLM providers and models |
| `copilot` | Copilot and Mothership chat |
| `integrations` | Third-party tool blocks, OAuth connections, third-party triggers |
| `mcp` | MCP servers, MCP tools |
| `api_deployment` | Deploying workflows, the public API, webhooks, schedules, chat deploy |
| `auth_accounts` | Login, SSO, invites, workspaces, permissions, billing and usage limits, whitelabeling |
| `logs_observability` | Logs, traces, cost tracking, audit trails |
| `other` | None of the above, and every `invalid` issue |

If an issue spans two areas, pick the one a maintainer would route it to first:
the place the fix would most likely go.

## needs_human

`true` means automation should not just apply labels and move on: a maintainer
must look now. This is true for:
- anything `security`
- anything `urgent`
- a `high` bug where the reporter is blocked

It's `false` for:
- a clear bug or request that can be labeled and queued
- a question the docs answer
- spam

## Consistency rules (these become gates)

| id | rule |
|---|---|
| R1 | `needs_human` means priority is not `low` |
| R2 | `security` means `needs_human` and priority `high` or `urgent` |
| R3 | `invalid` means priority `low`, not `needs_human`, product_area `other` |
| R4 | `urgent` means `needs_human` |
| R5 | `integration_request` means product_area `integrations`, `mcp` or `agents_models` |
| R6 | `docs` means priority `low` or `medium` |
| R7 | `question` means priority is not `urgent` |

The tool warns you right away if a label breaks a rule. If a real issue
genuinely calls for the rule-breaking label, keep it. The conflict is recorded,
and that rule gets revised before any model output is seen.

## Summaries

You don't write summaries; the workflow does. Summaries are checked by gates
(see PROTOCOL.md), not against a reference.

## Process

1. Label all 100 issues with `simtriage label`. You can stop and resume at any
   time; it saves after every issue.
2. Don't open `data/maintainer_labels_HIDDEN.jsonl` until all 100 are done.
3. At least 24 hours later, run `simtriage label --recheck 20` to blindly
   relabel 20 seeded-random issues. The agreement rate between the two passes is
   the reliability figure for single-annotator labels.
4. Note anything ambiguous in `notes`. Ambiguous cases are findings, not noise.

## Changes after freeze

(none)
