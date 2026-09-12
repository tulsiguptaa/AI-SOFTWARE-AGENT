"""
web/test_server_logic.py

Unit tests for sse_format() - pure formatting logic, no Flask server or
API key needed. Run with: python3 -m pytest web/test_server_logic.py -v
"""

import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from web.server import sse_format, try_start_run, finish_run


def test_formats_as_sse_data_line():
    event = {"type": "reasoning", "text": "hello"}
    formatted = sse_format(event)
    assert formatted.startswith("data: ")
    assert formatted.endswith("\n\n")


def test_payload_round_trips_through_json():
    event = {"type": "tool_call", "name": "read_file", "args": {"filename": "a.py"}}
    formatted = sse_format(event)
    payload = formatted[len("data: "):-2]  # strip "data: " prefix and trailing \n\n
    assert json.loads(payload) == event


# --- Run concurrency lock tests -----------------------------------------
# These exist because of a real bug: browsers auto-reconnect a Server-Sent
# Events stream whenever it closes (even a normal close), which could
# silently start a SECOND concurrent agent run and double the API request
# rate - exhausting a free-tier rate limit almost immediately. The lock
# makes that structurally impossible; these tests prove the lock's logic
# is correct without needing real threads, a real server, or an API key.

def test_first_caller_acquires_the_lock():
    assert try_start_run() is True
    finish_run()  # clean up so later tests aren't affected


def test_second_caller_is_rejected_while_locked():
    assert try_start_run() is True
    assert try_start_run() is False  # a "duplicate" caller must be rejected
    finish_run()


def test_lock_is_available_again_after_finish_run():
    assert try_start_run() is True
    finish_run()
    assert try_start_run() is True  # lock was properly released
    finish_run()


def test_finish_run_is_safe_to_call_when_not_locked():
    # Should never raise, even if called without a matching try_start_run -
    # e.g. if a route's try/finally runs finish_run() defensively.
    finish_run()
    finish_run()
