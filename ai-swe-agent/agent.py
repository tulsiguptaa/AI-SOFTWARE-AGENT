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
from dotenv import load_dotenv
from mistralai.client import Mistral  # v2.x SDK: imports moved from `mistralai` to
                                       # `mistralai.client` - a breaking change from v1.
                                       # See: github.com/mistralai/client-python/blob/main/MIGRATION.md

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
MAX_ITERATIONS = 12  # V4: raised again - branch/diff/commit adds 3 more steps per fix

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


def run_agent(task: str):
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task},
    ]

    # --- Stagnation tracking -------------------------------------------
    # Maps a "call signature" (tool name + its exact arguments) to the
    # result it produced last time. If we see the SAME signature produce
    # the SAME result again, no new information entered the conversation -
    # that's the definition of stagnation, not "trying again."
    seen_results: dict[str, str] = {}
    consecutive_stagnant_calls = 0
    STAGNATION_LIMIT = 2  # after this many repeats in a row, force a hard stop

    for iteration in range(1, MAX_ITERATIONS + 1):
        print(f"\n{'='*60}\nITERATION {iteration}\n{'='*60}")

        # Warn the model when it's running low on budget, so it prioritizes
        # wrapping up instead of exploring speculatively.
        remaining = MAX_ITERATIONS - iteration + 1
        if remaining == 2:
            messages.append({
                "role": "user",
                "content": "[SYSTEM NOTE: You have 2 iterations left. Prioritize "
                            "applying and confirming a fix over further exploration.]",
            })

        response = get_client().chat.complete(
            model=MODEL,
            messages=messages,
            tools=TOOL_SCHEMAS,
            tool_choice="auto",
        )

        message = response.choices[0].message
        # Append the assistant's message to history exactly as returned -
        # Mistral needs to see its own prior tool_calls in later turns.
        messages.append(message)

        if message.content and message.content.strip():
            print(f"\n[Model's reasoning]:\n{message.content}")

        if not message.tool_calls:
            # No tool call means the model thinks it's done.
            print("\n[Agent finished - no more tool calls]")
            return message

        # Execute each requested tool call and reply with a "tool" message
        for call in message.tool_calls:
            args = json.loads(call.function.arguments)
            print(f"\n[Tool call]: {call.function.name}({json.dumps(args)})")
            try:
                result = TOOL_FUNCTIONS[call.function.name](args)
            except Exception as e:
                result = f"ERROR executing tool: {e}"
            result_str = str(result)
            print(f"[Tool result]:\n{result_str[:500]}")

            # --- Stagnation check --------------------------------------
            signature = f"{call.function.name}:{json.dumps(args, sort_keys=True)}"
            is_repeat = check_stagnation(seen_results, signature, result_str)

            if is_repeat:
                consecutive_stagnant_calls += 1
                print(f"[STAGNATION DETECTED: repeat #{consecutive_stagnant_calls}]")
                result_str += (
                    "\n\n[SYSTEM NOTE: You already performed this exact action and got "
                    "this exact result before. Repeating it again will not produce new "
                    "information. Stop and change approach: reconsider your hypothesis "
                    "about the bug, search for something you haven't checked yet, or "
                    "read a different file.]"
                )
            else:
                consecutive_stagnant_calls = 0

            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "name": call.function.name,
                "content": result_str,
            })

        if consecutive_stagnant_calls >= STAGNATION_LIMIT:
            print(f"\n[STOPPED: {STAGNATION_LIMIT} consecutive stagnant actions detected - "
                  f"agent appears stuck in a loop]")
            return None

    print("\n[STOPPED: reached max iterations without confirmed success]")
    return None


if __name__ == "__main__":
    task = (
        "There is a bug somewhere in this project causing a test to fail. "
        "You are not told which file it's in - use your tools to find it, "
        "fix it, and confirm all tests pass."
    )
    run_agent(task)
