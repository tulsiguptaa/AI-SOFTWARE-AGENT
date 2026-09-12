# AI Software Engineering Agent (V1)

An autonomous agent that reads a codebase, finds a bug, fixes it, and
verifies the fix by running tests — using an LLM as the reasoning engine
and a controlled set of tools for acting on the filesystem.

## Setup

```bash
# 1. Create a virtual environment
python3 -m venv venv
source venv/bin/activate   # on Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set up your API key
cp .env.example .env
# then edit .env and paste your real Mistral API key

# 4. Run the agent
python3 agent.py
```

## What it does (V4 scope)

Everything from V3, plus **git-aware workflow** - the agent no longer just
overwrites files, it works the way a real engineer does:

1. Creates a new branch BEFORE making any changes (`create_branch`) -
   isolating the fix instead of editing `main` directly.
2. Finds and fixes the bug (same process as V2/V3).
3. Reviews its own change with `git_diff` before committing - a real
   self-check step, not just "trust the model."
4. Commits only once tests pass, with a descriptive message
   (`commit_changes`) - and is explicitly told never to commit a broken
   state.

`sample_project/` is now a real local git repo (see `sample_project/.git`),
so you can inspect the agent's work afterward with normal git commands:

```bash
cd sample_project
git log --all --oneline --graph   # see the branch + commit the agent made
git diff main fix/<branch-name>   # see exactly what it changed
```

**Deliberate scope limit:** only THREE git operations are exposed
(`create_branch`, `git_diff`, `commit_changes`) - not a generic "run any
git command" tool. No `push`, no `reset --hard`, no force operations.
Same safety principle as the filesystem sandbox: the agent can only do
what we've explicitly built a function for.

**Not included in V4** (a natural stretch goal, not required): opening an
actual GitHub pull request via the GitHub API. That needs a real remote
repo and a personal access token, which is easy to add later
(`PyGithub`) but depends on infrastructure outside this local project.

## What it does (V5 scope)

**A real, automated evaluation harness** - `eval/run_eval.py` runs the
agent against multiple independent bug scenarios, fresh each time, and
reports a genuine pass rate instead of a single anecdotal "it worked when
I ran it."

Run it with:
```bash
python3 eval/run_eval.py
```

Three scenarios ship by default, each with a different failure signature:

| Scenario | Bug type | Files | Failure |
|---|---|---|---|
| `inventory` | Cross-file attribute mismatch | 3 | `AttributeError` |
| `playlist` | Single-file logic bug | 2 | `AssertionError` |
| `config_key` | Cross-file wrong dict key | 3 | `KeyError` |

**Critical design principle: the harness never trusts the agent's own
claim of success.** After each run, `verify_success()` independently (a)
actually re-runs the test suite and parses the real result, and (b)
checks git history for a real commit. This is the same "verify, don't
trust the model's narrative" principle behind the auto-complete fix in
V3/V4 - and it's exactly how SWE-bench itself works: ground truth is
always the test suite, never the model's report.

Each scenario runs in a fresh temporary directory (via `tempfile` +
`shutil.copytree`), so results are reproducible and re-running the suite
never accumulates leftover branches or commits between runs.

### Why not full SWE-bench-lite?

This is a deliberate, honest scoping decision worth being able to explain
in an interview, not a shortcut taken silently. Real SWE-bench-lite
involves cloning full open-source repositories and spinning up a
per-task Docker container matching that repo's exact dependency versions,
then running hundreds of real historical GitHub issues against it. That's
genuinely valuable infrastructure, but it's a significant lift - not
something to bolt on casually, especially on a free-tier API budget where
each task can take many LLM calls.

**What this project does instead** is directly SWE-bench-*inspired* at
smaller scale: independent tasks, known ground truth, automated pass/fail
scoring, no trust in the model's self-report. If you wanted to extend
this into the real thing, the natural next steps are:
1. Add Docker sandboxing to `run_tests()` (already flagged as a known
   limitation below) so each scenario can have totally different,
   isolated dependencies.
2. Pull a handful of real tasks from the actual SWE-bench-lite dataset
   (huggingface.co/datasets/princeton-nlp/SWE-bench_Lite) as additional
   scenario folders, following the same `verify_success()` pattern.
3. Swap the fixed 3-scenario loop for a proper test runner that can scale
   to dozens/hundreds of tasks and report per-category breakdowns.

Being able to describe this path - even without having built it - is
itself a legitimate, resume-relevant signal that you understand what a
production-grade evaluation actually requires.

## Architecture

```
agent.py    -> run_agent_events() is a GENERATOR yielding structured events
              (the single source of truth for the loop's logic); run_agent()
              is a thin terminal wrapper that prints those events - see
              "Web UI" below for the second consumer of the same generator
tools.py    -> the only actions the agent is allowed to take, plus
              set_project_root() so the eval harness/web UI can point the
              same tools at different project directories, and
              ensure_git_repo() / reset_sample_project() for bootstrapping
test_agent_logic.py -> unit tests for the harness logic (no API needed)
sample_project/ -> the "codebase" the agent works on interactively
eval/
  run_eval.py        -> the evaluation harness (terminal)
  test_eval_logic.py -> unit tests for compute_summary() (no API needed)
  scenarios/
    inventory/    -> cross-file AttributeError
    playlist/     -> single-file logic bug (AssertionError)
    config_key/   -> cross-file KeyError
web/
  server.py            -> Flask app: serves the UI + 2 SSE streams (live
                          run, eval suite) by consuming run_agent_events()
  test_server_logic.py -> unit tests for SSE formatting (no API needed)
  templates/index.html, static/style.css, static/app.js -> the browser UI
```

### Six known real bugs fixed while building this (worth understanding, not skipping)

1. **`mistralai` v2 import path changed.** Most tutorials show
   `from mistralai import Mistral`; the installed v2.x SDK requires
   `from mistralai.client import Mistral`. Always check a package's actual
   installed version/changelog when an import fails instead of assuming
   your reference material is current.
2. **Module-level client creation blocked testability.** Creating the API
   client as soon as `agent.py` was imported meant even pure-logic unit
   tests needed a real API key. Fixed with lazy initialization
   (`get_client()`), a standard pattern for decoupling side effects from
   logic you want to test in isolation.
3. **Hardcoded `python3` broke on Windows.** `subprocess.run(["python3", ...])`
   assumes a Unix-style command name that often doesn't exist on Windows.
   Fixed with `sys.executable`, which always points to the exact Python
   interpreter currently running - portable across OSes and guaranteed to
   match your virtual environment.
4. **Scope creep: the agent created and committed an unrequested file.**
   On a real run, the agent fixed the actual bug correctly, but also wrote
   a scratch file (`manual_test.py`, using `print()` statements instead of
   real assertions) to "double check" unrelated code that wasn't broken -
   and committed it alongside the real fix. Telling the model in the
   prompt to "keep the diff minimal" was a weak guardrail; it didn't
   reliably self-critique its own diff. The real fix was a strong,
   code-level guardrail: `write_file` now refuses to create new files at
   all, only allowing edits to files that already exist. This closes the
   failure mode regardless of what the model decides to do - a good
   general lesson: prefer guardrails the code enforces over guardrails
   the prompt merely requests.
5. **Hitting `MAX_ITERATIONS` even when the task was already done.**
   Increasing the iteration limit (even to 30) didn't fix this - it just
   delayed it, because the real problem wasn't "not enough iterations."
   The agent would sometimes finish the actual work (tests passing, fix
   committed) but keep exploring anyway, because *the model itself* decides
   when to stop, and that judgment call is unreliable (same root cause as
   the scope-creep bug). The real fix: the harness now parses `run_tests`
   output itself (`parse_test_result`) and tracks whether the last commit
   succeeded. The moment both are true - tests passing AND fix committed -
   the loop force-stops immediately, regardless of what the model does
   next. This is a recurring pattern worth internalizing: don't build a
   softer prompt asking the model to behave a certain way when you can
   instead have your own code verify the actual state and enforce it.
6. **`__pycache__`/`.pyc` files got committed by the eval harness.** The
   same noisy-diff bug from V4 recurred, but in a new place: fresh eval
   scenario folders didn't have their own `.gitignore`, so the first
   scenario's commit picked up compiled bytecode files. Fixed by having
   `prepare_scenario()` write a `.gitignore` into every temp copy before
   `git init`, regardless of whether the scenario source folder happened
   to include one - a reminder that a fix made in one place (V4's
   `sample_project/.gitignore`) doesn't automatically protect new code
   paths that didn't exist yet when you made it.

## Web UI (V6)

A browser-based console for watching the agent work live, instead of
reading a terminal scroll - laid out like a real IDE, not a plain log.

Run it with:
```bash
python3 web/server.py
```
Then open **http://localhost:5000**.

**Live Run tab** is a 3-pane workspace:
- **File explorer** (left) - every file in `sample_project/`, with a
  small dot that lights up amber when the agent reads it, and solid amber
  when it writes to it - so you can see exactly what it's touching, not
  just read about it in a log.
- **Code viewer** (center) - shows the actual current contents of
  whichever file the agent is working on, with real Python syntax
  highlighting (via highlight.js), auto-opening and refreshing live as
  the agent reads and edits files. A "modified this run" badge appears
  on files the agent has changed.
- **Activity feed** (right) - the same event stream as before, but tool
  results over 150 characters now collapse behind a `<details>` toggle
  instead of dumping a wall of text.

A slim toolbar above the workspace shows the **current git branch**
(updates live the moment `create_branch` runs), **iteration progress**
(a bar reflecting iteration / `MAX_ITERATIONS`), and **live test status**.

**Evaluation tab** - unchanged from before: runs the full 3-scenario
benchmark from the browser, with each scenario's card updating live.

### New backend endpoints powering the file explorer

`GET /api/files` lists every file in `sample_project/`;
`GET /api/file/<filename>` returns one file's contents. Both reuse
`tools.read_file()` directly rather than reimplementing file access - so
the UI can never see anything the agent itself couldn't, and the same
path-traversal guardrail from V1 (`_safe_path`) protects these endpoints
automatically, with zero new code needed to keep that safe.

### How the file explorer follows the agent's actions correctly

An early version of this tried to guess which file a `write_file` result
was about by looking at "whichever file happens to be open in the
viewer" - which breaks the moment the agent reads one file and writes to
a different one in the same iteration. The correct fix: `tool_call` and
`tool_result` events are always emitted as an immediate pair for the
same call (see `run_agent_events`), so the frontend tracks the filename
from the `tool_call` event and uses that exact value when its paired
`tool_result` arrives - no guessing, no state that can drift out of sync.

### A bug this surfaced: the browser silently started a second concurrent run

Working perfectly in the terminal but hitting rapid rate-limit errors
only in the browser was the symptom of a genuinely subtle bug: browsers
automatically try to reconnect a Server-Sent Events connection whenever
it closes - including a completely NORMAL close, like the agent finishing
successfully - unless something tells them not to. The frontend does call
`.close()` when it sees the final `"stopped"` event, but there's a race:
the browser can notice the connection ended before that callback runs, and
silently reconnect anyway, starting a **second, fully independent agent
run** in the background. That doubles the real API request rate without
any visible sign of it happening - which is exactly why it looked fine in
the terminal (a single sequential process, no browser involved) but broke
in the browser.

The fix follows this whole project's core pattern one more time: don't
depend on client-side timing behaving perfectly - enforce the actual
constraint in the server. `web/server.py` now holds a single shared lock
(`try_start_run()` / `finish_run()`) across BOTH the live-run and
evaluation-suite streams. A second request - whether from an accidental
browser reconnect, a double click, or two tabs open on the same page -
gets an immediate `"already_running"` response instead of silently
starting a competing run. `web/test_server_logic.py` verifies this holds
under a genuine race condition using real threads, not just sequential
calls, since a lock that only works when called one-at-a-time isn't
actually proving anything about concurrency safety.

### How this was built without duplicating the agent's logic

The agent loop (`agent.run_agent_events`) is a **generator that yields
structured events** instead of printing - `{"type": "tool_call", ...}`,
`{"type": "stopped", "reason": "auto_complete", ...}`, etc. Both the
terminal script and the web server consume this exact same generator;
they just render its events differently (`print()` vs. Server-Sent
Events to a browser). This is the same principle behind
`check_stagnation()` and `parse_test_result()` being pure, testable
functions, applied one level up: **the loop's logic doesn't know or care
how its progress gets displayed.** Adding the web UI required zero
changes to how the agent actually behaves.

`web/server.py` is a small Flask app with 5 routes: serve the page, report
live status, reset the demo, and two Server-Sent Event streams (a live
run, and the full eval suite). `web/test_server_logic.py` unit-tests the
SSE formatting function with no server or API key needed - same testing
discipline as the rest of the project.

### A bug this surfaced: the demo git repo doesn't survive a GitHub push

Pushing this project to GitHub meant removing `sample_project/.git` (a
nested repo would show up as a broken submodule link). But that also
meant a fresh clone had **no git history at all** - `create_branch` would
fail on the very first run. Fixed with `tools.ensure_git_repo()`, called
automatically at the start of every agent run: if `sample_project` isn't
already a git repo, it initializes one on the spot. The tool is now
self-healing regardless of whether you're running it for the first time
ever or the hundredth - a better fix than the alternative of shipping the
git history and accepting the broken-submodule-link problem.

### A bug the web UI surfaced: free-tier rate limits crashed the whole run

Running against a free-tier Mistral key, `run_tests` and other steps
happen fast enough that the API sometimes returns `429 Rate limit
exceeded`. Before this fix, that exception was unhandled - it crashed the
Python generator mid-stream, which killed the SSE connection and showed
up in the browser as an unexplained "connection lost," with the real
cause buried in the terminal.

Two separate fixes, for two separate problems:
1. **Automatic retry with backoff** (`call_model_with_retry`): a 429 is a
   *transient* condition, not a real failure, so it's retried
   automatically (3s, 6s, 12s...) rather than surfaced as an error at all.
2. **Any error that survives retries becomes a clean event, not a crash**:
   `run_agent_events` catches it and yields a normal `stopped` event with
   `reason: "api_error"`, so both the terminal and the web UI can show a
   clear, specific message instead of dying silently.

This is the same lesson as the auto-complete and scope-creep fixes,
applied to infrastructure instead of agent behavior: don't let a
transient, expected condition (a rate limit) look like a fundamental
crash - handle it explicitly, and make the failure mode visible and
specific when it does happen for real.

## Known limitations (by design, for V6)

- No GitHub/remote integration (no push, no PR) - local git only.
- Stagnation detection only catches *exact* repeats, not "different action,
  same underlying mistake."
- No sandboxing (tests run directly via subprocess, not Docker) - fine for
  these small, dependency-free scenarios, but a real blocker for scaling
  to arbitrary real-world repos with their own dependencies.
- Only 3 evaluation scenarios, all Python, all small, single-repo. Real
  SWE-bench-lite spans many repos, languages of dependency (not code
  language), and much larger codebases.
- The web UI supports one run at a time, no user accounts or multi-session
  support - fine for a personal local tool, a real blocker if you wanted
  multiple people using it concurrently (Flask's dev server is also not
  meant for production use as-is).

These are exactly the gaps you'd close next if you kept extending this
into a portfolio-grade project - see "Why not full SWE-bench-lite?" above
for the concrete path.
