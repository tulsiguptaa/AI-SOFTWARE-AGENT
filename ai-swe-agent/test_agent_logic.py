"""
test_agent_logic.py

Unit tests for the agent's CONTROL LOGIC - the parts that don't require
calling the LLM at all. This is a deliberate testing strategy: separate
"does my harness behave correctly" (fast, free, deterministic - test with
plain pytest) from "does the model reason well" (slow, costs money,
non-deterministic - that's what V5's SWE-bench evaluation is for).

Run with: python3 -m pytest test_agent_logic.py -v
"""

import pytest

from agent import check_stagnation, call_model_with_retry
from tools import parse_test_result


def test_first_call_is_never_a_repeat():
    seen = {}
    is_repeat = check_stagnation(seen, "run_tests:{}", "1 failed, 4 passed")
    assert is_repeat is False


def test_identical_call_and_result_is_flagged_as_repeat():
    seen = {}
    check_stagnation(seen, "read_file:{'filename': 'a.py'}", "print('hi')")
    is_repeat = check_stagnation(seen, "read_file:{'filename': 'a.py'}", "print('hi')")
    assert is_repeat is True


def test_same_call_with_different_result_is_not_a_repeat():
    # Same tool+args, but the world changed (e.g. run_tests before vs after
    # a fix) - this should NOT be flagged, because new information arrived.
    seen = {}
    check_stagnation(seen, "run_tests:{}", "1 failed, 4 passed")
    is_repeat = check_stagnation(seen, "run_tests:{}", "0 failed, 5 passed")
    assert is_repeat is False


def test_different_calls_never_collide():
    seen = {}
    check_stagnation(seen, "read_file:{'filename': 'a.py'}", "content A")
    is_repeat = check_stagnation(seen, "read_file:{'filename': 'b.py'}", "content A")
    # Same result string, but a DIFFERENT call signature - not a repeat,
    # since these are genuinely different actions.
    assert is_repeat is False


def test_stagnation_resets_after_a_different_successful_action():
    """Simulates the real loop: repeat, repeat, then a genuinely new action -
    consecutive_stagnant_calls should reset to 0, not keep climbing."""
    seen = {}
    results = [
        check_stagnation(seen, "write_file:{'filename': 'a.py'}", "wrote 10 chars"),
        check_stagnation(seen, "write_file:{'filename': 'a.py'}", "wrote 10 chars"),  # repeat
        check_stagnation(seen, "search_code:{'query': 'unit_price'}", "models.py:4: ..."),  # new
    ]
    assert results == [False, True, False]


# --- parse_test_result tests --------------------------------------------
# This function drives auto-completion: the harness force-stops the agent
# once tests pass AND a commit succeeds, instead of trusting the model to
# notice it's done and stop on its own. If this parser is wrong, the agent
# could either stop too early (thinking a failing run passed) or never
# auto-stop at all (missing a real passing run) - so it needs real coverage.

def test_parses_all_tests_passing():
    result = parse_test_result("========== 7 passed in 0.01s ==========")
    assert result == {"passed": 7, "failed": 0, "all_passed": True}


def test_parses_some_tests_failing():
    result = parse_test_result("===== 1 failed, 6 passed in 0.02s =====")
    assert result == {"passed": 6, "failed": 1, "all_passed": False}


def test_parses_all_tests_failing():
    result = parse_test_result("========== 3 failed in 0.01s ==========")
    assert result == {"passed": 0, "failed": 3, "all_passed": False}


def test_unparseable_output_returns_none_fields():
    # e.g. a genuine subprocess error, not a real pytest summary - the
    # harness must NOT assume "no failures found" means "tests passed".
    result = parse_test_result("ERROR: tests timed out after 30 seconds")
    assert result == {"passed": None, "failed": None, "all_passed": None}


# --- call_model_with_retry tests -----------------------------------------
# A fake SDKError-like error carrying just enough shape (raw_response with
# a .status_code) for the retry logic to inspect, without needing a real
# httpx.Response or a real API call. time.sleep is monkeypatched to a
# no-op so these tests run instantly instead of actually waiting.

class FakeRawResponse:
    def __init__(self, status_code):
        self.status_code = status_code


class FakeSDKError(Exception):
    """Stands in for mistralai's SDKError - same shape (.raw_response.status_code)
    that call_model_with_retry actually inspects."""
    def __init__(self, status_code):
        self.raw_response = FakeRawResponse(status_code)
        super().__init__(f"fake error {status_code}")


def test_succeeds_immediately_with_no_retries_needed(monkeypatch):
    monkeypatch.setattr("agent.time.sleep", lambda s: None)
    events = list(call_model_with_retry(lambda: "real result"))
    assert events == [{"type": "_response", "response": "real result"}]


def test_retries_on_429_then_succeeds(monkeypatch):
    monkeypatch.setattr("agent.time.sleep", lambda s: None)
    monkeypatch.setattr("agent.SDKError", FakeSDKError)  # so `except SDKError` catches our fake

    attempts = {"n": 0}
    def flaky_request():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise FakeSDKError(429)
        return "success on third try"

    events = list(call_model_with_retry(flaky_request))
    rate_limited_events = [e for e in events if e["type"] == "rate_limited"]
    final_event = events[-1]

    assert len(rate_limited_events) == 2  # failed twice, succeeded on 3rd
    assert rate_limited_events[0]["attempt"] == 1
    assert rate_limited_events[1]["attempt"] == 2
    assert final_event == {"type": "_response", "response": "success on third try"}


def test_gives_up_after_max_retries_and_raises(monkeypatch):
    monkeypatch.setattr("agent.time.sleep", lambda s: None)
    monkeypatch.setattr("agent.SDKError", FakeSDKError)

    def always_rate_limited():
        raise FakeSDKError(429)

    with pytest.raises(FakeSDKError):
        list(call_model_with_retry(always_rate_limited, max_retries=2))


def test_non_429_error_is_not_retried():
    def server_error():
        raise FakeSDKError(500)  # a real bug, not a transient rate limit

    with pytest.raises(FakeSDKError):
        list(call_model_with_retry(server_error))
