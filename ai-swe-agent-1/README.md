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

## What it does (V2 scope)

The agent is no longer told which file the bug is in. It must:
1. Run the test suite to see what's failing.
2. Read the error (an `AttributeError`, not an obvious wrong-number bug).
3. Recognize it doesn't know enough yet, and use `search_code` to find where
   the relevant class/attribute is actually defined - across files.
4. Read the correct file(s) based on what search turned up.
5. Apply a fix based on real evidence, not a guess.
6. Re-run tests to confirm.

The project now spans three source files (`models.py`, `inventory.py`,
`calculator.py`) plus their tests, so the agent has to figure out *where*
to look, not just *what* to fix.

## Architecture

```
agent.py    -> the reasoning loop (Reason -> Act -> Observe -> Repeat)
tools.py    -> the only actions the agent is allowed to take
              (read_file, write_file, run_tests, list_files, search_code)
sample_project/ -> the "codebase" the agent works on
  models.py       -> Product class (correct)
  inventory.py    -> BUG: references a field that doesn't exist on Product
  calculator.py   -> fixed (was the V1 bug)
```

### Why keyword search instead of embeddings (semantic search)?

This is a genuine engineering trade-off worth understanding, not a shortcut:

- **Keyword/grep search** (what we built): zero extra infrastructure, instant,
  100% predictable/debuggable, and works great when you're searching for an
  exact identifier (a class name, function name, variable) - which is most
  of what debugging actually needs.
- **Embedding/semantic search**: needed when the query and the relevant code
  don't share exact words - e.g. searching "where do we handle user login"
  and the relevant function is named `authenticate_session`. This needs an
  embedding model, a vector store, and ongoing indexing - real infrastructure.

Rule of thumb: reach for embeddings only once you've hit a concrete case
where keyword search actually fails to find something relevant. Adding it
before you have that evidence is complexity you can't yet justify - and
that judgment call is itself something worth being able to explain.

## Known limitations (by design, for V2)

- Search is a single project folder, not a large real-world repo (no
  ignoring node_modules/venv/etc, no chunking large files)
- No sandboxing (tests run directly via subprocess, not Docker)
- No Git integration
- Trusts the model's "done" signal loosely (mitigated by requiring
  `run_tests` confirmation in the prompt, but not independently verified)

These are exactly the gaps V3-V5 will address.
