"""
test_agent_logic.py

Unit tests for the agent's CONTROL LOGIC - the parts that don't require
calling the LLM at all. This is a deliberate testing strategy: separate
"does my harness behave correctly" (fast, free, deterministic - test with
plain pytest) from "does the model reason well" (slow, costs money,
non-deterministic - that's what V5's SWE-bench evaluation is for).

Run with: python3 -m pytest test_agent_logic.py -v
"""

from agent import check_stagnation


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
