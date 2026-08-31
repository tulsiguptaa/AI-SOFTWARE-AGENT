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

## Architecture

```
agent.py    -> the reasoning loop + stagnation detection + git-aware prompt
tools.py    -> the only actions the agent is allowed to take:
              read_file, write_file, run_tests, list_files, search_code,
              create_branch, git_diff, commit_changes
test_agent_logic.py -> unit tests for the harness logic (no API needed)
sample_project/ -> the "codebase" the agent works on (now a real git repo)
  models.py       -> Product class (correct)
  inventory.py    -> BUG: references a field that doesn't exist on Product
  calculator.py   -> fixed (was the V1 bug)
```

### Two known real bugs fixed while building this (worth understanding, not skipping)

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

## Known limitations (by design, for V4)

- No GitHub/remote integration (no push, no PR) - local git only.
- Stagnation detection only catches *exact* repeats, not "different action,
  same underlying mistake."
- No sandboxing (tests run directly via subprocess, not Docker).

These are exactly the gaps V5 (evaluation on SWE-bench-lite) will surface
at scale - and where you'd naturally add Docker sandboxing and PR
automation if you kept extending this into a portfolio-grade project.
