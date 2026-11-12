"""Offline regression for reservations and output identity guards."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading

import pytest

from infrastructure.compiler import Compiler
from infrastructure.utils.budget import BudgetExhausted, RunBudget


def test_retries_share_logical_call_but_reserve_each_attempt():
    budget = RunBudget({"calls": 1, "http_attempts": 2, "tokens": 100})
    budget.start_call()
    first = budget.reserve_attempt(20, 25)
    budget.dispatch(first)
    budget.settle(first, None)
    second = budget.reserve_attempt(20, 25)
    budget.dispatch(second)
    budget.settle(second, 35)
    with pytest.raises(BudgetExhausted, match="http_attempts"):
        budget.reserve_attempt(20, 25)
    assert budget.snapshot()["used"] == {"calls": 1, "http_attempts": 2, "tokens": 80}


def test_concurrent_reservations_cannot_oversubscribe():
    budget = RunBudget({"calls": 8, "http_attempts": 8, "tokens": 100})
    barrier = threading.Barrier(4)
    def attempt():
        budget.start_call()
        barrier.wait(timeout=5)
        try:
            return budget.reserve_attempt(25, 25)
        except BudgetExhausted:
            return None
    with ThreadPoolExecutor(max_workers=4) as pool:
        attempts = list(pool.map(lambda _: attempt(), range(4)))
    assert sum(item is not None for item in attempts) == 2
    assert budget.snapshot()["reserved_tokens"] == 100


@pytest.mark.parametrize("target", ["input", "inside", "ancestor", "source"])
def test_output_rejects_protected_directories(tmp_path, target):
    source = tmp_path / "requirements"
    source.mkdir()
    targets = {"input": source, "inside": source / "child",
        "ancestor": tmp_path, "source": Path(__file__).resolve().parents[1]}
    with pytest.raises(ValueError):
        Compiler(source, targets[target])


def test_time_reserve_is_available_to_local_verification():
    now = [0]
    budget = RunBudget({"seconds": 100}, clock=lambda: now[0])
    budget.reserve_final_checks = True
    now[0] = 88
    with pytest.raises(BudgetExhausted, match="model_seconds"):
        budget.start_call()
    assert budget.check_time() == 7
