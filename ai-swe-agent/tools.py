"""
tools.py

These are the ONLY actions the agent is allowed to take. This is deliberate:
an LLM should never get raw shell access to your machine. Every capability
we give it is a function we wrote, with limits we control.

For V1 we keep this simple: read a file, write a file, run the test suite.
Later (V3+) we'll add sandboxing (Docker) so run_tests() can't do anything
dangerous even if the agent goes off the rails.
"""

import subprocess
import sys
from pathlib import Path

# Restrict the agent to only this folder. This is a basic guardrail —
# without it, a prompt-injected or confused agent could try to read/write
# files anywhere on your system.
PROJECT_ROOT = Path(__file__).parent / "sample_project"


def _safe_path(filename: str) -> Path:
    """Resolve a filename to an absolute path INSIDE project_root, or raise.
    This stops path traversal like '../../etc/passwd'."""
    target = (PROJECT_ROOT / filename).resolve()
    if not str(target).startswith(str(PROJECT_ROOT.resolve())):
        raise ValueError(f"Access denied: {filename} is outside the project sandbox")
    return target


def read_file(filename: str) -> str:
    """Read and return the contents of a file in the sample project."""
    try:
        path = _safe_path(filename)
        return path.read_text()
    except Exception as e:
        return f"ERROR reading {filename}: {e}"


def write_file(filename: str, content: str) -> str:
    """Overwrite an EXISTING file in the sample project with new content.

    Deliberately does NOT allow creating new files. This is a direct
    response to a real failure we observed: the agent once created an
    unrequested 'manual_test.py' scratch file and committed it alongside
    a real fix. Telling the model "don't create unrelated files" in the
    prompt is a weak guardrail - it's just a suggestion. Making file
    creation impossible at the tool level is a strong guardrail: the
    failure mode can't happen regardless of what the model decides to do.
    If the agent genuinely needs a new file for a legitimate reason, that's
    a deliberate design choice you'd add back with its own explicit tool
    (e.g. create_new_file) rather than overloading write_file to do both."""
    try:
        path = _safe_path(filename)
        if not path.exists():
            return (
                f"ERROR: '{filename}' does not exist. write_file can only modify "
                f"existing files, not create new ones. If you believe a new file "
                f"is genuinely necessary, explain why in your response instead of "
                f"creating it."
            )
        path.write_text(content)
        return f"Successfully wrote {len(content)} characters to {filename}"
    except Exception as e:
        return f"ERROR writing {filename}: {e}"


def run_tests() -> str:
    """Run the pytest suite inside the sample project and return the output.
    This is how the agent 'observes' whether its fix worked."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-v", "--tb=short"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=30,  # guardrail: never let a test hang forever
        )
        output = result.stdout + result.stderr
        return output[-4000:]  # keep it small so we don't blow the context window
    except subprocess.TimeoutExpired:
        return "ERROR: tests timed out after 30 seconds (possible infinite loop)"
    except Exception as e:
        return f"ERROR running tests: {e}"


def list_files() -> str:
    """List all files in the sample project so the agent knows what exists."""
    files = [f.name for f in PROJECT_ROOT.iterdir() if f.is_file()]
    return "\n".join(files)


def search_code(query: str) -> str:
    """Search all .py files in the project for a keyword/substring and return
    matching lines with their file name and line number - like a basic grep.

    This is intentionally simple (plain substring matching, case-insensitive)
    rather than semantic/embedding search. For V2 that's a feature, not a
    corner cut: it's fast, needs zero extra infrastructure, and is completely
    predictable to debug. We upgrade to embeddings only when keyword search
    genuinely stops being good enough (see README for when that trade-off flips)."""
    matches = []
    query_lower = query.lower()
    for path in sorted(PROJECT_ROOT.glob("*.py")):
        for line_num, line in enumerate(path.read_text().splitlines(), start=1):
            if query_lower in line.lower():
                matches.append(f"{path.name}:{line_num}: {line.strip()}")

    if not matches:
        return f"No matches found for '{query}'"
    return "\n".join(matches[:50])  # cap results so we don't blow the context window


# --- Git tools ------------------------------------------------------------
# Deliberately only THREE specific git operations are exposed, not a generic
# "run any git command" tool. This is the same safety principle as the
# filesystem sandbox: the agent can only take actions we've explicitly built
# a function for. No push, no reset --hard, no force operations - nothing
# that could destroy work outside what these three functions allow.

def _run_git(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git"] + args,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=15,
    )


def create_branch(branch_name: str) -> str:
    """Create and switch to a new git branch for making the fix on.
    Should be called BEFORE any write_file calls, so the fix is isolated
    from the main branch and easy to review or discard."""
    # Basic sanitization: git branch names can't contain spaces or most
    # special characters anyway, but we normalize defensively.
    safe_name = "".join(c for c in branch_name if c.isalnum() or c in "-_/")
    if not safe_name:
        return "ERROR: branch name is empty after sanitization"
    try:
        result = _run_git(["checkout", "-b", safe_name])
        if result.returncode != 0:
            return f"ERROR creating branch: {result.stderr}"
        return f"Created and switched to branch '{safe_name}'"
    except Exception as e:
        return f"ERROR creating branch: {e}"


def git_diff() -> str:
    """Show the uncommitted changes (diff) currently in the working directory.
    Use this to review your own fix before committing it."""
    try:
        result = _run_git(["diff"])
        output = result.stdout + result.stderr
        return output if output.strip() else "(no uncommitted changes)"
    except Exception as e:
        return f"ERROR getting diff: {e}"


def commit_changes(message: str) -> str:
    """Stage and commit all current changes with the given commit message.
    Only call this AFTER run_tests confirms the fix actually works - never
    commit a broken state."""
    try:
        add_result = _run_git(["add", "-A"])
        if add_result.returncode != 0:
            return f"ERROR staging changes: {add_result.stderr}"

        commit_result = _run_git(["commit", "-m", message])
        if commit_result.returncode != 0:
            return f"ERROR committing (maybe nothing to commit?): {commit_result.stderr}"
        return f"Committed successfully: {commit_result.stdout.strip()}"
    except Exception as e:
        return f"ERROR committing: {e}"
