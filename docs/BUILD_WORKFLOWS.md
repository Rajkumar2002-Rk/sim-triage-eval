# Building the two Sim workflows

Build these in the Sim canvas, as a customer would. **Do this after labeling
is complete.** Seeing model triage output first, even on practice issues,
could anchor your labels.

## 1. `issue-triage`

1. Create a workflow named `issue-triage`.
2. **Start** block, two inputs, both type String and **no default value**
   (a default would mask missing input): `title` and `body`.
3. **Agent** block (the plain "Agent", not "Claude Managed Agents"), connected
   from Start:
   - Model: `claude-haiku-4-5`
   - API key: `{{ANTHROPIC_API_KEY}}`
   - System prompt: paste all of `prompts/triage_v1.md`
   - User message:
     ```
     TITLE: <start.title>

     BODY:
     <start.body>
     ```
   - Temperature: **0**. Left empty, Sim uses 0.7.
   - Response format: paste `prompts/response_format.json`
   - No tools, memory off.
4. Click Run in the editor with any practice issue's text, then Deploy.
5. The workflow ID is the last part of the editor URL. Then:
   ```bash
   export SIM_TRIAGE_WORKFLOW_ID=paste-id
   ```
6. Smoke test on the 8 out-of-sample practice issues, one repeat each:
   ```bash
   uv run simtriage run --issues data/practice_issues.jsonl --split all --version practice --repeats 1
   ```

## 2. `triage-evaluator`

1. Create a workflow named `triage-evaluator`.
2. **Start** block, two String inputs with no defaults: `issue` and
   `triage_output`.
3. **Evaluator** block, connected from Start:
   - Metrics: the three in `prompts/evaluator_metrics.json` (name,
     description, range 1 to 5), entered exactly as written.
   - Content:
     ```
     ISSUE:
     <start.issue>

     TRIAGE OUTPUT:
     <start.triage_output>
     ```
   - Model: leave the default and record what it is.
   - Advanced: temperature **0**, system prompt: paste all of
     `prompts/evaluator_system.md`.
   - API key, if it asks: `{{ANTHROPIC_API_KEY}}`.
4. Deploy, then:
   ```bash
   export SIM_EVAL_WORKFLOW_ID=paste-id
   ```

## 3. Export both definitions

From each workflow's menu, export it and save it to `sim_workflows/`. Check
that the files contain `{{ANTHROPIC_API_KEY}}` and not a real key before
committing.

## Order of the real runs (after labeling)

```bash
uv run simtriage run --version v1 --split all        # 100 issues x 3 repeats
uv run simtriage mutate --version v1
uv run simtriage evaluate --version v1 --limit 5     # dry run, check scores parse
uv run simtriage evaluate --version v1               # full run
uv run simtriage report --version v1 --split test --json report/v1-test.json
```
