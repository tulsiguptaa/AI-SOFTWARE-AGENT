"""
agent.py

Core agent loop, using the Mistral API.

Same ReAct pattern as before (Reason -> Act -> Observe -> Repeat), but
Mistral's tool-calling format is OpenAI-style rather than Anthropic-style:

  - Tools are declared as {"type": "function", "function": {...}}
  - The model's tool requests show up as message.tool_calls (a list),
    where each call has an .id, and .function.name / .function.arguments
    (arguments arrive as a JSON STRING, not a dict - we have to parse it)
  - We reply to each tool call with its own message:
        {"role": "tool", "tool_call_id": ..., "name": ..., "content": ...}

This is a good thing to have actually seen: different LLM providers speak
slightly different "dialects" of the same underlying idea (function
calling). Once you understand the pattern, switching providers is a
translation exercise, not a redesign.
"""

import os
import json
import time
from dotenv import load_dotenv
from mistralai.client import Mistral  # v2.x SDK: imports moved from `mistralai` to
                                       # `mistralai.client` - a breaking change from v1.
                                       # See: github.com/mistralai/client-python/blob/main/MIGRATION.md
from mistralai.client.errors.sdkerror import SDKError

import tools

load_dotenv()

# We deliberately DON'T create the client here at import time. If we did,
# simply importing this module (e.g. to unit-test check_stagnation) would
# require a real MISTRAL_API_KEY to exist - coupling pure logic to a
# secret it doesn't actually need. Instead we create it lazily, the first
# time it's actually needed.
_client = None


def get_client() -> Mistral:
    global _client
    if _client is None:
        _client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
    return _client

# mistral-small-latest is fast and free-tier friendly and supports tool use.
# If you have access to it, "mistral-large-latest" or "codestral-latest"
# will reason better on trickier bugs - swap via this env var, no code change needed.
MODEL = os.environ.get("MISTRAL_MODEL", "mistral-small-latest")
MAX_ITERATIONS = 15  # this is now a hard safety ceiling only - normal runs should
                      # finish via the auto-complete check below, well before this

# --- Tool definitions ---------------------------------------------------
# OpenAI-style schema: Mistral (and OpenAI, and most other providers) use
# this nested {"type": "function", "function": {...}} wrapper. Anthropic's
# is flatter. Same information, different envelope.

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file in the project so you can inspect its current code.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string", "description": "Name of the file, e.g. 'calculator.py'"}
                },
                "required": ["filename"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Overwrite a file with new content. Use this to apply your fix. Always write the FULL file content, not a diff/snippet.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string"},
                    "content": {"type": "string", "description": "The complete new content of the file"},
                },
                "required": ["filename", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_tests",
            "description": "Run the test suite and get the results. Use this to check whether your fix worked, and to see failures before you've made a fix.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_code",
            "description": "Search all files in the project for a keyword or substring (like grep). Use this to find where a class, function, or variable is defined/used when the bug spans multiple files, or when you don't yet know which file to read.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Keyword to search for, e.g. a class name, attribute, or function name"}
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List all files in the project.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_branch",
            "description": "Create and switch to a new git branch. Call this BEFORE making any file edits, so your fix is isolated on its own branch rather than made directly on main.",
            "parameters": {
                "type": "object",
                "properties": {
                    "branch_name": {"type": "string", "description": "e.g. 'fix/product-price-attribute'"}
                },
                "required": ["branch_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_diff",
            "description": "Show the uncommitted changes in the working directory as a diff. Use this to review your fix before committing.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "commit_changes",
            "description": "Stage and commit all current changes with a descriptive commit message. Only call this AFTER run_tests confirms the fix works - never commit a broken state.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "A clear, descriptive commit message explaining the fix"}
                },
                "required": ["message"],
            },
        },
    },
]

TOOL_FUNCTIONS = {
    "read_file": lambda inp: tools.read_file(inp["filename"]),
    "write_file": lambda inp: tools.write_file(inp["filename"], inp["content"]),
    "run_tests": lambda inp: tools.run_tests(),
    "list_files": lambda inp: tools.list_files(),
    "search_code": lambda inp: tools.search_code(inp["query"]),
    "create_branch": lambda inp: tools.create_branch(inp["branch_name"]),
    "git_diff": lambda inp: tools.git_diff(),
    "commit_changes": lambda inp: tools.commit_changes(inp["message"]),
}

SYSTEM_PROMPT = """You are an autonomous software engineering agent. You will be given \
a coding task involving a small Python project with multiple files, tracked in git. \
You have tools to list files, search across the codebase, read files, write files, run \
the test suite, and work with git (branch, diff, commit).

Your process should be:
1. Create a new git branch for this fix FIRST, before editing anything. Use a short, \
descriptive branch name like 'fix/<what-you're-fixing>'.
2. Run the tests to see what's failing (if anything).
3. Read the failure carefully. If the error involves a class, function, or attribute \
you don't fully understand yet (e.g. "object has no attribute X"), use search_code to \
find where that thing is actually DEFINED before guessing at a fix - don't assume you \
already know the correct attribute/method names.
4. Read the relevant file(s) fully once you've located them.
5. Reason carefully about the ACTUAL bug based on evidence, not assumption.
6. Apply a fix using write_file (always write the complete file content). Only edit \
files that are directly necessary to fix the bug - do not create new files, and do not \
make speculative or unrelated changes "just to check" something.
7. Run the tests again to confirm the fix works. If tests still fail, read the new \
output carefully and try again - do not repeat a fix that already failed.
8. Once tests pass, use git_diff to review exactly what changed. Check specifically: \
does every changed line relate directly to the bug you were asked to fix? If you see \
any file or change you can't justify as necessary for the fix, that is a mistake - \
do not commit it.
9. Commit the change with commit_changes, using a clear message explaining WHAT was \
wrong and WHY your fix addresses it. Never commit while tests are failing.

When done, respond with plain text (no tool call) summarizing what you fixed and \
confirming it was committed. Do not claim success until run_tests actually shows all \
tests passing AND the fix has been committed."""


def call_model_with_retry(make_request, max_retries: int = 5, base_delay: float = 3.0):
    """Generator that calls make_request() and retries automatically on
    HTTP 429 (rate limit) with exponential backoff (3s, 6s, 12s, 24s, 48s).

    Yields {"type": "rate_limited", "attempt": n, "wait_seconds": s} for
    each retry, so callers (the terminal and the web UI) can show the
    person what's happening instead of the connection appearing to hang.
    Once a request succeeds, yields exactly one final
    {"type": "_response", "response": result} event.

    Any OTHER error (not a 429), or a 429 that persists after max_retries,
    is re-raised - the caller (run_agent_events) is responsible for
    turning that into a clean "stopped" event instead of letting it crash
    the whole process. Free-tier API keys hit rate limits often enough
    that NOT handling this specifically would make the agent flaky in a
    way that has nothing to do with its actual reasoning ability."""
    for attempt in range(max_retries + 1):
        try:
            result = make_request()
            yield {"type": "_response", "response": result}
            return
        except SDKError as e:
            status_code = getattr(getattr(e, "raw_response", None), "status_code", None)
            if status_code == 429 and attempt < max_retries:
                wait_seconds = base_delay * (2 ** attempt)
                yield {"type": "rate_limited", "attempt": attempt + 1, "wait_seconds": wait_seconds}
                time.sleep(wait_seconds)
                continue
            raise


def check_stagnation(seen_results: dict, signature: str, result_str: str) -> bool:
    """Returns True if this exact (tool call, result) pair has been seen before.
    Mutates seen_results in place to record the latest result for this signature.

    This is deliberately a pure-ish function (no API calls, no side effects
    beyond the dict passed in) so it can be unit tested directly - see
    test_agent_logic.py. Testing your control flow this way, independent of
    the LLM, is standard practice: it's cheap, instant, and deterministic,
    whereas testing via real API calls is slow, costs money, and the model's
    non-determinism makes failures hard to reproduce."""
    is_repeat = seen_results.get(signature) == result_str
    seen_results[signature] = result_str
    return is_repeat


def run_agent_events(task: str):
    """Run the agent loop, YIELDING structured events instead of printing.

    This is the single source of truth for the agent loop's logic. Both
    the terminal script (run_agent, below) and the web UI (web/server.py)
    consume this same generator and render its events differently - one
    prints to stdout, the other streams to a browser. This is the same
    "separate logic from presentation" principle behind check_stagnation
    and parse_test_result being pure, testable functions: the loop itself
    shouldn't care how its progress gets displayed.

    Yields dicts with a "type" key, e.g.:
      {"type": "iteration_start", "iteration": 1, "remaining": 15}
      {"type": "reasoning", "text": "..."}
      {"type": "tool_call", "name": "run_tests", "args": {}}
      {"type": "tool_result", "name": "run_tests", "result": "...", "is_stagnant_repeat": False}
      {"type": "stopped", "reason": "auto_complete" | "model_stopped" | "stagnation" | "max_iterations", "iterations_used": N}
    The final event is always the "stopped" event."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task},
    ]

    tools.ensure_git_repo()

    seen_results: dict[str, str] = {}
    consecutive_stagnant_calls = 0
    STAGNATION_LIMIT = 2

    tests_currently_passing = False
    fix_committed = False

    for iteration in range(1, MAX_ITERATIONS + 1):
        remaining = MAX_ITERATIONS - iteration + 1
        yield {"type": "iteration_start", "iteration": iteration, "remaining": remaining}

        if remaining == 2:
            messages.append({
                "role": "user",
                "content": "[SYSTEM NOTE: You have 2 iterations left. Prioritize "
                            "applying and confirming a fix over further exploration.]",
            })
            yield {"type": "budget_warning"}

        try:
            response = None
            for retry_event in call_model_with_retry(
                lambda: get_client().chat.complete(
                    model=MODEL,
                    messages=messages,
                    tools=TOOL_SCHEMAS,
                    tool_choice="auto",
                )
            ):
                if retry_event["type"] == "_response":
                    response = retry_event["response"]
                else:
                    yield retry_event
        except Exception as e:
            # Anything that survives retries (a non-429 error, or a 429
            # that persisted past max_retries) ends the run cleanly - the
            # caller (terminal or web UI) sees a real message, not a
            # crashed connection with no explanation.
            yield {"type": "api_error", "message": str(e)}
            yield {"type": "stopped", "reason": "api_error", "iterations_used": iteration}
            return

        message = response.choices[0].message
        messages.append(message)

        if message.content and message.content.strip():
            yield {"type": "reasoning", "text": message.content}

        if not message.tool_calls:
            yield {"type": "stopped", "reason": "model_stopped", "iterations_used": iteration}
            return

        for call in message.tool_calls:
            args = json.loads(call.function.arguments)
            yield {"type": "tool_call", "name": call.function.name, "args": args}
            try:
                result = TOOL_FUNCTIONS[call.function.name](args)
            except Exception as e:
                result = f"ERROR executing tool: {e}"
            result_str = str(result)

            if call.function.name == "run_tests":
                parsed = tools.parse_test_result(result_str)
                if parsed["all_passed"] is not None:
                    tests_currently_passing = bool(parsed["all_passed"])
                    if not tests_currently_passing:
                        fix_committed = False
            if call.function.name == "commit_changes" and result_str.startswith("Committed successfully"):
                fix_committed = True

            signature = f"{call.function.name}:{json.dumps(args, sort_keys=True)}"
            is_repeat = check_stagnation(seen_results, signature, result_str)

            display_result = result_str
            if is_repeat:
                consecutive_stagnant_calls += 1
                display_result += (
                    "\n\n[SYSTEM NOTE: You already performed this exact action and got "
                    "this exact result before. Repeating it again will not produce new "
                    "information. Stop and change approach: reconsider your hypothesis "
                    "about the bug, search for something you haven't checked yet, or "
                    "read a different file.]"
                )
            else:
                consecutive_stagnant_calls = 0

            yield {
                "type": "tool_result",
                "name": call.function.name,
                "result": result_str,
                "is_stagnant_repeat": is_repeat,
                "stagnant_count": consecutive_stagnant_calls,
            }

            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "name": call.function.name,
                "content": display_result,
            })

        if consecutive_stagnant_calls >= STAGNATION_LIMIT:
            yield {"type": "stopped", "reason": "stagnation", "iterations_used": iteration}
            return

        if tests_currently_passing and fix_committed:
            yield {"type": "stopped", "reason": "auto_complete", "iterations_used": iteration}
            return

    yield {"type": "stopped", "reason": "max_iterations", "iterations_used": MAX_ITERATIONS}


# Human-readable terminal rendering for each event type. Kept separate
# from run_agent_events itself, so adding a new presentation (like the web
# UI) never means touching the loop's logic - only adding a new renderer.
def _print_event(event: dict) -> None:
    t = event["type"]
    if t == "iteration_start":
        print(f"\n{'='*60}\nITERATION {event['iteration']}\n{'='*60}")
    elif t == "budget_warning":
        print("[SYSTEM NOTE: 2 iterations left]")
    elif t == "reasoning":
        print(f"\n[Model's reasoning]:\n{event['text']}")
    elif t == "rate_limited":
        print(f"\n[RATE LIMITED - retry #{event['attempt']}, waiting {event['wait_seconds']}s before trying again]")
    elif t == "api_error":
        print(f"\n[API ERROR]: {event['message']}")
    elif t == "tool_call":
        print(f"\n[Tool call]: {event['name']}({json.dumps(event['args'])})")
    elif t == "tool_result":
        print(f"[Tool result]:\n{event['result'][:500]}")
        if event["is_stagnant_repeat"]:
            print(f"[STAGNATION DETECTED: repeat #{event['stagnant_count']}]")
    elif t == "stopped":
        labels = {
            "auto_complete": "[AUTO-COMPLETE: tests passing AND fix committed]",
            "model_stopped": "[Agent finished - no more tool calls]",
            "stagnation": "[STOPPED: consecutive stagnant actions detected]",
            "max_iterations": "[STOPPED: reached max iterations without confirmed success]",
            "api_error": "[STOPPED: unrecoverable API error - see message above]",
        }
        print(f"\n{labels.get(event['reason'], event['reason'])}")


def run_agent(task: str) -> dict:
    """Terminal entry point: consumes run_agent_events(), prints each event,
    and returns the final {"stopped_reason", "iterations_used"} dict -
    same public interface as before the refactor, so existing callers
    (eval/run_eval.py) don't need to change."""
    final = None
    for event in run_agent_events(task):
        _print_event(event)
        if event["type"] == "stopped":
            final = {"stopped_reason": event["reason"], "iterations_used": event["iterations_used"]}
    return final


if __name__ == "__main__":
    task = (
        "There is a bug somewhere in this project causing a test to fail. "
        "You are not told which file it's in - use your tools to find it, "
        "fix it, and confirm all tests pass."
    )
    result = run_agent(task)
    print(f"\n{'='*60}\nRUN SUMMARY: {result}\n{'='*60}")
