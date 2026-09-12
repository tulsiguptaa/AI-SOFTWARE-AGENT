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
import re
import shutil
from pathlib import Path

# Restrict the agent to only this folder. This is a basic guardrail —
# without it, a prompt-injected or confused agent could try to read/write
# files anywhere on your system.
PROJECT_ROOT = Path(__file__).parent / "sample_project"


def set_project_root(path) -> None:
    """Point all tools at a different project directory.

    Exists for the evaluation harness (eval/run_eval.py), which needs to
    run the same agent against several different bug scenarios in one
    process. Every function below reads the PROJECT_ROOT global at CALL
    time (not at import time), so reassigning it here immediately affects
    all subsequent tool calls - no other changes needed."""
    global PROJECT_ROOT
    PROJECT_ROOT = Path(path)


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


def ensure_git_repo() -> str:
    """Initialize PROJECT_ROOT as a git repo if it isn't already one.

    Why this exists: the demo git history in sample_project/.git is
    deliberately NOT committed into this project's own GitHub repo (a
    nested .git folder would show up as a broken submodule link to anyone
    viewing the repo). That means a fresh clone has no git history at all -
    without this, create_branch would simply fail on first use. Calling
    this before every run makes the tool self-healing: it works correctly
    whether you're running it for the first time ever, or the hundredth."""
    if (PROJECT_ROOT / ".git").exists():
        return "Git repo already exists - nothing to do"
    _run_git(["init", "-q", "-b", "main"])
    _run_git(["config", "user.email", "agent@example.com"])
    _run_git(["config", "user.name", "AI SWE Agent"])
    _run_git(["add", "-A"])
    _run_git(["commit", "-q", "-m", "Initial commit"])
    return "Initialized a new git repo"


_SAMPLE_PROJECT_INVENTORY_BUGGY = '''from models import Product


def calculate_total(products: list[Product]) -> float:
    """Calculate the total value of all inventory."""
    total = 0
    for p in products:
        total += p.price * p.quantity  # BUG: Product has no 'price' attribute
    return total


def most_valuable(products: list[Product]) -> Product:
    """Return the product with the highest total value (price * quantity)."""
    return max(products, key=lambda p: p.unit_price * p.quantity)
'''


def reset_sample_project() -> str:
    """Restore sample_project/ to its original demo state: the known bug
    back in inventory.py, and git history wiped back to a single clean
    commit. This exists for the web UI's "Reset demo" button, so you can
    re-run the interactive demo repeatedly without it drifting into a
    fixed/committed state from a previous run."""
    inventory_path = PROJECT_ROOT / "inventory.py"
    inventory_path.write_text(_SAMPLE_PROJECT_INVENTORY_BUGGY)

    git_dir = PROJECT_ROOT / ".git"
    if git_dir.exists():
        shutil.rmtree(git_dir)
    ensure_git_repo()
    return "Sample project reset: bug restored, git history cleared"


def parse_test_result(output: str) -> dict:
    """Parse a pytest summary line (e.g. '3 failed, 4 passed in 0.02s' or
    '7 passed in 0.01s') into a structured result.

    This is a pure function (no side effects) so it can be unit tested
    directly - see test_agent_logic.py. It exists so the HARNESS can know
    with certainty whether tests are passing, instead of only ever finding
    out via the model's own claim. Returns:
      {"passed": int, "failed": int, "all_passed": bool} on success, or
      {"passed": None, "failed": None, "all_passed": None} if the output
      couldn't be parsed (e.g. a genuine error, not a test summary)."""
    failed_match = re.search(r"(\d+)\s+failed", output)
    passed_match = re.search(r"(\d+)\s+passed", output)

    if not failed_match and not passed_match:
        return {"passed": None, "failed": None, "all_passed": None}

    failed = int(failed_match.group(1)) if failed_match else 0
    passed = int(passed_match.group(1)) if passed_match else 0
    return {"passed": passed, "failed": failed, "all_passed": failed == 0 and passed > 0}
