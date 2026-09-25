# Building the Sim workflows

Build these in the Sim canvas, as a customer would. There are three: one
triage workflow per customer (`sim-triage`, `k8s-triage`) and one shared
`triage-evaluator`. Each answer key is built from existing human decisions and
committed before any output exists (the runner refuses to run otherwise).

## 1. `sim-triage` and `k8s-triage`

Build the same shape twice. Only the prompt and the response format differ.

1. Create a workflow named `sim-triage` (then `k8s-triage`).
2. **Start** block, two inputs, both type String and **no default value**
   (a default would mask missing input): `title` and `body`.
3. **Agent** block (the plain "Agent", not "Claude Managed Agents"), connected
   from Start:
   - Model: `claude-haiku-4-5`
   - API key: `{{ANTHROPIC_API_KEY}}`
   - System prompt: paste all of `prompts/<sim|k8s>/triage_v1.md`
   - User message:
     ```
     TITLE: <start.title>

     BODY:
     <start.body>
     ```
   - Temperature: **0**. Left empty, Sim uses 0.7.
   - Response format: paste `prompts/<sim|k8s>/response_format.json`
   - No tools, memory off.
4. Click Run in the editor with the text of any **dev** issue (never a test issue), then Deploy.
5. The workflow ID is the last part of the editor URL. Then:
   ```bash
   export SIM_SIM_WORKFLOW_ID=paste-id    # and SIM_K8S_WORKFLOW_ID for k8s-triage
   ```
6. Smoke test on 3 **dev** issues, one repeat, into a throwaway version tag
   (never smoke-test on test issues; seeing test outputs while tuning leaks them
   into the prompt):
   ```bash
   uv run simtriage run --dataset sim --version smoke --split dev --limit 3 --repeats 1
   ```

## 2. `triage-evaluator`

1. Create a workflow named `triage-evaluator`.
2. **Start** block, three String inputs with no defaults: `rubric`, `issue`
   and `triage_output`.
3. **Evaluator** block, connected from Start:
   - Metrics: the three in `prompts/evaluator_metrics.json` (name,
     description, range 1 to 5), entered exactly as written.
   - Content:
     ```
     RUBRIC:
     <start.rubric>

     ISSUE:
     <start.issue>

     TRIAGE OUTPUT:
     <start.triage_output>
     ```
   - Model: leave the default (`claude-sonnet-5` in this image).
   - API key, if it asks: `{{ANTHROPIC_API_KEY}}`.
   - There is nothing else to set. Sim hides the Evaluator's temperature (fixed
     at 0.1) and system prompt (generated from the metrics). That's why the
     rubric goes in through the content.
4. Deploy, then:
   ```bash
   export SIM_EVAL_WORKFLOW_ID=paste-id
   ```

## 3. Export all three definitions

From each workflow's menu, export it and save it to `sim_workflows/`. Check
that the files contain `{{ANTHROPIC_API_KEY}}` and not a real key before
committing.

## Order of the real runs (per dataset: sim, then k8s)

```bash
uv run simtriage run --dataset sim --version v1 --split all     # keyed issues x 3 repeats
uv run simtriage run --dataset sim --version v1 --split queue   # untriaged queue
uv run simtriage mutate --dataset sim --version v1
uv run simtriage evaluate --dataset sim --version v1 --limit 5  # dry run, check scores parse
uv run simtriage evaluate --dataset sim --version v1
uv run simtriage report --dataset sim --version v1 --split test --json report/sim-v1-test.json
```
