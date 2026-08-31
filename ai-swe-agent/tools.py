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
    """Overwrite a file in the sample project with new content."""
    try:
        path = _safe_path(filename)
        path.write_text(content)
        return f"Successfully wrote {len(content)} characters to {filename}"
    except Exception as e:
        return f"ERROR writing {filename}: {e}"


def run_tests() -> str:
    """Run the pytest suite inside the sample project and return the output.
    This is how the agent 'observes' whether its fix worked."""
    try:
        result = subprocess.run(
            ["python3", "-m", "pytest", "-v", "--tb=short"],
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
