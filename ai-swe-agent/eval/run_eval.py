"""
eval/run_eval.py

A small, SWE-bench-INSPIRED evaluation harness (not the real SWE-bench -
see the README section "Why not full SWE-bench-lite" for the honest
scoping reasoning behind that choice).

The core idea, same as SWE-bench: give the agent a set of independent
tasks with known ground truth, run it against each one fresh, and measure
a real pass rate - instead of a single anecdotal "it worked when I ran it."

CRITICAL DESIGN PRINCIPLE: we NEVER trust the agent's own claim of success.
After each run, we independently verify by (a) actually running the test
suite ourselves and parsing the result, and (b) checking that a real git
commit was made. This is the same "verify, don't trust the model's
narrative" principle used throughout the project (see the auto-complete
fix in agent.py).

Run with: python3 eval/run_eval.py
"""

import shutil
import sys
import tempfile
import time
from pathlib import Path

# Make the parent directory importable so we can reuse agent.py / tools.py
sys.path.insert(0, str(Path(__file__).parent.parent))

import agent
import tools

SCENARIOS_DIR = Path(__file__).parent / "scenarios"

TASK_PROMPT = (
    "There is a bug somewhere in this project causing a test to fail. "
    "You are not told which file it's in - use your tools to find it, "
    "fix it, and confirm all tests pass."
)


def prepare_scenario(scenario_dir: Path) -> Path:
    """Copy a pristine scenario into a fresh temp directory and initialize
    it as a git repo with one clean commit. Using a fresh temp copy every
    run means results are reproducible and re-running the eval suite never
    accumulates leftover branches/commits from a previous run."""
    temp_dir = Path(tempfile.mkdtemp(prefix=f"eval_{scenario_dir.name}_"))
    shutil.copytree(scenario_dir, temp_dir, dirs_exist_ok=True)

    # Ensure .gitignore exists regardless of whether the scenario source
    # folder remembered to include one - otherwise __pycache__/*.pyc files
    # get swept into the agent's commit and pollute the diff (a real bug
    # we hit while building this: see README).
    gitignore = temp_dir / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("__pycache__/\n*.pyc\n.pytest_cache/\n")

    tools.set_project_root(temp_dir)
    tools._run_git(["init", "-q", "-b", "main"])
    tools._run_git(["config", "user.email", "agent@example.com"])
    tools._run_git(["config", "user.name", "AI SWE Agent"])
    tools._run_git(["add", "-A"])
    tools._run_git(["commit", "-q", "-m", "Initial commit"])
    return temp_dir


def verify_success(temp_dir: Path) -> dict:
    """Independently verify the outcome - never trust the agent's claim.
    Checks two things: (1) do tests actually pass right now, and (2) did
    the agent actually make a git commit (i.e. did it follow the intended
    workflow, not just silently edit files without committing)."""
    tools.set_project_root(temp_dir)
    test_output = tools.run_tests()
    parsed = tools.parse_test_result(test_output)

    log_result = tools._run_git(["log", "--oneline", "--all"])
    commit_count = len(log_result.stdout.strip().splitlines())

    return {
        "tests_passing": bool(parsed["all_passed"]),
        "committed_a_fix": commit_count > 1,  # more than just the initial commit
    }


def run_scenario(scenario_dir: Path) -> dict:
    print(f"\n{'#'*70}\n# SCENARIO: {scenario_dir.name}\n{'#'*70}")
    temp_dir = prepare_scenario(scenario_dir)

    start = time.time()
    run_result = agent.run_agent(TASK_PROMPT)
    elapsed = time.time() - start

    verification = verify_success(temp_dir)
    success = verification["tests_passing"] and verification["committed_a_fix"]

    return {
        "scenario": scenario_dir.name,
        "success": success,
        "tests_passing": verification["tests_passing"],
        "committed_a_fix": verification["committed_a_fix"],
        "stopped_reason": run_result["stopped_reason"],
        "iterations_used": run_result["iterations_used"],
        "time_seconds": round(elapsed, 1),
        "workdir": str(temp_dir),  # left on disk for manual inspection
    }


def compute_summary(results: list) -> dict:
    """Pure aggregation function - no side effects, so it's directly unit
    testable (see eval/test_eval_logic.py) without needing to run any real
    scenario or call the API."""
    total = len(results)
    if total == 0:
        return {"total": 0, "passed": 0, "pass_rate": 0.0, "avg_iterations": 0.0, "avg_time_seconds": 0.0}
    passed = sum(1 for r in results if r["success"])
    avg_iterations = sum(r["iterations_used"] for r in results) / total
    avg_time = sum(r["time_seconds"] for r in results) / total
    return {
        "total": total,
        "passed": passed,
        "pass_rate": round(passed / total, 3),
        "avg_iterations": round(avg_iterations, 1),
        "avg_time_seconds": round(avg_time, 1),
    }


def main():
    scenario_dirs = sorted(p for p in SCENARIOS_DIR.iterdir() if p.is_dir())
    if not scenario_dirs:
        print(f"No scenarios found in {SCENARIOS_DIR}")
        return

    results = [run_scenario(d) for d in scenario_dirs]
    summary = compute_summary(results)

    print(f"\n\n{'='*70}\nEVALUATION RESULTS\n{'='*70}")
    for r in results:
        status = "PASS" if r["success"] else "FAIL"
        print(
            f"[{status}] {r['scenario']:<15} "
            f"iterations={r['iterations_used']:<3} "
            f"time={r['time_seconds']}s "
            f"stopped_reason={r['stopped_reason']}"
        )
        if not r["success"]:
            print(f"         tests_passing={r['tests_passing']} committed_a_fix={r['committed_a_fix']}")
            print(f"         inspect at: {r['workdir']}")

    print(f"\n{'-'*70}")
    print(f"Pass rate: {summary['passed']}/{summary['total']} ({summary['pass_rate']*100:.1f}%)")
    print(f"Avg iterations per scenario: {summary['avg_iterations']}")
    print(f"Avg time per scenario: {summary['avg_time_seconds']}s")
    print(f"{'='*70}")


if __name__ == "__main__":
    main()
