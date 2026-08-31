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
from mistralai.client import Mistral

import tools

load_dotenv()

client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])

# mistral-small-latest is fast and free-tier friendly and supports tool use.
# If you have access to it, "mistral-large-latest" or "codestral-latest"
# will reason better on trickier bugs - swap via this env var, no code change needed.
MODEL = os.environ.get("MISTRAL_MODEL", "mistral-small-latest")
MAX_ITERATIONS = 30  # slightly higher than V1 - search_code adds an extra step per bug

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
]

TOOL_FUNCTIONS = {
    "read_file": lambda inp: tools.read_file(inp["filename"]),
    "write_file": lambda inp: tools.write_file(inp["filename"], inp["content"]),
    "run_tests": lambda inp: tools.run_tests(),
    "list_files": lambda inp: tools.list_files(),
    "search_code": lambda inp: tools.search_code(inp["query"]),
}

SYSTEM_PROMPT = """You are an autonomous software engineering agent. You will be given \
a coding task involving a small Python project with multiple files. You have tools to \
list files, search across the codebase, read files, write files, and run the test suite.

Your process should be:
1. Run the tests first to see what's failing (if anything).
2. Read the failure carefully. If the error involves a class, function, or attribute \
you don't fully understand yet (e.g. "object has no attribute X"), use search_code to \
find where that thing is actually DEFINED before guessing at a fix - don't assume you \
already know the correct attribute/method names.
3. Read the relevant file(s) fully once you've located them.
4. Reason carefully about the ACTUAL bug based on evidence, not assumption.
5. Apply a fix using write_file (always write the complete file content).
6. Run the tests again to confirm the fix works.
7. If tests still fail, read the new output carefully and try again - do not repeat \
a fix that already failed.

When all tests pass, respond with plain text (no tool call) summarizing what you fixed \
and why. Do not claim success until run_tests actually shows all tests passing."""


def run_agent(task: str):
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task},
    ]

    for iteration in range(1, MAX_ITERATIONS + 1):
        print(f"\n{'='*60}\nITERATION {iteration}\n{'='*60}")

        response = client.chat.complete(
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
            print(f"[Tool result]:\n{str(result)[:500]}")

            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "name": call.function.name,
                "content": str(result),
            })

    print("\n[STOPPED: reached max iterations without confirmed success]")
    return None


if __name__ == "__main__":
    task = (
        "There is a bug somewhere in this project causing a test to fail. "
        "You are not told which file it's in - use your tools to find it, "
        "fix it, and confirm all tests pass."
    )
    run_agent(task)
