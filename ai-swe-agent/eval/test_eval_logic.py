"""
eval/test_eval_logic.py

Unit tests for compute_summary() - the eval harness's pure aggregation
function. Run with: python3 -m pytest eval/test_eval_logic.py -v

No API key or real scenario runs required - these test the arithmetic and
edge cases directly, using hand-built fake result dicts.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from eval.run_eval import compute_summary


def test_empty_results():
    summary = compute_summary([])
    assert summary["total"] == 0
    assert summary["pass_rate"] == 0.0


def test_all_passing():
    results = [
        {"success": True, "iterations_used": 4, "time_seconds": 10.0},
        {"success": True, "iterations_used": 6, "time_seconds": 20.0},
    ]
    summary = compute_summary(results)
    assert summary["total"] == 2
    assert summary["passed"] == 2
    assert summary["pass_rate"] == 1.0
    assert summary["avg_iterations"] == 5.0
    assert summary["avg_time_seconds"] == 15.0


def test_mixed_pass_fail():
    results = [
        {"success": True, "iterations_used": 4, "time_seconds": 10.0},
        {"success": False, "iterations_used": 15, "time_seconds": 40.0},
    ]
    summary = compute_summary(results)
    assert summary["passed"] == 1
    assert summary["pass_rate"] == 0.5


def test_all_failing():
    results = [
        {"success": False, "iterations_used": 15, "time_seconds": 50.0},
    ]
    summary = compute_summary(results)
    assert summary["passed"] == 0
    assert summary["pass_rate"] == 0.0
