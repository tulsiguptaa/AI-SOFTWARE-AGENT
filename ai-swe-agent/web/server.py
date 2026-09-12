"""
web/server.py

A small Flask web UI for watching the agent work in real time, and for
running the evaluation suite from a browser instead of the terminal.

IMPORTANT: this changes NOTHING about how the agent behaves. It's a
second "renderer" on top of the exact same core loop (agent.run_agent_events)
and the exact same eval harness helpers (eval.run_eval) already built and
tested in earlier steps. The terminal scripts keep working exactly as
before - this just adds a browser as an additional way to watch a run.

Run with: python3 web/server.py
Then open http://localhost:5000
"""

import json
import sys
import threading
import time
from pathlib import Path

from flask import Flask, Response, render_template, request, jsonify

# Make the parent directory importable so we can reuse agent.py / tools.py /
# eval/run_eval.py exactly as they are - no duplicated logic.
sys.path.insert(0, str(Path(__file__).parent.parent))

import agent
import tools
from eval.run_eval import (
    SCENARIOS_DIR,
    TASK_PROMPT,
    prepare_scenario,
    verify_success,
    compute_summary,
)

app = Flask(__name__)

SAMPLE_PROJECT_ROOT = Path(__file__).parent.parent / "sample_project"

# Shared across BOTH the live-run stream and the eval-suite stream: only
# one real agent run should ever execute at a time. This exists because
# browsers auto-reconnect a Server-Sent Events connection whenever it
# closes - including a NORMAL close after the agent finishes - unless the
# client calls .close() before the browser notices the connection ended.
# That's a real race: relying on client-side timing to prevent a second,
# concurrent run (which would double the API request rate and exhaust a
# free-tier rate limit almost immediately) isn't reliable. Enforcing "only
# one run at a time" here, in the server, makes it impossible regardless
# of what caused the duplicate request - an accidental browser reconnect,
# a double click, or two browser tabs open on the same page.
_agent_lock = threading.Lock()


def try_start_run() -> bool:
    """Returns True if no run was in progress and this call now owns the
    lock. Returns False immediately (non-blocking) if a run is already
    active - the caller should NOT start a second one."""
    return _agent_lock.acquire(blocking=False)


def finish_run() -> None:
    """Release the run lock. Always call in a finally block so a crashed
    run doesn't leave the lock stuck forever."""
    if _agent_lock.locked():
        _agent_lock.release()


def sse_format(event: dict) -> str:
    """Format a single event dict as one Server-Sent Event message.
    Pure function - see web/test_server_logic.py for direct unit tests."""
    return f"data: {json.dumps(event)}\n\n"


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/status")
def status():
    """Report the current real state of sample_project - never a cached
    guess. Used by the sidebar so the UI reflects reality on page load."""
    tools.set_project_root(SAMPLE_PROJECT_ROOT)
    tools.ensure_git_repo()
    output = tools.run_tests()
    parsed = tools.parse_test_result(output)
    branch_result = tools._run_git(["branch", "--show-current"])
    return jsonify({
        "tests_passing": parsed["all_passed"],
        "passed": parsed["passed"],
        "failed": parsed["failed"],
        "branch": branch_result.stdout.strip() or "main",
    })


@app.route("/api/files")
def list_files():
    """List every source file in sample_project, for the file explorer
    panel. Excludes .gitignore and dotfiles - those aren't part of the
    'codebase' a person browsing the demo cares about."""
    tools.set_project_root(SAMPLE_PROJECT_ROOT)
    files = []
    for p in sorted(SAMPLE_PROJECT_ROOT.iterdir()):
        if p.is_file() and not p.name.startswith("."):
            files.append({"name": p.name, "lines": len(p.read_text().splitlines())})
    return jsonify({"files": files})


@app.route("/api/file/<path:filename>")
def get_file(filename):
    """Return one file's current contents, for the code viewer panel.
    Reuses tools.read_file() directly - the exact same sandboxed read
    the agent itself uses, so the UI can never see anything the agent
    couldn't."""
    tools.set_project_root(SAMPLE_PROJECT_ROOT)
    content = tools.read_file(filename)
    return jsonify({"filename": filename, "content": content})


@app.route("/api/reset", methods=["POST"])
def reset():
    tools.set_project_root(SAMPLE_PROJECT_ROOT)
    message = tools.reset_sample_project()
    return jsonify({"message": message})


@app.route("/api/run-stream")
def run_stream():
    """Stream a live agent run against sample_project as Server-Sent
    Events. Reuses agent.run_agent_events() directly - the identical
    generator the terminal script consumes, just rendered differently."""

    def generate():
        if not try_start_run():
            yield sse_format({"type": "already_running"})
            return
        try:
            tools.set_project_root(SAMPLE_PROJECT_ROOT)
            for event in agent.run_agent_events(TASK_PROMPT):
                yield sse_format(event)
        finally:
            finish_run()

    return Response(generate(), mimetype="text/event-stream")


@app.route("/api/eval-stream")
def eval_stream():
    """Run the full 3-scenario evaluation suite, streaming every agent
    event AND the final scored result for each scenario, exactly
    reusing eval/run_eval.py's prepare_scenario/verify_success/
    compute_summary helpers - same ground-truth verification, same
    'never trust the model's claim' principle, just a browser view."""

    def generate():
        if not try_start_run():
            yield sse_format({"type": "already_running"})
            return

        try:
            scenario_dirs = sorted(p for p in SCENARIOS_DIR.iterdir() if p.is_dir())
            results = []

            for scenario_dir in scenario_dirs:
                yield sse_format({"type": "scenario_start", "scenario": scenario_dir.name})
                temp_dir = prepare_scenario(scenario_dir)

                start = time.time()
                stopped_event = None
                for event in agent.run_agent_events(TASK_PROMPT):
                    yield sse_format({"type": "agent_event", "scenario": scenario_dir.name, "event": event})
                    if event["type"] == "stopped":
                        stopped_event = event
                elapsed = time.time() - start

                verification = verify_success(temp_dir)
                success = verification["tests_passing"] and verification["committed_a_fix"]
                result = {
                    "scenario": scenario_dir.name,
                    "success": success,
                    "tests_passing": verification["tests_passing"],
                    "committed_a_fix": verification["committed_a_fix"],
                    "stopped_reason": stopped_event["reason"] if stopped_event else "unknown",
                    "iterations_used": stopped_event["iterations_used"] if stopped_event else 0,
                    "time_seconds": round(elapsed, 1),
                }
                results.append(result)
                yield sse_format({"type": "scenario_result", **result})

            summary = compute_summary(results)
            yield sse_format({"type": "eval_summary", "summary": summary})
        finally:
            finish_run()

    return Response(generate(), mimetype="text/event-stream")


if __name__ == "__main__":
    app.run(debug=True, threaded=True, port=5000)
