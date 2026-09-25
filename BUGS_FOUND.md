# Bugs found in my own tooling

Dated. "Pre-output" means caught before any triage output existed; those can't
have been fitted to the results. Real failures found by running against Sim are
listed separately, and each gets a pinned regression test.

## Pre-output

- 2026-09-24, sampler (synthetic draft, later discarded): `groupby().apply`
  dropped the grouping column under current pandas, so 28 of 40 tickets lost
  their queue and the stratification silently collapsed to 4 queues. Caught
  because the printed queue count (4) didn't match the known 10.
- 2026-09-25, sampler: the email-redaction regex matched npm versions like
  `pkg@1.1.2`, and would have erased version numbers the summary gate depends
  on. Every match turned out to be a placeholder (example.com), Sim's own
  address, or a version; there were zero personal emails. Redaction is now
  limited to personal domains.
- 2026-09-25, environment: the editable install broke with
  `ModuleNotFoundError`. In an iCloud-synced `~/Documents`, a background
  process sets the macOS `hidden` flag on `.venv` about 30 seconds after
  install, and Python 3.12.13 skips hidden `.pth` files. Fix: the real venv is
  `.venv.nosync` (iCloud ignores `.nosync`), with `.venv` as a symlink; tests
  also use `pythonpath = src`. Confirmed by watching the flag for 90 seconds
  before and after.
- 2026-09-25, `summary_handles` gate: it required the literal text `#1373` in
  the issue, so a summary citing an issue linked as `.../issues/1373` would
  have been a false failure. Caught by the gate's own unit test. It now checks
  the number.

## Found against real outputs

(none yet)
