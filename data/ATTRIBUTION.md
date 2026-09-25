# Data attribution

## Sim (`data/sim/`)
`raw/issues_2026-09-25.json` is a snapshot of the public GitHub issues of
https://github.com/simstudioai/sim (Apache-2.0 code), taken with
`scripts/fetch_sim.sh`. `raw/label_events_2026-09-25.json` holds each issue's
label history (who applied which label), used to establish that the labels were
set by reporters through templates.

## Kubernetes (`data/k8s/`)
`raw/issues_2026-09-25.json` is a snapshot of public issues from
https://github.com/kubernetes/kubernetes (Apache-2.0 code) that carry a
`priority/*` label and were created on or after 2025-08-01, with their comments
and label events, taken with `scripts/fetch_k8s.py`. The priority definitions in
`prompts/k8s/rubric.md` paraphrase the Kubernetes issue-triage guide
(https://github.com/kubernetes/community/blob/master/contributors/guide/issue-triage.md).

Issue text belongs to the people who wrote it and is used here only as
evaluation input. Template text and bot commands are stripped as documented in
the build scripts; nothing else is changed. If you wrote one of these issues and
want it removed, open an issue on this repo and it will be dropped and the
results regenerated.
