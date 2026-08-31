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

## What it does (V1 scope)

1. Runs the test suite in `sample_project/` to see what's failing.
2. Reads `calculator.py` to understand the code.
3. Reasons about the actual bug (there's a logic bug in `multiply`).
4. Applies a fix by rewriting the file.
5. Re-runs tests to confirm the fix worked.
6. Reports what it did.

## Architecture

```
agent.py    -> the reasoning loop (Reason -> Act -> Observe -> Repeat)
tools.py    -> the only actions the agent is allowed to take
              (read_file, write_file, run_tests, list_files)
sample_project/ -> the "codebase" the agent works on
```

The agent never executes code or touches files directly — it can only
request tool calls, which Python then executes on its behalf. This is a
deliberate safety boundary.

## Known limitations (by design, for V1)

- Only works on a single hardcoded file, no codebase-wide search
- No sandboxing (tests run directly via subprocess, not Docker)
- No Git integration
- Trusts Claude's "done" signal loosely (mitigated by requiring
  `run_tests` confirmation in the prompt, but not independently verified)

These are exactly the gaps that V2-V5 will address.
